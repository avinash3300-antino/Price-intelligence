"""Firecrawl-based competitor PDP scraper.

Brief's Stage 3: collect each discovered seller's product page so we can
extract options and the real per-customer price.

For the PoC we scrape the URL we got from search (the search-result link),
which is usually a product detail page or a category/listing page. If it's
a listing page with multiple offerings, the option extractor will surface
each offering as a distinct option.

Idempotent: skips competitors that already have a non-empty markdown body
in competitor_listings (re-run safe).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx

from src import config, db

FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"
MAX_PER_PRODUCT = 6           # scrape top-N real sellers per product
REQUEST_TIMEOUT_S = 90
INTER_REQUEST_SLEEP_S = 1.5   # be polite + respect Firecrawl rate limits


def scrape_url(url: str) -> tuple[str | None, str | None, dict]:
    """Returns (markdown, title, raw_response_meta)."""
    r = httpx.post(
        FIRECRAWL_ENDPOINT,
        headers={
            "Authorization": f"Bearer {config.FIRECRAWL_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
            "waitFor": 1500,
        },
        timeout=REQUEST_TIMEOUT_S,
    )
    r.raise_for_status()
    payload = r.json()
    if not payload.get("success"):
        raise RuntimeError(f"Firecrawl returned success=false: {payload}")
    data = payload.get("data", {})
    md = data.get("markdown") or ""
    meta = data.get("metadata") or {}
    title = meta.get("title") or meta.get("ogTitle")
    return md, title, {"firecrawl_meta": meta}


def already_scraped(conn, competitor_id: int) -> bool:
    row = conn.execute(
        """SELECT 1 FROM competitor_listings
           WHERE competitor_id=? AND raw_markdown IS NOT NULL AND length(raw_markdown) > 200
           LIMIT 1""",
        (competitor_id,),
    ).fetchone()
    return row is not None


def run() -> None:
    db.init_db()

    conn = db.get_conn()
    products = list(conn.execute("SELECT id, name FROM products ORDER BY id"))

    targets: list[dict] = []
    for p in products:
        rows = list(
            conn.execute(
                """SELECT id, rayna_product_id, seller_domain, seed_url, search_rank
                   FROM competitors
                   WHERE rayna_product_id=? AND sells_this_product=1
                     AND seed_url IS NOT NULL
                   ORDER BY search_rank
                   LIMIT ?""",
                (p["id"], MAX_PER_PRODUCT),
            )
        )
        for r in rows:
            targets.append({
                "competitor_id": r["id"],
                "product_id": p["id"],
                "product_name": p["name"],
                "domain": r["seller_domain"],
                "url": r["seed_url"],
                "rank": r["search_rank"],
            })
    conn.close()

    print(f"{len(targets)} competitor URL(s) to scrape "
          f"(max {MAX_PER_PRODUCT} per product, sellers only)\n")

    successes = failures = skipped = 0

    for i, t in enumerate(targets, 1):
        conn = db.get_conn()
        try:
            if already_scraped(conn, t["competitor_id"]):
                print(f"  [{i:>2}/{len(targets)}] skip (cached) {t['domain']}")
                skipped += 1
                continue
        finally:
            conn.close()

        print(f"  [{i:>2}/{len(targets)}] {t['domain']} → {t['url'][:80]}")
        try:
            md, title, meta = scrape_url(t["url"])
        except httpx.HTTPStatusError as e:
            print(f"    ! HTTP {e.response.status_code}: {e.response.text[:120]}")
            failures += 1
            time.sleep(INTER_REQUEST_SLEEP_S)
            continue
        except Exception as e:
            print(f"    ! {type(e).__name__}: {e}")
            failures += 1
            time.sleep(INTER_REQUEST_SLEEP_S)
            continue

        now = datetime.now(timezone.utc).isoformat()
        with db.tx() as conn:
            conn.execute(
                """INSERT INTO competitor_listings
                     (competitor_id, listing_url, title, raw_markdown, raw_html, scraped_at, scrape_method)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    t["competitor_id"],
                    t["url"],
                    title,
                    md,
                    None,
                    now,
                    "firecrawl_v1",
                ),
            )

        kb = len(md) // 1024
        print(f"    ✓ {kb} KB markdown, title={title!r}")
        successes += 1
        time.sleep(INTER_REQUEST_SLEEP_S)

    print(f"\nScraping complete: {successes} ok, {failures} failed, {skipped} skipped")


if __name__ == "__main__":
    run()
