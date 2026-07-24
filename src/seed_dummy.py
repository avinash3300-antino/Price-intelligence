"""Historical: this script used to seed *dummy* competitors + competitor
options for products without real data.

It is now a **no-op**. Rayna options come from the Vercel feed via
``src.sync_options_from_feed``; competitors come only from the Headout
Partner API via ``src.ingest_headout_competitors`` (apple-to-apple matched
with Claude adjudication). No dummy competitor data is permitted anywhere in
the pipeline — running this script will refuse to write.

Kept in-tree only so `python -m src.seed_dummy` from old runbooks still exits
cleanly instead of ImportError'ing.
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timezone
from typing import Any

from src import db


# Real OTA / aggregator domains by product type. Picked because they actually
# do sell in these categories — keeps the demo believable.
OTAS_BY_TYPE: dict[str, list[str]] = {
    "activities": [
        "getyourguide.com",
        "viator.com",
        "klook.com",
        "headout.com",
        "tiqets.com",
        "civitatis.com",
        "musement.com",
    ],
    "holiday": [
        "booking.com",
        "expedia.com",
        "agoda.com",
        "hotels.com",
        "trip.com",
    ],
    "cruise": [
        "cruisecritic.com",
        "viator.com",
        "tripadvisor.com",
        "expedia.com",
    ],
    "visa": [
        "ivisa.com",
        "visacentral.com",
        "vfsglobal.com",
    ],
    "yacht": [
        "clickandboat.com",
        "viator.com",
        "getyourguide.com",
        "boatbookings.com",
    ],
    "combo": [
        "getyourguide.com",
        "viator.com",
        "klook.com",
        "headout.com",
    ],
}

# (label, price_multiplier, basis, transfer_included)
OPTION_TEMPLATES: dict[str, list[tuple[str, float, str, bool]]] = {
    "activities": [
        ("Standard", 1.00, "per_adult", False),
        ("With shared transfer", 1.30, "per_adult", True),
        ("Premium / VIP", 2.10, "per_adult", True),
    ],
    "holiday": [
        ("Standard package", 1.00, "private_group", False),
        ("Deluxe package", 1.45, "private_group", False),
    ],
    "cruise": [
        ("Standard cabin", 1.00, "per_adult", False),
        ("Suite", 1.65, "per_adult", False),
    ],
    "visa": [
        ("Standard processing", 1.00, "per_adult", False),
        ("Express processing", 1.55, "per_adult", False),
    ],
    "yacht": [
        ("Half-day charter", 1.00, "per_yacht", False),
        ("Full-day charter", 1.75, "per_yacht", False),
    ],
    "combo": [
        ("Standard combo", 1.00, "per_adult", False),
        ("Premium combo", 1.40, "per_adult", True),
    ],
}


def _rng(seed_str: str) -> random.Random:
    h = hashlib.sha1(seed_str.encode()).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


def _has_existing_options(conn, product_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM options WHERE rayna_product_id=? LIMIT 1",
        (product_id,),
    ).fetchone()
    return row is not None


def _has_existing_competitors(conn, product_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM competitors WHERE rayna_product_id=? LIMIT 1",
        (product_id,),
    ).fetchone()
    return row is not None


def seed() -> dict[str, int]:
    print(
        "seed_dummy: NO-OP. Dummy competitor seeding is disabled. Use "
        "`python -m src.ingest_headout_competitors --all-cities` instead."
    )
    return {
        "products_seeded": 0,
        "products_skipped_real": 0,
        "competitors_inserted": 0,
        "listings_inserted": 0,
        "competitor_options_inserted": 0,
    }


def _legacy_seed_disabled() -> dict[str, int]:
    """Old implementation, kept for reference. Never called from anywhere."""
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_conn()
    products = list(conn.execute("SELECT * FROM products ORDER BY id"))

    seeded_products = 0
    skipped_real = 0
    n_competitors = 0
    n_listings = 0
    n_comp_opts = 0

    for p in products:
        if _has_existing_competitors(conn, p["id"]):
            # Real (or previously-seeded) competitors exist — don't touch.
            skipped_real += 1
            continue

        raw = json.loads(p["raw_json"]) if p["raw_json"] else {}
        ptype = (p["type"] or "activities").lower()
        base_price = (
            raw.get("price_totalPrice")
            or raw.get("normalPrice")
            or raw.get("list_price")
            or 200.0
        )
        try:
            base_price = float(base_price)
        except (TypeError, ValueError):
            base_price = 200.0
        currency = raw.get("currency") or p["currency"] or "AED"
        market = p["market"] or "UAE"

        rng = _rng(f"prod-{p['id']}")
        # Templates are still used to drive the per-seller variant generation
        # below, but no Rayna-side rows are written from this script anymore.
        templates = OPTION_TEMPLATES.get(ptype, OPTION_TEMPLATES["activities"])
        n_opts = rng.choice([1, 2, 2, 3])
        selected_opts = templates[:n_opts]

        with db.tx() as tx:
            otas = OTAS_BY_TYPE.get(ptype, OTAS_BY_TYPE["activities"])
            n_comp = rng.choice([3, 4, 4, 5])
            chosen = rng.sample(otas, min(n_comp, len(otas)))

            for rank, domain in enumerate(chosen, 1):
                seller_name = domain.split(".")[0].replace("-", " ").title()
                slug = (p["name"] or "").lower().replace(" ", "-")[:60]
                listing_url = f"https://www.{domain}/listing/{p['id']}-{slug}"

                tx.execute(
                    """INSERT OR IGNORE INTO competitors
                       (rayna_product_id, market, seller_domain, seller_name,
                        seed_url, snippet, search_rank, search_query,
                        classified_as, classifier_confidence, classifier_reason,
                        sells_this_product, classified_at, discovered_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                               'real_seller', 0.95, 'DUMMY classification',
                               1, ?, ?)""",
                    (
                        p["id"],
                        market,
                        domain,
                        seller_name,
                        listing_url,
                        "DUMMY snippet",
                        rank,
                        (p["name"] or "")[:80],
                        now,
                        now,
                    ),
                )
                comp_id = tx.execute(
                    "SELECT id FROM competitors WHERE rayna_product_id=? AND seller_domain=?",
                    (p["id"], domain),
                ).fetchone()[0]
                n_competitors += 1

                tx.execute(
                    """INSERT INTO competitor_listings
                       (competitor_id, listing_url, title, raw_markdown, raw_html,
                        scraped_at, scrape_method)
                       VALUES (?, ?, ?, '(dummy markdown)', NULL, ?, 'dummy')""",
                    (
                        comp_id,
                        listing_url,
                        f"{p['name']} – {seller_name}",
                        now,
                    ),
                )
                listing_id = tx.execute("SELECT last_insert_rowid()").fetchone()[0]
                n_listings += 1

                n_their_opts = rng.choice([1, 1, 2])
                for opt_idx in range(n_their_opts):
                    tier_name, mult, basis, transfer = rng.choice(selected_opts)
                    drift = rng.uniform(0.82, 1.25)
                    comp_price = round(base_price * mult * drift, 2)
                    fp = {
                        "venue": None,
                        "activity_category": ptype,
                        "tier": tier_name.lower().replace(" ", "_").replace("/", "_"),
                        "pricing_basis": basis,
                        "transfer_included": transfer,
                        "notes": "DUMMY — demo placeholder, not real",
                    }
                    tx.execute(
                        """INSERT INTO options
                           (source, competitor_listing_id, name, pricing_basis,
                            price, currency, market, fingerprint_json,
                            raw_extracted_json, extraction_model, extracted_at)
                           VALUES ('competitor', ?, ?, ?, ?, ?, ?, ?, '(dummy)', 'dummy', ?)""",
                        (
                            listing_id,
                            f"{tier_name} · {seller_name}",
                            basis,
                            comp_price,
                            currency,
                            market,
                            json.dumps(fp, ensure_ascii=False),
                            now,
                        ),
                    )
                    n_comp_opts += 1

        seeded_products += 1
        if seeded_products % 200 == 0:
            print(f"  seeded {seeded_products} products…")

    conn.close()
    return {
        "products_seeded": seeded_products,
        "products_skipped_real": skipped_real,
        "competitors_inserted": n_competitors,
        "listings_inserted": n_listings,
        "competitor_options_inserted": n_comp_opts,
    }


if __name__ == "__main__":
    print("Seeding dummy competitors for products without real competitor data…")
    result = seed()
    for k, v in result.items():
        print(f"  {k:<30} {v}")
