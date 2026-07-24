"""Refresh per-date Headout prices into ``price_observations``.

For every Headout competitor option we already have in ``options``
(``extraction_model='headout-api'``), this fetches inventory in rolling 7-day
windows across the next ``config.DATE_LOOKAHEAD_DAYS`` days and stores one
observation per (option_id, target_date).

Idempotent: prior Headout observations for the option are deleted before
re-inserting so re-runs don't accumulate duplicates.

Usage
-----

    python -m src.refresh_headout_date_prices --pilot                    # PoC 5 only
    python -m src.refresh_headout_date_prices --all                      # every option
    python -m src.refresh_headout_date_prices --limit 20                 # first N (for smoke)
    python -m src.refresh_headout_date_prices --all --parallelism 6      # (Headout serialises; keep low)
"""
from __future__ import annotations

import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any

from src import config, db, headout_client

_DB_LOCK = threading.Lock()


def _windows(days: int, window_size: int = 7) -> list[tuple[str, str]]:
    """Return a list of (start_date, end_date) ISO strings covering N days
    from today, in consecutive `window_size`-day chunks (default 7)."""
    today = date.today()
    out: list[tuple[str, str]] = []
    day = today
    end = today + timedelta(days=days)
    while day < end:
        chunk_end = min(day + timedelta(days=window_size - 1), end - timedelta(days=1))
        out.append((day.isoformat(), chunk_end.isoformat()))
        day = chunk_end + timedelta(days=1)
    return out


def _observations_for_variant(
    variant_id: str,
    windows: list[tuple[str, str]],
    sleep_between: float = 0.15,
) -> list[tuple[str, float, str]]:
    """Return [(target_date, price, currency)] across all windows.

    Deduped by target_date (Headout can return several slots per day; we take
    the first with a valid adult price)."""
    out: dict[str, tuple[float, str]] = {}
    for start, end in windows:
        try:
            inv = headout_client.list_inventory_by_variant(
                variant_id, start_date=start, end_date=end, force_currency="USD"
            )
        except Exception as e:
            print(f"    ! variant {variant_id} window {start}..{end} failed: {e}")
            time.sleep(sleep_between)
            continue
        for item in inv.get("items") or []:
            dt = item.get("startDateTime")
            if not dt:
                continue
            target_date = dt[:10]
            if target_date in out:
                continue  # keep first slot for the day
            pricing = item.get("pricing") or {}
            person = headout_client.pick_person_price(pricing.get("persons") or [])
            if person is None:
                continue
            price = person.get("headoutSellingPrice") or person.get("price")
            if price is None:
                continue
            try:
                out[target_date] = (float(price), "USD")
            except (TypeError, ValueError):
                continue
        time.sleep(sleep_between)
    return [(d, p, cur) for d, (p, cur) in sorted(out.items())]


def _refresh_one_option(
    option_id: int,
    variant_id: str,
    windows: list[tuple[str, str]],
    now: str,
    market: str,
    sleep_between: float,
) -> tuple[int, int]:
    """Returns (written, 1_if_empty_else_0). Serialised DB write via _DB_LOCK."""
    obs = _observations_for_variant(variant_id, windows, sleep_between)
    if not obs:
        return (0, 1)
    with _DB_LOCK:
        conn = db.get_conn()
        try:
            conn.execute("BEGIN")
            conn.execute(
                "DELETE FROM price_observations WHERE option_id=? AND capture_method='headout-api'",
                (option_id,),
            )
            for target_date, price, currency in obs:
                conn.execute(
                    """INSERT INTO price_observations
                       (option_id, price, currency, market,
                        target_date, captured_at, is_spike_flagged, capture_method)
                       VALUES (?, ?, ?, ?, ?, ?, 0, 'headout-api')""",
                    (option_id, price, currency, market, target_date, now),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return (len(obs), 0)


def refresh(
    only_pilot: bool = False,
    all_options: bool = False,
    limit: int | None = None,
    days: int | None = None,
    sleep_between: float = 0.15,
    parallelism: int = 8,
    skip_done: bool = False,
) -> dict[str, int]:
    if not (only_pilot or all_options or limit):
        raise ValueError("Pass --pilot, --all, or --limit N")

    days = days or config.DATE_LOOKAHEAD_DAYS
    windows = _windows(days)
    now = datetime.now(timezone.utc).isoformat()
    market = config.PILOT_MARKET

    print(f"Windows to fetch per variant: {len(windows)} × 7 days = {days} days")
    print(f"Parallelism: {parallelism}")

    db.init_db()
    conn = db.get_conn()

    q = """SELECT o.id, o.fingerprint_json
           FROM options o
           JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
           JOIN competitors c ON c.id = cl.competitor_id
           WHERE o.source='competitor' AND o.extraction_model='headout-api'"""
    if only_pilot:
        q += f" AND c.rayna_product_id IN ({','.join(str(i) for i in config.PILOT_PRODUCT_IDS)})"
    q += " ORDER BY o.id"
    if limit:
        q += f" LIMIT {int(limit)}"

    rows = list(conn.execute(q))

    # optional resume: skip options that already have >=5 observations
    if skip_done and rows:
        already = {
            r["option_id"]
            for r in conn.execute(
                "SELECT option_id, COUNT(*) c FROM price_observations "
                "WHERE capture_method='headout-api' GROUP BY option_id HAVING c >= 5"
            )
        }
        rows = [r for r in rows if r["id"] not in already]
        print(f"skip_done: {len(already)} options already covered; {len(rows)} left")

    conn.close()

    print(f"Options to refresh: {len(rows)}")
    if not rows:
        return {"options_refreshed": 0, "observations_written": 0, "options_empty": 0}

    n_written = 0
    n_empty = 0
    done = 0
    started = time.monotonic()

    import json as _json

    tasks = []
    for row in rows:
        fp = _json.loads(row["fingerprint_json"] or "{}")
        variant_id = str(fp.get("headout_variant_id") or "")
        if not variant_id:
            n_empty += 1
            continue
        tasks.append((row["id"], variant_id))

    with ThreadPoolExecutor(max_workers=parallelism) as pool:
        fut_map = {
            pool.submit(_refresh_one_option, oid, vid, windows, now, market, sleep_between): oid
            for oid, vid in tasks
        }
        for fut in as_completed(fut_map):
            try:
                w, e = fut.result()
            except Exception as exc:
                print(f"    ! option {fut_map[fut]} unexpected error: {exc}")
                w, e = (0, 1)
            n_written += w
            n_empty += e
            done += 1
            if done % 20 == 0 or done == len(tasks):
                elapsed = time.monotonic() - started
                rate = done / max(elapsed, 0.001)
                eta = (len(tasks) - done) / max(rate, 0.001)
                print(f"  {done}/{len(tasks)}  ({rate:.2f}/s, ~{eta/60:.1f} min left)  written so far: {n_written}")

    return {
        "options_refreshed": len(rows),
        "options_processed": len(tasks),
        "observations_written": n_written,
        "options_empty": n_empty,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--pilot", action="store_true")
    grp.add_argument("--all", action="store_true", dest="all_options")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--sleep", type=float, default=0.15)
    p.add_argument("--parallelism", type=int, default=8)
    p.add_argument("--skip-done", action="store_true",
                   help="skip options that already have >=5 observations")
    args = p.parse_args()

    r = refresh(
        only_pilot=args.pilot,
        all_options=args.all_options,
        limit=args.limit,
        days=args.days,
        sleep_between=args.sleep,
        parallelism=args.parallelism,
        skip_done=args.skip_done,
    )
    print("refresh_headout_date_prices: done")
    for k, v in r.items():
        print(f"  {k:<40} {v}")
