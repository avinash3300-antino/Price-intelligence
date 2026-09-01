"""Re-fetch the competitor prices behind mapped pairs.

A competitor price used to be written once, when someone pasted the URL, and
never touched again — so /mapped compared a Rayna price refreshed that morning
against a competitor price up to twelve days old and called the difference a
live gap.

This job closes that. For every distinct seller URL behind a manual mapping:

  1. fetch the page through the same four-stage chain the paste flow uses
  2. hash the content; if it matches the previous run, skip Claude entirely
  3. otherwise re-extract, and update the price of options we already hold
  4. record a price_observation either way, so history accumulates

What it does not do, deliberately:

* **Never inserts options.** New packages on a page are a mapping decision, not
  a price refresh. They arrive when someone pastes the URL again.
* **Never deletes or unmaps.** An option missing from the page is flagged by
  leaving last_seen_at behind, not removed. A transient fetch failure must not
  destroy a human's mapping — the same reasoning as the feed-blackout guard on
  the Rayna side.

The hash check is what makes a nightly run affordable: fetching is cheap,
extraction is not, and most pages do not change on most nights.

Usage:
    python -m src.refresh_competitor_prices [--limit N] [--force] [--workers N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from datetime import datetime, timezone
from typing import Any, Optional

from src import add_by_url, config, db, fx_rates

# Fetching is the slow part and Playwright is heavy, so this stays low. The job
# has all night; hammering seven sellers in parallel is how you get blocked.
DEFAULT_WORKERS = 3

_db_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(name: str) -> str:
    """Lowercased, alphanumeric-only form of an option name."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


# Words that appear in most option names and so carry no discriminating
# signal. Left in the comparison they inflate every score toward each other.
_NOISE = {
    "per", "adult", "ticket", "tickets", "the", "and", "with", "for", "a", "an",
    "of", "to", "at", "in", "from", "on", "or", "plus", "combo", "option",
    "entry", "access", "pass", "tour", "experience", "dubai",
}


def _tokens(name: str) -> set[str]:
    return {t for t in _norm(name).split() if t not in _NOISE and len(t) > 1}


def _similarity(a: str, b: str) -> float:
    """0..1 similarity between two option names.

    Claude does not name options identically across extractions — the same
    Burj Khalifa package came back as a different string on the second run,
    which is what made exact matching flag 71 of 166 live options as missing.

    Token containment rather than plain overlap: one side is often a longer
    phrasing of the other ("Silver - At the Top Levels 124 & 125" vs "At the
    Top Levels 124 and 125 Silver"), and containment scores that as the near
    match it is. Falls back to sequence similarity when either side has no
    distinctive tokens left after noise removal.
    """
    ta, tb = _tokens(a), _tokens(b)
    if ta and tb:
        overlap = len(ta & tb)
        containment = overlap / min(len(ta), len(tb))
        jaccard = overlap / len(ta | tb)
        # Weighted toward containment, with Jaccard holding it back when one
        # name is much longer and merely happens to contain the other's words.
        return 0.7 * containment + 0.3 * jaccard
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


# Below this, two names are treated as different options rather than the same
# one renamed. Chosen so a genuine rename still matches while two distinct
# packages on the same page (Silver vs Gold vs Platinum) do not collapse.
_MATCH_THRESHOLD = 0.55


def _best_match(stored_name: str, candidates: list[Any], used: set[int]):
    """Closest unused extracted option to a stored one, or None.

    Greedy and one-to-one: each extracted option can claim at most one stored
    row, so two similar packages cannot both match the same candidate.
    """
    best, best_score, best_idx = None, 0.0, -1
    for i, cand in enumerate(candidates):
        if i in used:
            continue
        score = _similarity(stored_name, cand.name)
        if score > best_score:
            best, best_score, best_idx = cand, score, i
    if best is not None and best_score >= _MATCH_THRESHOLD:
        return best, best_idx, best_score
    return None, -1, best_score


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _listings_to_refresh(conn, limit: Optional[int]) -> list[dict[str, Any]]:
    """Distinct listings behind at least one manual mapping.

    Only mapped listings are worth the spend — an unmapped competitor option
    is not on anyone's screen as a gap.
    """
    sql = """
        SELECT DISTINCT cl.id, cl.listing_url, cl.content_hash, cc.seller_domain
        FROM mappings m
        JOIN options co ON co.id = m.competitor_option_id
        JOIN competitor_listings cl ON cl.id = co.competitor_listing_id
        JOIN competitors cc ON cc.id = cl.competitor_id
        WHERE m.is_manual = TRUE
        ORDER BY cl.id
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [dict(r) for r in conn.execute(sql)]


def _record_observation(conn, option_id: int, price: float, currency: str) -> None:
    """Append to price history.

    target_date is today: this is 'the price the seller showed on this date',
    which is what a trend needs. Rayna's per-date observations mean something
    different (the price for travel on that date) but share the table.
    """
    conn.execute(
        """INSERT INTO price_observations
             (option_id, price, currency, market, target_date, captured_at, capture_method)
           VALUES (%s, %s, %s, %s, %s, %s, 'competitor-refresh')""",
        (
            option_id, price, currency or "AED", config.PILOT_MARKET,
            datetime.now(timezone.utc).date().isoformat(), _now(),
        ),
    )


def _mark_all_seen(conn, listing_id: int, now: str) -> None:
    """Page unchanged, so every option we hold for it is still on it."""
    conn.execute(
        """UPDATE options SET last_checked_at = %s, last_seen_at = %s
           WHERE competitor_listing_id = %s AND source = 'competitor'""",
        (now, now, listing_id),
    )


def _process(listing: dict[str, Any], force: bool) -> dict[str, Any]:
    """Fetch, compare, and update one listing. Returns a result summary."""
    url = listing["listing_url"]
    result = {
        "listing_id": listing["id"],
        "seller": listing["seller_domain"],
        "status": "error",
        "changed": False,
        "prices_updated": 0,
        "options_seen": 0,
        "options_missing": 0,
        "error": None,
    }

    try:
        content, title = add_by_url.fetch_url_as_text(url)
    except add_by_url.FetchBlockedError as e:
        result["status"] = "blocked"
        result["error"] = str(e)[:200]
        with _db_lock, db.tx() as conn:
            conn.execute(
                """UPDATE competitor_listings
                   SET last_checked_at = %s, last_check_status = 'blocked'
                   WHERE id = %s""",
                (_now(), listing["id"]),
            )
        return result
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"[:200]
        return result

    digest = _content_hash(content)
    now = _now()

    # ---- unchanged: the expensive half is skipped -------------------------
    if digest == listing.get("content_hash") and not force:
        result["status"] = "unchanged"
        with _db_lock, db.tx() as conn:
            conn.execute(
                """UPDATE competitor_listings
                   SET last_checked_at = %s, last_check_status = 'unchanged'
                   WHERE id = %s""",
                (now, listing["id"]),
            )
            _mark_all_seen(conn, listing["id"], now)
            # Still record the price: "unchanged on this date" is a real data
            # point, and without it the history has holes on quiet days.
            for r in conn.execute(
                """SELECT id, price, currency FROM options
                   WHERE competitor_listing_id = %s AND source = 'competitor'
                     AND price IS NOT NULL""",
                (listing["id"],),
            ).fetchall():
                _record_observation(conn, r["id"], r["price"], r["currency"])
                result["options_seen"] += 1
        return result

    # ---- changed: re-extract ----------------------------------------------
    from anthropic import Anthropic
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    try:
        extracted = add_by_url.extract_competitor_options(client, content, url, title)
    except Exception as e:  # noqa: BLE001
        result["error"] = f"extract failed: {type(e).__name__}: {e}"[:200]
        return result

    with _db_lock, db.tx() as conn:
        rows = conn.execute(
            """SELECT id, name, price, currency FROM options
               WHERE competitor_listing_id = %s AND source = 'competitor'""",
            (listing["id"],),
        ).fetchall()

        used: set[int] = set()
        # Exact normalised matches first, so a perfect match is never stolen by
        # a fuzzy one processed earlier.
        ordered = sorted(
            rows,
            key=lambda r: 0 if any(_norm(r["name"]) == _norm(o.name) for o in extracted) else 1,
        )
        for row in ordered:
            match, idx, score = _best_match(row["name"], extracted, used)
            if match is not None:
                used.add(idx)
            if match is None:
                # Kept, not deleted — see the module docstring. last_seen_at
                # stays behind last_checked_at, which is the flag.
                conn.execute(
                    "UPDATE options SET last_checked_at = %s WHERE id = %s",
                    (now, row["id"]),
                )
                result["options_missing"] += 1
                continue

            currency = (match.currency or "").strip().upper() or None
            aed = fx_rates.to_aed(match.price, currency)
            price = aed if aed is not None else match.price
            stored_currency = "AED" if aed is not None else currency

            conn.execute(
                """UPDATE options
                   SET price = %s, currency = %s, previous_price = %s,
                       last_checked_at = %s, last_seen_at = %s,
                       raw_extracted_json = %s
                   WHERE id = %s""",
                (
                    price, stored_currency, row["price"], now, now,
                    match.model_dump_json(), row["id"],
                ),
            )
            result["options_seen"] += 1
            if price is not None and price != row["price"]:
                result["prices_updated"] += 1
            if price is not None:
                _record_observation(conn, row["id"], price, stored_currency or "AED")

        conn.execute(
            """UPDATE competitor_listings
               SET content_hash = %s, last_checked_at = %s,
                   last_check_status = 'updated', raw_markdown = %s,
                   scraped_at = %s
               WHERE id = %s""",
            (digest, now, content[:200000], now, listing["id"]),
        )

    result["status"] = "updated"
    result["changed"] = True
    return result


def run(limit: Optional[int] = None, force: bool = False,
        workers: int = DEFAULT_WORKERS) -> dict[str, Any]:
    conn = db.get_conn()
    try:
        listings = _listings_to_refresh(conn, limit)
    finally:
        conn.close()

    print(f"refresh_competitor_prices: {len(listings)} mapped listing(s), "
          f"{workers} worker(s), force={force}")

    totals = {
        "listings": len(listings), "unchanged": 0, "updated": 0,
        "blocked": 0, "error": 0, "prices_updated": 0,
        "options_seen": 0, "options_missing": 0,
    }
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_process, l, force): l for l in listings}
        for fut in as_completed(futs):
            l = futs[fut]
            try:
                r = fut.result()
            except Exception as e:  # noqa: BLE001
                totals["error"] += 1
                print(f"  ! {l['seller_domain']:<24} crashed: {type(e).__name__}: {e}")
                continue
            totals[r["status"]] = totals.get(r["status"], 0) + 1
            for k in ("prices_updated", "options_seen", "options_missing"):
                totals[k] += r[k]
            flag = {
                "unchanged": "=", "updated": "*", "blocked": "!", "error": "!",
            }.get(r["status"], "?")
            note = f" — {r['error']}" if r["error"] else ""
            print(f"  {flag} {r['seller']:<24} {r['status']:<10} "
                  f"seen={r['options_seen']} missing={r['options_missing']} "
                  f"repriced={r['prices_updated']}{note}")

    print("\nrefresh_competitor_prices: done")
    for k, v in totals.items():
        print(f"  {k:<20} {v}")
    return totals


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="only the first N listings (for testing)")
    ap.add_argument("--force", action="store_true",
                    help="re-extract even when the page content is unchanged")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = ap.parse_args()
    run(limit=args.limit, force=args.force, workers=args.workers)
    sys.exit(0)
