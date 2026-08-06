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

# legacy options have AUTOINCREMENT IDs starting at 1. Any id below this is
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
        conn.execute("BEGIN")

        # ------------------------------------------------------------------
        # 1. Find legacy Rayna options that still need migrating
        # ------------------------------------------------------------------
        legacy_rows = [
            dict(r)
            for r in conn.execute(
                "SELECT id, rayna_product_id, name, pricing_basis, extraction_model "
                "FROM options WHERE source='rayna' AND id < ?",
                (SYNTHETIC_ID_OFFSET,),
            )
        ]
        migration, unmapped = _build_migration_map(legacy_rows, by_product)

        legacy_ids_referenced = {
            r["rayna_option_id"]
            for r in conn.execute(
                "SELECT DISTINCT rayna_option_id FROM mappings WHERE rayna_option_id < ?",
                (SYNTHETIC_ID_OFFSET,),
            )
        }

        # ------------------------------------------------------------------
        # 2. Upsert all variants as `options` rows. INSERT OR REPLACE keeps
        #    re-runs idempotent and refreshes prices/names.
        # ------------------------------------------------------------------
        upserts = 0
        for v in variants:
            conn.execute(
                """
                INSERT OR REPLACE INTO options
                  (id, source, rayna_product_id, competitor_listing_id,
                   name, pricing_basis, price, currency, market,
                   fingerprint_json, raw_extracted_json,
                   extraction_model, extracted_at)
                VALUES (?, 'rayna', ?, NULL, ?, ?, ?, ?, ?, ?, '(vercel-feed)', 'vercel-feed', ?)
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
                    "DELETE FROM mappings WHERE rayna_option_id = ?",
                    (old_id,),
                )
                mappings_dropped += cur.rowcount or 0
                continue
            try:
                cur = conn.execute(
                    "UPDATE mappings SET rayna_option_id = ? WHERE rayna_option_id = ?",
                    (new_id, old_id),
                )
                mappings_repointed += cur.rowcount or 0
            except Exception:
                # UNIQUE(rayna_option_id, competitor_option_id) — two old
                # rows collapsed to the same new variant for the same
                # competitor. Drop the dupe.
                cur = conn.execute(
                    "DELETE FROM mappings WHERE rayna_option_id = ?",
                    (old_id,),
                )
                unique_skipped += cur.rowcount or 0

        # ------------------------------------------------------------------
        # 4. Delete legacy Rayna option rows (now unreferenced).
        # ------------------------------------------------------------------
        cur = conn.execute(
            "DELETE FROM options WHERE source='rayna' AND id < ?",
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
                "SELECT id FROM options WHERE source='rayna' AND id >= ?",
                (SYNTHETIC_ID_OFFSET,),
            )
        }
        stale = list(all_synth_ids - valid_ids)
        orphan_unmapped = 0
        if stale:
            # only drop if no mapping references them, to be safe
            placeholders = ",".join("?" * len(stale))
            ref = {
                r["rayna_option_id"]
                for r in conn.execute(
                    f"SELECT DISTINCT rayna_option_id FROM mappings "
                    f"WHERE rayna_option_id IN ({placeholders})",
                    stale,
                )
            }
            drop = [i for i in stale if i not in ref]
            if drop:
                placeholders = ",".join("?" * len(drop))
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
    }
    return summary


if __name__ == "__main__":
    s = sync()
    print("sync_options_from_feed: done")
    for k, v in s.items():
        print(f"  {k:<40} {v}")
