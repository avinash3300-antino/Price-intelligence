"""Ingest the full Rayna catalogue from the live API endpoint.

Pulls https://data-projects-flax.vercel.app/api/enriched-feed%sformat=json, caches
the raw response to data/rayna_catalog_live.json (so the rest of the pipeline can
run offline / for debugging), then upserts every row into the products table.

Falls back to the static rayna_catalog_sample.json if the API call fails — this
lets the demo keep working when the network is down.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from src import config, db

API_URL = config.RAYNA_API_BASE + config.RAYNA_ENRICHED_FEED
REQUEST_TIMEOUT_S = 60


def _fetch_live() -> dict[str, Any]:
    # The Vercel endpoint now 302-redirects to a Blob storage URL for the
    # cached-hourly snapshot. Follow redirects so daily cron actually gets
    # fresh data instead of silently falling back to the disk cache.
    r = httpx.get(API_URL, timeout=REQUEST_TIMEOUT_S, follow_redirects=True)
    r.raise_for_status()
    data = r.json()
    config.CATALOG_LIVE_PATH.write_text(json.dumps(data, ensure_ascii=False))
    return data


def _load_catalog() -> tuple[dict[str, Any], str]:
    """Return (catalog, source) where source is 'live' or 'cache' or 'sample'."""
    try:
        return _fetch_live(), "live"
    except Exception as e:
        print(f"  ! live fetch failed ({type(e).__name__}: {e}); falling back to cache/sample")
    if config.CATALOG_LIVE_PATH.exists():
        return json.loads(config.CATALOG_LIVE_PATH.read_text()), "cache"
    if config.CATALOG_PATH.exists():
        return json.loads(config.CATALOG_PATH.read_text()), "sample"
    raise RuntimeError("No catalog source available (API down and no local file).")


def ingest(only_pilot: bool = False) -> int:
    """Ingest all products from the catalog.

    only_pilot=True restricts to PILOT_PRODUCT_IDS (handy when running expensive
    downstream stages). Default is False — bring in the whole catalogue.
    """
    catalog, source = _load_catalog()

    feed_currency = catalog.get("currency", config.PILOT_CURRENCY)
    now = datetime.now(timezone.utc).isoformat()

    rows = list(catalog.get("products") or [])
    if only_pilot:
        keep = set(config.PILOT_PRODUCT_IDS)
        rows = [r for r in rows if r.get("productId") in keep]

    # de-dup on productId — the API can return multiple enriched rows per product
    by_id: dict[int, dict[str, Any]] = {}
    for r in rows:
        pid = r.get("productId")
        if pid is None:
            continue
        prev = by_id.get(pid)
        if prev is None or (r.get("_enriched") and not prev.get("_enriched")):
            by_id[pid] = r

    db.init_db()
    inserted = 0
    with db.tx() as conn:
        cur = conn.cursor()
        for pid, r in by_id.items():
            cur.execute(
                """
                INSERT INTO products
                  (id, name, type, city, country, market, currency, url, raw_json, ingested_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET
                  name = EXCLUDED.name, type = EXCLUDED.type,
                  city = EXCLUDED.city, country = EXCLUDED.country,
                  market = EXCLUDED.market, currency = EXCLUDED.currency,
                  url = EXCLUDED.url, raw_json = EXCLUDED.raw_json,
                  ingested_at = EXCLUDED.ingested_at
                """,
                (
                    pid,
                    r.get("name") or r.get("title") or "",
                    r.get("type") or r.get("product_type"),
                    r.get("city"),
                    r.get("country"),
                    config.PILOT_MARKET,
                    r.get("currency") or feed_currency,
                    r.get("url"),
                    json.dumps(r, ensure_ascii=False),
                    now,
                ),
            )
            inserted += 1

    stats = catalog.get("stats") or {}
    print(
        f"Catalog source: {source}  "
        f"(API stats: totalProducts={stats.get('totalProducts')}, "
        f"enriched={stats.get('enriched')})"
    )
    print(
        f"Ingested {inserted} distinct products "
        f"(deduped from {len(rows)} feed rows) into {config.DB_PATH}"
    )
    return inserted


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument(
        "--pilot",
        action="store_true",
        help="Only ingest the 5 PoC product IDs from config.PILOT_PRODUCT_IDS",
    )
    args = p.parse_args()
    ingest(only_pilot=args.pilot)
