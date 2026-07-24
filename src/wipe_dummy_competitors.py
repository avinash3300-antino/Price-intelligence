"""One-shot: delete every trace of *dummy* competitor data from SQLite.

Rows are identified by their marker fields (``extraction_model='dummy'``,
``scrape_method='dummy'``, ``classifier_reason LIKE '%DUMMY%'``). Real
Headout rows carry different markers (``'headout-api'`` / ``'headout_api'``
/ ``'Headout Partner API (verified)'``) and are left untouched.

Deletion order respects foreign keys with ``PRAGMA foreign_keys=ON``:

    1. mappings → competitor_option (options)
    2. options (source='competitor', extraction_model='dummy')
    3. competitor_listings (scrape_method='dummy')
    4. competitors (classifier_reason LIKE '%DUMMY%')
    5. sweep any now-orphaned listings / competitors

Idempotent — re-running does nothing after the first pass.
"""
from __future__ import annotations

from src import db


def wipe() -> dict[str, int]:
    conn = db.get_conn()
    try:
        conn.execute("BEGIN")

        cur = conn.execute(
            """
            DELETE FROM mappings
            WHERE competitor_option_id IN (
                SELECT id FROM options
                WHERE source='competitor' AND extraction_model='dummy'
            )
            """
        )
        n_mappings = cur.rowcount or 0

        cur = conn.execute(
            "DELETE FROM options WHERE source='competitor' AND extraction_model='dummy'"
        )
        n_options = cur.rowcount or 0

        cur = conn.execute(
            "DELETE FROM competitor_listings WHERE scrape_method='dummy'"
        )
        n_listings = cur.rowcount or 0

        cur = conn.execute(
            "DELETE FROM competitors WHERE classifier_reason LIKE '%DUMMY%'"
        )
        n_competitors = cur.rowcount or 0

        # sweep orphans: listings without a parent competitor, and competitors
        # with zero listings (may happen if a listing was removed earlier)
        cur = conn.execute(
            "DELETE FROM competitor_listings "
            "WHERE competitor_id NOT IN (SELECT id FROM competitors)"
        )
        n_orphan_listings = cur.rowcount or 0

        cur = conn.execute(
            "DELETE FROM competitors "
            "WHERE id NOT IN (SELECT DISTINCT competitor_id FROM competitor_listings)"
        )
        n_orphan_competitors = cur.rowcount or 0

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    summary = {
        "mappings_deleted": n_mappings,
        "competitor_options_deleted": n_options,
        "competitor_listings_deleted": n_listings,
        "competitors_deleted": n_competitors,
        "orphan_listings_swept": n_orphan_listings,
        "orphan_competitors_swept": n_orphan_competitors,
    }
    return summary


if __name__ == "__main__":
    result = wipe()
    print("wipe_dummy_competitors: done")
    for k, v in result.items():
        print(f"  {k:<32} {v}")
