"""Ingest GlobalTix as a second live competitor (alongside Headout).

For each Rayna product whose country maps to a GlobalTix country code:

1. Fetch GlobalTix's catalog for the country (paginated).
2. Fuzzy shortlist top-5 candidates by name similarity.
3. Ship them (shape-shifted into the same schema Headout candidates use) to
   the Claude adjudicator in :mod:`src.match_headout` for apple-to-apple check.
4. Insert one ``competitors`` row per Rayna product with
   ``seller_domain='globaltix.com'``, one ``competitor_listings`` per matched
   GlobalTix product, and one ``options`` row using the product-level
   ``fromPrice`` (customer-facing starting price) as the representative
   competitor price.

Note on prices: GlobalTix's variant endpoint (``/api/product/options``)
doesn't return prices, and their availability endpoint returns wholesale
``nettPrice`` which isn't the price a customer would actually pay. Product-
level ``fromPrice`` is the honest "starting from" retail figure and is what
we compare against Rayna's variant prices. If we later want per-variant
pricing we can layer :func:`globaltix_client.check_availability` on top.

Usage
-----

    python -m src.ingest_globaltix_competitors --country "United Arab Emirates"
    python -m src.ingest_globaltix_competitors --country "United Arab Emirates" --pilot
    python -m src.ingest_globaltix_competitors --all-countries

"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from src import config, db, globaltix_client, match_headout

GLOBALTIX_SELLER_DOMAIN = "globaltix.com"
GLOBALTIX_SELLER_NAME = "GlobalTix"

FUZZY_SHORTLIST = 15
FUZZY_MIN_SCORE = 0.20


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _score(rayna_name: str, other_name: str) -> float:
    a, b = _norm(rayna_name), _norm(other_name)
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    a_toks = set(a.split())
    b_toks = set(b.split())
    overlap = len(a_toks & b_toks) / max(len(a_toks), 1)
    return ratio + overlap


def _shortlist(
    rayna_name: str, products: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    scored = [(_score(rayna_name, p.get("name") or ""), p) for p in products]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for s, p in scored[:FUZZY_SHORTLIST] if s >= FUZZY_MIN_SCORE]


def _adapt_for_adjudicator(p: dict[str, Any]) -> dict[str, Any]:
    """Reshape a GlobalTix product into the Headout-like schema the
    :mod:`src.match_headout` adjudicator expects (name / primaryCategory /
    content.shortSummary / id).
    """
    keywords = p.get("keywords") or ""
    merchant_name = (p.get("merchant") or {}).get("name") or ""
    summary_bits = [
        f"City: {p.get('city') or ''}",
        f"Merchant: {merchant_name}" if merchant_name else "",
        f"Keywords: {keywords}" if keywords else "",
    ]
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "primaryCategory": {"name": p.get("category") or ""},
        "primarySubCategory": None,
        "content": {"shortSummary": " · ".join(x for x in summary_bits if x)},
        "canonicalUrl": p.get("canonicalUrl") or "",
    }


def _delete_existing_globaltix(conn, rayna_product_ids: list[int]) -> tuple[int, int]:
    if not rayna_product_ids:
        return (0, 0)
    ph = ",".join("?" * len(rayna_product_ids))
    comp_ids = [
        r["id"]
        for r in conn.execute(
            f"SELECT id FROM competitors WHERE seller_domain=? "
            f"AND rayna_product_id IN ({ph})",
            [GLOBALTIX_SELLER_DOMAIN, *rayna_product_ids],
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
        conn.execute(
            f"DELETE FROM mappings WHERE competitor_option_id IN "
            f"(SELECT id FROM options WHERE source='competitor' "
            f"AND competitor_listing_id IN ({lph}))",
            listing_ids,
        )
        conn.execute(
            f"DELETE FROM price_observations WHERE option_id IN "
            f"(SELECT id FROM options WHERE source='competitor' "
            f"AND competitor_listing_id IN ({lph}))",
            listing_ids,
        )
        cur = conn.execute(
            f"DELETE FROM options WHERE source='competitor' "
            f"AND competitor_listing_id IN ({lph})",
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
                   'real_seller', 1.0, 'GlobalTix Partner API (verified)',
                   1, ?, ?)""",
        (
            rayna_product_id,
            market,
            GLOBALTIX_SELLER_DOMAIN,
            GLOBALTIX_SELLER_NAME,
            top_url,
            "Real seller — GlobalTix Partner API",
            1,
            "",
            now,
            now,
        ),
    )
    row = conn.execute(
        "SELECT id FROM competitors WHERE rayna_product_id=? AND market=? AND seller_domain=?",
        (rayna_product_id, market, GLOBALTIX_SELLER_DOMAIN),
    ).fetchone()
    return int(row["id"])


def _canonical_url(product: dict[str, Any]) -> str:
    """Best-effort customer-facing URL for a GlobalTix product.

    The API doesn't include a canonicalUrl, and GlobalTix is a B2B platform
    (resellers publish to their own storefronts). We synthesise a link to
    the staging partner portal so the user has something to click.
    """
    pid = product.get("id")
    return f"https://stg-partner.globaltix.com/#/products/{pid}" if pid else ""


def _price_from_product(p: dict[str, Any]) -> tuple[float | None, str | None]:
    price = p.get("fromPrice") or p.get("originalPrice")
    if price is None:
        return (None, None)
    try:
        price = float(price)
    except (TypeError, ValueError):
        return (None, None)
    if price <= 0:
        return (None, p.get("currency"))
    return (price, p.get("currency") or "USD")


def ingest_country(
    country_name: str,
    only_rayna_ids: list[int] | None = None,
    only_city: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    country_code_override: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    db.init_db()
    conn = db.get_conn()

    # Resolve country code from GlobalTix's own catalog (by name)
    if country_code_override:
        cc = country_code_override
    else:
        countries = globaltix_client.list_countries()
        cc_by_name = {(c.get("name") or "").lower(): c.get("code") for c in countries}
        cc = cc_by_name.get(country_name.lower())
        if not cc:
            conn.close()
            raise RuntimeError(
                f"GlobalTix does not list country {country_name!r}. "
                f"Available names include: {sorted(cc_by_name.keys())[:10]}…"
            )

    q = "SELECT id, name, type, city, country, market, raw_json FROM products WHERE country=?"
    args: list[Any] = [country_name]
    if only_rayna_ids:
        ph = ",".join("?" * len(only_rayna_ids))
        q += f" AND id IN ({ph})"
        args.extend(only_rayna_ids)
    if only_city:
        q += " AND city = ?"
        args.append(only_city)
    q += " ORDER BY id"
    if limit:
        q += f" LIMIT {int(limit)}"
    rayna_products = [dict(r) for r in conn.execute(q, args)]
    if not rayna_products:
        conn.close()
        print(f"No Rayna products for country={country_name!r}.")
        return {"rayna_products_considered": 0}

    print(f"Fetching GlobalTix catalog for {country_name} ({cc}) …")
    gt_products = globaltix_client.list_products(cc)
    print(f"  GlobalTix returned {len(gt_products)} products.")
    if not gt_products:
        conn.close()
        return {"rayna_products_considered": len(rayna_products), "gt_products": 0}

    n_matched = 0
    n_shortlisted = 0
    n_yes = 0
    n_no = 0
    n_listings = 0
    n_options_priced = 0
    n_options_unpriced = 0
    unmatched: list[dict[str, Any]] = []

    if not dry_run:
        del_l, del_o = _delete_existing_globaltix(conn, [p["id"] for p in rayna_products])
        if del_l or del_o:
            print(f"  cleared {del_l} old GlobalTix listings / {del_o} options")

    for rp in rayna_products:
        shortlist = _shortlist(rp["name"], gt_products)
        if not shortlist:
            unmatched.append({"id": rp["id"], "name": rp["name"], "reason": "no fuzzy shortlist"})
            continue
        n_shortlisted += len(shortlist)

        # shape-shift into the schema the adjudicator was written for
        adapted = [_adapt_for_adjudicator(p) for p in shortlist]
        verdicts = match_headout.adjudicate_batch(rp, adapted)
        by_id = {v["headout_id"]: v for v in verdicts}
        kept: list[dict[str, Any]] = []
        for p in shortlist:
            v = by_id.get(str(p.get("id"))) or {}
            if v.get("same_product"):
                kept.append(p)
                n_yes += 1
            else:
                n_no += 1

        if not kept:
            unmatched.append({
                "id": rp["id"], "name": rp["name"],
                "reason": "no apple-to-apple match after Claude",
            })
            continue

        n_matched += 1
        top_url = _canonical_url(kept[0])

        if dry_run:
            print(f"[dry] #{rp['id']} {rp['name']!r}:")
            for p in kept:
                v = by_id.get(str(p.get("id"))) or {}
                price, cur = _price_from_product(p)
                price_s = f"{cur} {price:.2f}" if price is not None else "no price"
                print(
                    f"    ✓ conf={v.get('confidence', 0):.2f}  #{p.get('id')}  "
                    f"{price_s:<14}  {(p.get('name') or '')[:60]}"
                )
            continue

        try:
            with conn:
                comp_id = _upsert_competitor(
                    conn, rp["id"], rp["market"] or "UAE", top_url, now
                )
                for p in kept:
                    listing_url = _canonical_url(p)
                    price, cur = _price_from_product(p)

                    # Also pull the per-option detail from GlobalTix so the
                    # enricher has richer text (inclusions/exclusions/duration
                    # often live at option level, not product level). We store
                    # the options array alongside the product in raw_markdown.
                    try:
                        gt_options = globaltix_client.list_options(p.get("id"))
                    except Exception as ex:  # noqa: BLE001
                        print(
                            f"    ! list_options failed for gt#{p.get('id')}: {ex}"
                        )
                        gt_options = []

                    raw_bundle = json.dumps(
                        {"product": p, "options": gt_options},
                        ensure_ascii=False,
                    )
                    cur_l = conn.execute(
                        """INSERT INTO competitor_listings
                           (competitor_id, listing_url, title,
                            raw_markdown, raw_html, scraped_at, scrape_method)
                           VALUES (?, ?, ?, ?, NULL, ?, 'globaltix_api')""",
                        (comp_id, listing_url, p.get("name") or "", raw_bundle, now),
                    )
                    listing_id = cur_l.lastrowid
                    n_listings += 1

                    fp = {
                        "vendor": "globaltix",
                        "gt_product_id": p.get("id"),
                        "category": p.get("category"),
                        "merchant": (p.get("merchant") or {}).get("name"),
                        "city": p.get("city"),
                        "pricing_basis": "per_adult",
                    }
                    raw_option_ref = json.dumps(
                        {"product": p, "options": gt_options},
                        ensure_ascii=False,
                    )
                    conn.execute(
                        """INSERT INTO options
                           (source, competitor_listing_id, name, pricing_basis,
                            price, currency, market, fingerprint_json,
                            raw_extracted_json, extraction_model, extracted_at)
                           VALUES ('competitor', ?, ?, 'per_adult', ?, ?, ?, ?,
                                   ?, 'globaltix-api', ?)""",
                        (
                            listing_id,
                            p.get("name") or "GlobalTix product",
                            price,
                            cur,
                            rp["market"] or "UAE",
                            json.dumps(fp, ensure_ascii=False),
                            raw_option_ref,
                            now,
                        ),
                    )
                    if price is None:
                        n_options_unpriced += 1
                    else:
                        n_options_priced += 1
        except Exception as e:
            print(f"  ! failed on Rayna #{rp['id']} {rp['name']!r}: {e}")

    conn.close()

    print()
    print(f"Rayna products considered: {len(rayna_products)}")
    print(f"  fuzzy shortlisted total: {n_shortlisted}")
    print(f"  Claude YES:              {n_yes}")
    print(f"  Claude NO:               {n_no}")
    print(f"  matched to GlobalTix:    {n_matched}")
    print(f"  unmatched:               {len(unmatched)}")
    print(f"Listings created:          {n_listings}")
    print(f"Options priced:            {n_options_priced}")
    print(f"Options unpriced:          {n_options_unpriced}")
    return {
        "country": country_name,
        "gt_country_code": cc,
        "rayna_products_considered": len(rayna_products),
        "matched": n_matched,
        "unmatched": len(unmatched),
        "listings_created": n_listings,
        "options_priced": n_options_priced,
        "options_unpriced": n_options_unpriced,
    }


def ingest_all_countries(limit_per_country: int | None = None) -> list[dict[str, Any]]:
    conn = db.get_conn()
    try:
        rayna_countries = [
            r["country"]
            for r in conn.execute(
                "SELECT country, COUNT(*) c FROM products "
                "WHERE country IS NOT NULL GROUP BY country ORDER BY c DESC"
            )
        ]
    finally:
        conn.close()

    countries = globaltix_client.list_countries()
    cc_by_name = {(c.get("name") or "").lower(): c.get("code") for c in countries}

    targets: list[tuple[str, str]] = []
    for name in rayna_countries:
        cc = cc_by_name.get(name.lower())
        if cc:
            targets.append((name, cc))

    print(f"=== Running GlobalTix ingest for {len(targets)} countries ===")
    for name, cc in targets:
        print(f"  · {name:35} → {cc}")

    results: list[dict[str, Any]] = []
    for i, (name, cc) in enumerate(targets, 1):
        print(f"\n{'#' * 60}\n# [{i}/{len(targets)}] {name}\n{'#' * 60}")
        try:
            r = ingest_country(
                country_name=name,
                limit=limit_per_country,
                country_code_override=cc,
            )
            results.append(r)
        except Exception as e:
            print(f"  ! country {name!r} failed: {e}")
            results.append({"country": name, "error": str(e)})

    print("\n=== Cross-country summary ===")
    print(f"{'country':35} {'rayna':>6} {'matched':>8} {'listings':>8}")
    for r in results:
        if "error" in r:
            print(f"{r['country']:35} ERROR: {r['error'][:40]}")
        else:
            print(
                f"{r['country']:35} "
                f"{r['rayna_products_considered']:>6} "
                f"{r['matched']:>8} "
                f"{r['listings_created']:>8}"
            )
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--country", help="Rayna country name (e.g. 'United Arab Emirates')")
    p.add_argument("--all-countries", action="store_true")
    p.add_argument("--pilot", action="store_true")
    p.add_argument("--rayna-product-id", type=int, action="append", default=[],
                   help="Restrict to these Rayna product IDs. Repeatable.")
    p.add_argument("--city", default=None,
                   help="Restrict by Rayna product city (e.g. 'Dubai').")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.all_countries:
        ingest_all_countries(limit_per_country=args.limit)
    else:
        if not args.country:
            p.error("either --country or --all-countries is required")
        if args.rayna_product_id:
            only = args.rayna_product_id
        elif args.pilot:
            only = config.PILOT_PRODUCT_IDS
        else:
            only = None
        ingest_country(
            country_name=args.country,
            only_rayna_ids=only,
            only_city=args.city,
            limit=args.limit,
            dry_run=args.dry_run,
        )
