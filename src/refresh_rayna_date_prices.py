"""Snapshot Rayna variants' ``date_price[]`` into ``price_observations``.

The Vercel feed only exposes a rolling ~3-day window of per-date prices per
variant. That window is what we cache here. For any date OUTSIDE those 3
days, the backend falls back to the variant's base ``price`` (marked
``date_price_source='default'`` so the UI can flag it).

This module is a pure local read + insert — no external API calls, no
network. Runs in a few seconds for the whole 1,879-variant catalogue.

Idempotent: prior observations for the same (option_id, target_date) are
overwritten by inserting a fresh row (backend reads MAX(captured_at)).

Usage
-----

    python -m src.refresh_rayna_date_prices --all-products
    python -m src.refresh_rayna_date_prices --pilot     # PoC 5 only
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from src import config, db, feed_cache


def _iter_variant_rows(only_product_ids: set[int] | None):
    """Yield (rayna_product_id, variant_key, date_price_list, market)."""
    feed_cache.load_from_disk(force=True)
    for pid_str, prod in (feed_cache._payload or {}).get("products", {}).items():
        pid = int(pid_str)
        if only_product_ids and pid not in only_product_ids:
            continue
        for opt in prod.get("options") or []:
            for variant in opt.get("variants") or []:
                dp = variant.get("date_price") or []
                if not dp:
                    continue
                # need to compute the same synthetic id used by sync_options_from_feed
                synth = feed_cache.variant_synthetic_id(
                    pid, opt.get("group_id"), variant.get("option_id")
                )
                yield synth, pid, dp, variant.get("currency") or prod.get("currency") or "AED"


def refresh(
    only_pilot: bool = False,
    all_products: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    if only_pilot:
        only = set(config.PILOT_PRODUCT_IDS)
    elif all_products:
        only = None
    else:
        raise ValueError("Pass --pilot or --all-products")

    now = datetime.now(timezone.utc).isoformat()
    market = config.PILOT_MARKET

    db.init_db()
    conn = db.get_conn()

    n_variants = 0
    n_rows = 0
    n_sold_out = 0
    n_missing_option = 0

    try:
        # existing rayna option ids in DB (we can only insert observations for
        # options that actually exist, else FK will reject)
        valid_option_ids = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM options WHERE source='rayna'"
            )
        }

        for synth_id, product_id, dp, currency in _iter_variant_rows(only):
            n_variants += 1
            if synth_id not in valid_option_ids:
                n_missing_option += 1
                continue

            # delete prior observations for this option so re-runs don't stack
            if not dry_run:
                conn.execute(
                    "DELETE FROM price_observations WHERE option_id=%s",
                    (synth_id,),
                )

            for row in dp:
                d = row.get("date")
                price = row.get("price")
                sold_out = bool(row.get("sold_out"))
                if not d or price is None:
                    continue
                if sold_out:
                    n_sold_out += 1
                    # still record price so UI can show the number (they're
                    # comparable), but flag via is_spike_flagged=0 for now
                if not dry_run:
                    conn.execute(
                        """INSERT INTO price_observations
                           (option_id, price, currency, market,
                            target_date, captured_at, is_spike_flagged, capture_method)
                           VALUES (%s, %s, %s, %s, %s, %s, 0, 'vercel-feed')""",
                        (synth_id, float(price), currency, market, d, now),
                    )
                    n_rows += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "variants_scanned": n_variants,
        "observations_written": n_rows,
        "sold_out_rows": n_sold_out,
        "variants_missing_in_options_table": n_missing_option,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--pilot", action="store_true", help="only the 5 PoC products")
    grp.add_argument("--all-products", action="store_true", help="every Rayna variant")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    result = refresh(only_pilot=args.pilot, all_products=args.all_products, dry_run=args.dry_run)
    print("refresh_rayna_date_prices: done")
    for k, v in result.items():
        print(f"  {k:<40} {v}")
