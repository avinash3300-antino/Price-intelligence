"""Ingest Headout as a *real* live competitor into our SQLite.

For each Rayna product whose city is in ``config.HEADOUT_CITY_CODES``:

1. Fetch Headout's catalog for the city.
2. Take the top ``FUZZY_SHORTLIST`` Headout products by fuzzy name score.
3. Ask Claude Haiku (:mod:`src.match_headout`) whether each candidate is the
   SAME real-world experience as the Rayna product (apple-to-apple).
4. Keep only Claude's ``same_product=true`` verdicts.
5. Insert one ``competitors`` row (``seller_domain='headout.com'``), one
   ``competitor_listings`` per kept Headout product, and one ``options`` row
   (``source='competitor'``) per Headout variant — priced from Headout's
   inventory endpoint (7-day window, USD, adult tier).

Re-runs are idempotent for the ``headout.com`` seller only: prior Headout
listings + options for the target Rayna products are deleted first so we
don't accumulate duplicates. Dummy competitors are already gone by the time
this runs; other sellers (real Claude-extracted, if any survive) are left
untouched.

Usage
-----

    python -m src.ingest_headout_competitors --city Dubai
    python -m src.ingest_headout_competitors --city Dubai --pilot     # only PoC IDs
    python -m src.ingest_headout_competitors --city Dubai --limit 20  # first N Rayna products
    python -m src.ingest_headout_competitors --all-cities             # every mapped city

"""
from __future__ import annotations

import argparse
import re
import time
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

from src import config, db, headout_client, match_headout

HEADOUT_SELLER_DOMAIN = "headout.com"
HEADOUT_SELLER_NAME = "Headout"

# Fuzzy pre-filter: number of candidates the LLM will adjudicate per Rayna
# product. 15 = balance of coverage vs. Claude cost/time. Original was 5
# (missed many real matches for popular categories); 25 was tried but 3x
# slower for only marginal gains beyond top-15.
FUZZY_SHORTLIST = 15
FUZZY_MIN_SCORE = 0.20

# 7-day window ~5 weeks out — far enough that early inventory is loaded but
# still returned as page 1 by Headout's paginated inventory endpoint.
_INV_WINDOW_START = "2026-08-05"
_INV_WINDOW_END = "2026-08-11"


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _score(rayna_name: str, headout_name: str) -> float:
    a, b = _norm(rayna_name), _norm(headout_name)
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    a_toks = set(a.split())
    b_toks = set(b.split())
    overlap = len(a_toks & b_toks) / max(len(a_toks), 1)
    return ratio + overlap


def _shortlist(
    rayna_name: str, headout_products: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Cheap fuzzy shortlist for the Claude adjudicator to score."""
    scored = [(_score(rayna_name, hp.get("name") or ""), hp) for hp in headout_products]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [hp for s, hp in scored[:FUZZY_SHORTLIST] if s >= FUZZY_MIN_SCORE]


def _delete_existing_headout(conn, rayna_product_ids: list[int]) -> tuple[int, int]:
    """Wipe existing Headout listings + options for a batch of Rayna products
    (competitor row stays and gets its listings replaced)."""
    if not rayna_product_ids:
        return (0, 0)
    ph = ",".join("?" * len(rayna_product_ids))
    comp_ids = [
        r["id"]
        for r in conn.execute(
            f"SELECT id FROM competitors WHERE seller_domain=? "
            f"AND rayna_product_id IN ({ph})",
            [HEADOUT_SELLER_DOMAIN, *rayna_product_ids],
        )
    ]
    if not comp_ids:
        return (0, 0)
    cph = ",".join("?" * len(comp_ids))
    listing_ids = [
        r["id"]
        for r in conn.execute(
            f"SELECT id FROM competitor_listings WHERE competitor_id IN ({cph})",
            comp_ids,
        )
    ]
    n_opts = 0
    if listing_ids:
        lph = ",".join("?" * len(listing_ids))
        # drop mappings + price_observations first (FK)
        conn.execute(
            f"DELETE FROM mappings WHERE competitor_option_id IN "
            f"(SELECT id FROM options WHERE source='competitor' AND competitor_listing_id IN ({lph}))",
            listing_ids,
        )
        conn.execute(
            f"DELETE FROM price_observations WHERE option_id IN "
            f"(SELECT id FROM options WHERE source='competitor' AND competitor_listing_id IN ({lph}))",
            listing_ids,
        )
        cur = conn.execute(
            f"DELETE FROM options WHERE source='competitor' AND competitor_listing_id IN ({lph})",
            listing_ids,
        )
        n_opts = cur.rowcount or 0
        conn.execute(
            f"DELETE FROM competitor_listings WHERE id IN ({lph})",
            listing_ids,
        )
    return (len(listing_ids), n_opts)


def _upsert_competitor(
    conn, rayna_product_id: int, market: str, top_url: str, now: str
) -> int:
    conn.execute(
        """INSERT OR IGNORE INTO competitors
           (rayna_product_id, market, seller_domain, seller_name,
            seed_url, snippet, search_rank, search_query,
            classified_as, classifier_confidence, classifier_reason,
            sells_this_product, classified_at, discovered_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                   'real_seller', 1.0, 'Headout Partner API (verified)',
                   1, ?, ?)""",
        (
            rayna_product_id,
            market,
            HEADOUT_SELLER_DOMAIN,
            HEADOUT_SELLER_NAME,
            top_url,
            "Real seller — Headout Partner API",
            1,
            "",
            now,
            now,
        ),
    )
    row = conn.execute(
        "SELECT id FROM competitors WHERE rayna_product_id=? AND market=? AND seller_domain=?",
        (rayna_product_id, market, HEADOUT_SELLER_DOMAIN),
    ).fetchone()
    return int(row["id"])


def _headout_variant_price(
    variant_id: str,
) -> tuple[float | None, str | None]:
    """Return (customer_facing_price, currency) or (None, None) if no inventory."""
    try:
        inv = headout_client.list_inventory_by_variant(
            variant_id,
            start_date=_INV_WINDOW_START,
            end_date=_INV_WINDOW_END,
            force_currency="USD",
        )
    except Exception as e:
        print(f"    ! inventory fetch failed for variant {variant_id}: {e}")
        return (None, None)

    for item in inv.get("items") or []:
        pricing = item.get("pricing") or {}
        person = headout_client.pick_person_price(pricing.get("persons") or [])
        if person is None:
            continue
        # `headoutSellingPrice` = what a customer pays on headout.com.
        # That is the price Rayna competes against, so it's the right column.
        price = person.get("headoutSellingPrice") or person.get("price")
        if price is None:
            continue
        try:
            return (float(price), "USD")
        except (TypeError, ValueError):
            continue
    return (None, None)


def ingest_city(
    city_name: str,
    only_rayna_ids: list[int] | None = None,
    limit: int | None = None,
    sleep_between_variants: float = 0.18,
    dry_run: bool = False,
) -> dict[str, Any]:
    city_code = config.HEADOUT_CITY_CODES.get(city_name)
    if not city_code:
        raise RuntimeError(
            f"No Headout cityCode mapping for {city_name!r}. "
            f"Add it to config.HEADOUT_CITY_CODES first."
        )

    now = datetime.now(timezone.utc).isoformat()

    db.init_db()
    conn = db.get_conn()

    q = "SELECT id, name, type, city, country, market, raw_json FROM products WHERE city=?"
    args: list[Any] = [city_name]
    if only_rayna_ids:
        ph = ",".join("?" * len(only_rayna_ids))
        q += f" AND id IN ({ph})"
        args.extend(only_rayna_ids)
    q += " ORDER BY id"
    if limit:
        q += f" LIMIT {int(limit)}"
    rayna_products = [dict(r) for r in conn.execute(q, args)]
    if not rayna_products:
        conn.close()
        print(f"No Rayna products found for city={city_name!r} (with filters).")
        return {"rayna_products_considered": 0}

    print(f"Fetching Headout catalogue for {city_name} ({city_code}) …")
    headout_products = headout_client.list_products(city_code)
    print(f"  Headout returned {len(headout_products)} products.")
    if not headout_products:
        conn.close()
        return {"rayna_products_considered": len(rayna_products), "headout_products": 0}

    n_matched_rayna = 0
    n_shortlisted_total = 0
    n_claude_yes = 0
    n_claude_no = 0
    n_listings = 0
    n_options_priced = 0
    n_options_unpriced = 0
    unmatched: list[dict[str, Any]] = []

    rayna_ids_touched = [p["id"] for p in rayna_products]
    if not dry_run:
        del_l, del_o = _delete_existing_headout(conn, rayna_ids_touched)
        if del_l or del_o:
            print(f"  cleared {del_l} old Headout listings / {del_o} options")

    for rp in rayna_products:
        shortlist = _shortlist(rp["name"], headout_products)
        if not shortlist:
            unmatched.append({"id": rp["id"], "name": rp["name"], "reason": "no fuzzy shortlist"})
            continue
        n_shortlisted_total += len(shortlist)

        verdicts = match_headout.adjudicate_batch(rp, shortlist)
        by_id = {v["headout_id"]: v for v in verdicts}
        kept: list[dict[str, Any]] = []
        for hp in shortlist:
            v = by_id.get(str(hp.get("id"))) or {}
            if v.get("same_product"):
                kept.append(hp)
                n_claude_yes += 1
            else:
                n_claude_no += 1

        if not kept:
            unmatched.append({
                "id": rp["id"], "name": rp["name"],
                "reason": "no apple-to-apple match after Claude",
            })
            continue

        n_matched_rayna += 1
        top_url = kept[0].get("canonicalUrl") or ""

        if dry_run:
            print(f"[dry] #{rp['id']} {rp['name']!r}:")
            for hp in kept:
                v = by_id.get(str(hp.get("id"))) or {}
                print(f"    ✓ conf={v.get('confidence', 0):.2f}  #{hp.get('id')}  {(hp.get('name') or '')[:70]}")
            continue

        try:
            with conn:
                comp_id = _upsert_competitor(conn, rp["id"], rp["market"] or "UAE", top_url, now)

                for hp in kept:
                    listing_url = hp.get("canonicalUrl") or ""
                    variants = hp.get("variants") or []

                    # Store the whole Headout product blob in raw_markdown so
                    # the enricher (src.enrich_competitor_options) can pull
                    # description / highlights / duration / etc. out later.
                    raw_hp_json = __import__("json").dumps(hp, ensure_ascii=False)
                    cur = conn.execute(
                        """INSERT INTO competitor_listings
                           (competitor_id, listing_url, title,
                            raw_markdown, raw_html, scraped_at, scrape_method)
                           VALUES (?, ?, ?, ?, NULL, ?, 'headout_api')""",
                        (comp_id, listing_url, hp.get("name") or "", raw_hp_json, now),
                    )
                    listing_id = cur.lastrowid
                    n_listings += 1

                    for variant in variants:
                        vid = str(variant.get("id"))
                        vname = variant.get("name") or "Variant"
                        price, currency = _headout_variant_price(vid)
                        time.sleep(sleep_between_variants)
                        if price is None:
                            n_options_unpriced += 1
                            # Still record the variant, without a price — the UI
                            # tolerates None prices already.
                        else:
                            n_options_priced += 1
                        fp = {
                            "vendor": "headout",
                            "headout_variant_id": vid,
                            "headout_product_id": hp.get("id"),
                            "tier": (vname or "").lower().replace(" ", "_")[:40],
                            "pricing_basis": "per_adult",
                        }
                        # Persist the variant blob (plus a pointer to its parent
                        # product) so the enricher gets full context.
                        raw_variant_json = __import__("json").dumps(
                            {"variant": variant, "product_id": hp.get("id")},
                            ensure_ascii=False,
                        )
                        conn.execute(
                            """INSERT INTO options
                               (source, competitor_listing_id, name, pricing_basis,
                                price, currency, market, fingerprint_json,
                                raw_extracted_json, extraction_model, extracted_at)
                               VALUES ('competitor', ?, ?, 'per_adult', ?, ?, ?, ?,
                                       ?, 'headout-api', ?)""",
                            (
                                listing_id,
                                f"{hp.get('name')} – {vname}",
                                price,
                                currency,
                                rp["market"] or "UAE",
                                __import__("json").dumps(fp, ensure_ascii=False),
                                raw_variant_json,
                                now,
                            ),
                        )
        except Exception as e:
            print(f"  ! failed on Rayna #{rp['id']} {rp['name']!r}: {e}")

    conn.close()

    print()
    print(f"Rayna products considered: {len(rayna_products)}")
    print(f"  fuzzy shortlisted total: {n_shortlisted_total} candidates")
    print(f"  Claude YES:              {n_claude_yes}")
    print(f"  Claude NO:               {n_claude_no}")
    print(f"  matched to Headout:      {n_matched_rayna}")
    print(f"  unmatched:               {len(unmatched)}")
    print(f"Listings created:          {n_listings}")
    print(f"Variant options priced:    {n_options_priced}")
    print(f"Variant options unpriced:  {n_options_unpriced}")
    if unmatched and len(unmatched) <= 20:
        print("\nUnmatched Rayna products:")
        for u in unmatched:
            print(f"  #{u['id']}  {u['name']}  — {u.get('reason', '')}")

    return {
        "city": city_name,
        "rayna_products_considered": len(rayna_products),
        "shortlisted_total": n_shortlisted_total,
        "claude_yes": n_claude_yes,
        "claude_no": n_claude_no,
        "matched": n_matched_rayna,
        "unmatched": len(unmatched),
        "listings_created": n_listings,
        "options_priced": n_options_priced,
        "options_unpriced": n_options_unpriced,
    }


def ingest_all_cities(
    limit_per_city: int | None = None,
    sleep_between_variants: float = 0.18,
) -> list[dict[str, Any]]:
    """Run ``ingest_city`` for every city in ``config.HEADOUT_CITY_CODES``
    that has any Rayna products.
    """
    conn = db.get_conn()
    try:
        city_counts = {
            r["city"]: r["c"]
            for r in conn.execute(
                "SELECT city, COUNT(*) c FROM products WHERE city IS NOT NULL "
                "GROUP BY city ORDER BY c DESC"
            )
        }
    finally:
        conn.close()

    cities = [c for c in config.HEADOUT_CITY_CODES.keys() if city_counts.get(c, 0) > 0]
    print(f"=== Running Headout ingest for {len(cities)} cities ===")
    for c in cities:
        print(f"  · {c:22} ({city_counts[c]} Rayna products)")

    results: list[dict[str, Any]] = []
    for i, city in enumerate(cities, 1):
        print(f"\n{'#' * 60}")
        print(f"# [{i}/{len(cities)}] {city}")
        print(f"{'#' * 60}")
        try:
            r = ingest_city(
                city_name=city,
                limit=limit_per_city,
                sleep_between_variants=sleep_between_variants,
            )
            results.append(r)
        except Exception as e:
            print(f"  ! city {city!r} failed: {e}")
            results.append({"city": city, "error": str(e)})

    print("\n=== Cross-city summary ===")
    print(f"{'city':22} {'products':>8} {'matched':>8} {'listings':>8} {'priced':>7}")
    for r in results:
        if "error" in r:
            print(f"{r['city']:22} ERROR: {r['error'][:40]}")
        else:
            print(
                f"{r['city']:22} "
                f"{r['rayna_products_considered']:>8} "
                f"{r['matched']:>8} "
                f"{r['listings_created']:>8} "
                f"{r['options_priced']:>7}"
            )
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--city", help="Rayna city name (e.g. 'Dubai')")
    p.add_argument("--all-cities", action="store_true",
                   help="Run ingest for every Rayna city with a Headout mapping")
    p.add_argument("--pilot", action="store_true",
                   help="Only process PILOT_PRODUCT_IDS (single-city only)")
    p.add_argument("--rayna-product-id", type=int, action="append", default=[],
                   help="Restrict to these Rayna product IDs. Repeatable. Single-city only.")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true",
                   help="Show matches without writing to DB (single-city only)")
    args = p.parse_args()

    if args.all_cities:
        ingest_all_cities(limit_per_city=args.limit)
    else:
        if not args.city:
            p.error("either --city or --all-cities is required")
        if args.rayna_product_id:
            only = args.rayna_product_id
        elif args.pilot:
            only = config.PILOT_PRODUCT_IDS
        else:
            only = None
        ingest_city(
            city_name=args.city,
            only_rayna_ids=only,
            limit=args.limit,
            dry_run=args.dry_run,
        )
