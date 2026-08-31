"""Sync Rayna options in SQLite from the Vercel feed cache.

Reads ``data/feed_cache.json`` (produced by ``src.feed_cache``) and writes
one row per bookable variant into the ``options`` table. Each variant gets a
deterministic synthetic ID derived from ``(product_id, group_id, transfer_option_id)``
so re-syncing leaves existing rows / mappings undisturbed.

Existing mappings that reference *legacy* option IDs (Claude-extracted or
dummy, i.e. anything below ``SYNTHETIC_ID_OFFSET``) are re-pointed to the
closest matching new variant by best-effort name match before the old rows
get deleted. Mappings without a plausible match are dropped (and reported).

Competitors and competitor_listings are not touched here — they keep their
existing rows (real for PoC products, dummy for the rest).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from src import config, db, feed_cache

# legacy options have sequence-assigned ids starting at 1. Any id below this is
# considered legacy and migratable. New variant IDs are >= this.
SYNTHETIC_ID_OFFSET = feed_cache.SYNTHETIC_ID_OFFSET


def _norm(s: str | None) -> str:
    """Lowercased, alpha-num-only — used as a stable fingerprint for name match."""
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _score_match(old_name: str, old_basis: str | None, variant: dict[str, Any]) -> int:
    """Higher is better. Used to choose the new variant most similar to an
    old Rayna option for the mapping migration.
    """
    old_n = _norm(old_name)
    new_n = _norm(variant["name"])

    score = 0
    # transfer-type tokens are the most informative signal
    for token, weight in [
        ("without transfers", 50),
        ("sharing transfers", 50),
        ("private transfers", 50),
        ("no transfer", 40),
        ("with transfer", 40),
        ("transfer", 10),
        ("sunrise", 30),
        ("morning treat", 30),
        ("125", 25),
        ("124", 15),
        ("aquarium", 25),
        ("fast track", 25),
        ("premium", 20),
        ("vip", 20),
        ("standard", 5),
    ]:
        if token in old_n and token in new_n:
            score += weight

    # token overlap as tiebreaker
    old_tokens = set(old_n.split())
    new_tokens = set(new_n.split())
    score += len(old_tokens & new_tokens)

    # basis agreement (per_adult vs private_group)
    if old_basis and variant.get("pricing_basis") == old_basis:
        score += 3

    return score


def _build_migration_map(
    legacy_rows: list[dict[str, Any]],
    candidates_by_product: dict[int, list[dict[str, Any]]],
) -> tuple[dict[int, int], list[dict[str, Any]]]:
    """Build {old_options.id → new synthetic_id} and a list of unmapped olds."""
    migration: dict[int, int] = {}
    unmapped: list[dict[str, Any]] = []

    for row in legacy_rows:
        pid = row["rayna_product_id"]
        candidates = candidates_by_product.get(pid, [])
        if not candidates:
            unmapped.append({"old_id": row["id"], "name": row["name"],
                             "product_id": pid, "reason": "no variants in feed"})
            continue

        best: dict[str, Any] | None = None
        best_score = -1
        for v in candidates:
            s = _score_match(row["name"], row.get("pricing_basis"), v)
            if s > best_score:
                best_score = s
                best = v

        if best is None or best_score < 1:
            unmapped.append({"old_id": row["id"], "name": row["name"],
                             "product_id": pid, "reason": "no plausible match"})
            continue

        migration[row["id"]] = best["synthetic_id"]

    return migration, unmapped


def sync() -> dict[str, Any]:
    """Run the full sync. Idempotent."""
    feed_cache.load_from_disk(force=True)
    variants = feed_cache.get_all_variants()
    if not variants:
        raise RuntimeError(
            "Feed cache is empty. Run `python -m src.feed_cache` first."
        )

    # bucket variants by product for the migration step
    by_product: dict[int, list[dict[str, Any]]] = {}
    for v in variants:
        by_product.setdefault(int(v["product_id"]), []).append(v)

    now = datetime.now(timezone.utc).isoformat()

    db.init_db()
    conn = db.get_conn()
    try:

        # ------------------------------------------------------------------
        # 1. Find legacy Rayna options that still need migrating
        # ------------------------------------------------------------------
        legacy_rows = [
            dict(r)
            for r in conn.execute(
                "SELECT id, rayna_product_id, name, pricing_basis, extraction_model "
                "FROM options WHERE source='rayna' AND id < %s",
                (SYNTHETIC_ID_OFFSET,),
            )
        ]
        migration, unmapped = _build_migration_map(legacy_rows, by_product)

        legacy_ids_referenced = {
            r["rayna_option_id"]
            for r in conn.execute(
                "SELECT DISTINCT rayna_option_id FROM mappings WHERE rayna_option_id < %s",
                (SYNTHETIC_ID_OFFSET,),
            )
        }

        # ------------------------------------------------------------------
        # 2. Upsert all variants as `options` rows. ON CONFLICT DO UPDATE
        #    keeps re-runs idempotent and refreshes prices/names.
        # ------------------------------------------------------------------
        upserts = 0
        for v in variants:
            conn.execute(
                """
                INSERT INTO options
                  (id, source, rayna_product_id, competitor_listing_id,
                   name, pricing_basis, price, currency, market,
                   fingerprint_json, raw_extracted_json,
                   extraction_model, extracted_at)
                VALUES (%s, 'rayna', %s, NULL, %s, %s, %s, %s, %s, %s, '(vercel-feed)', 'vercel-feed', %s)
                ON CONFLICT (id) DO UPDATE SET
                  source = EXCLUDED.source,
                  rayna_product_id = EXCLUDED.rayna_product_id,
                  name = EXCLUDED.name,
                  pricing_basis = EXCLUDED.pricing_basis,
                  price = EXCLUDED.price,
                  currency = EXCLUDED.currency,
                  market = EXCLUDED.market,
                  fingerprint_json = EXCLUDED.fingerprint_json,
                  extraction_model = EXCLUDED.extraction_model,
                  extracted_at = EXCLUDED.extracted_at
                """,
                (
                    v["synthetic_id"],
                    v["product_id"],
                    v["name"],
                    v["pricing_basis"],
                    v["price"],
                    v["currency"],
                    config.PILOT_MARKET,
                    json.dumps(v["fingerprint"], ensure_ascii=False),
                    now,
                ),
            )
            upserts += 1

        # ------------------------------------------------------------------
        # 3. Re-point mappings to new synthetic IDs (only those that have a
        #    plausible match). Drop the ones we can't map.
        # ------------------------------------------------------------------
        mappings_repointed = 0
        mappings_dropped = 0
        unique_skipped = 0

        for old_id in legacy_ids_referenced:
            new_id = migration.get(old_id)
            if new_id is None:
                cur = conn.execute(
                    "DELETE FROM mappings WHERE rayna_option_id = %s",
                    (old_id,),
                )
                mappings_dropped += cur.rowcount or 0
                continue
            try:
                cur = conn.execute(
                    "UPDATE mappings SET rayna_option_id = %s WHERE rayna_option_id = %s",
                    (new_id, old_id),
                )
                mappings_repointed += cur.rowcount or 0
            except Exception:
                # UNIQUE(rayna_option_id, competitor_option_id) — two old
                # rows collapsed to the same new variant for the same
                # competitor. Drop the dupe.
                cur = conn.execute(
                    "DELETE FROM mappings WHERE rayna_option_id = %s",
                    (old_id,),
                )
                unique_skipped += cur.rowcount or 0

        # ------------------------------------------------------------------
        # 4. Delete legacy Rayna option rows (now unreferenced).
        # ------------------------------------------------------------------
        cur = conn.execute(
            "DELETE FROM options WHERE source='rayna' AND id < %s",
            (SYNTHETIC_ID_OFFSET,),
        )
        legacy_deleted = cur.rowcount or 0

        # ------------------------------------------------------------------
        # 5. Sweep newly-orphaned variant rows: variants that exist in the
        #    options table from a prior sync but no longer in feed cache.
        # ------------------------------------------------------------------
        valid_ids = {v["synthetic_id"] for v in variants}
        all_synth_ids = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM options WHERE source='rayna' AND id >= %s",
                (SYNTHETIC_ID_OFFSET,),
            )
        }
        stale = list(all_synth_ids - valid_ids)
        orphan_unmapped = 0
        blackout_protected = 0
        blackout_products: set[int] = set()
        if stale:
            # only drop if no mapping references them, to be safe
            placeholders = ",".join(["%s"] * len(stale))
            ref = {
                r["rayna_option_id"]
                for r in conn.execute(
                    f"SELECT DISTINCT rayna_option_id FROM mappings "
                    f"WHERE rayna_option_id IN ({placeholders})",
                    stale,
                )
            }

            # --------------------------------------------------------------
            # Feed-blackout guard.
            #
            # "The feed returned no options for this product" and "this
            # product has no options" are not the same statement, but the
            # sweep below can't tell them apart on its own — both look like
            # a variant that vanished from the cache.
            #
            # This bit us for real: on 2026-08-06 the enriched-feed returned
            # 3 variants for product 33 (Dubai City Tour, option_ids
            # 41843/41844). By 2026-08-26 the same endpoint returned
            # `options: []` for it while /api/city/products still listed
            # those option ids as live. The nightly sync read the empty
            # array as truth and deleted all three, which silently greys the
            # product out in the mapping UI with no explanation.
            #
            # So: only sweep a variant when the feed still returned OTHER
            # variants for its product. That keeps genuine removals working
            # (feed returns 2 where we held 3 → the missing 1 is dropped)
            # while refusing to act on an all-or-nothing disappearance,
            # which is far more likely to be an upstream fault than a real
            # catalogue change.
            # --------------------------------------------------------------
            stale_product_of: dict[int, int] = {
                r["id"]: r["rayna_product_id"]
                for r in conn.execute(
                    f"SELECT id, rayna_product_id FROM options "
                    f"WHERE id IN ({placeholders})",
                    stale,
                )
            }

            def _feed_went_dark(option_id: int) -> bool:
                """True when the feed returned no variants at all for this
                option's product — i.e. we cannot trust the absence."""
                pid = stale_product_of.get(option_id)
                if pid is None:
                    return False
                return not by_product.get(pid)

            protected = [i for i in stale if _feed_went_dark(i)]
            for i in protected:
                pid = stale_product_of.get(i)
                if pid is not None:
                    blackout_products.add(pid)
            blackout_protected = len(protected)
            if protected:
                print(
                    f"  ! feed-blackout guard: kept {blackout_protected} option(s) "
                    f"across {len(blackout_products)} product(s) whose feed "
                    f"response carried zero options this run "
                    f"(product ids: {sorted(blackout_products)[:12]}"
                    f"{' …' if len(blackout_products) > 12 else ''})"
                )

            protected_set = set(protected)
            drop = [i for i in stale if i not in ref and i not in protected_set]
            if drop:
                placeholders = ",".join(["%s"] * len(drop))
                # price_observations also FK options.id — clear those first
                # so the options DELETE doesn't fail the constraint. The rows
                # are meaningless without the parent option anyway.
                conn.execute(
                    f"DELETE FROM price_observations WHERE option_id IN ({placeholders})",
                    drop,
                )
                conn.execute(
                    f"DELETE FROM options WHERE id IN ({placeholders})",
                    drop,
                )
                orphan_unmapped = len(drop)

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    summary = {
        "variants_in_feed": len(variants),
        "legacy_options_found": len(legacy_rows),
        "legacy_options_referenced_by_mappings": len(legacy_ids_referenced),
        "migration_map_size": len(migration),
        "unmapped_legacy_options": len(unmapped),
        "options_upserted": upserts,
        "mappings_repointed": mappings_repointed,
        "mappings_dropped_no_match": mappings_dropped,
        "mappings_dropped_unique_dupe": unique_skipped,
        "legacy_options_deleted": legacy_deleted,
        "stale_variants_dropped": orphan_unmapped,
        "stale_kept_feed_blackout": blackout_protected,
        "products_with_empty_feed_options": len(blackout_products),
    }
    return summary


if __name__ == "__main__":
    s = sync()
    print("sync_options_from_feed: done")
    for k, v in s.items():
        print(f"  {k:<40} {v}")
