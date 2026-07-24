"""One-shot: delete every competitor row that isn't ``headout.com``.

After the dummy wipe, some real Claude-pipeline data from the earlier PoC
(Firecrawl-scraped listings on getyourguide.com / viator.com / atthetop.ae
etc.) still lives in the DB. Avinash's rule is now:

    "all should be headout real data should show in competitor only"

so anything with ``seller_domain != 'headout.com'`` must go. Delete order
respects foreign keys the same way ``wipe_dummy_competitors`` does.

Idempotent — re-running does nothing after the first pass.
"""
from __future__ import annotations

from src import db


def wipe() -> dict[str, int]:
    conn = db.get_conn()
    try:
        conn.execute("BEGIN")

        # 1. mappings pointing at non-Headout competitor options
        cur = conn.execute(
            """
            DELETE FROM mappings
            WHERE competitor_option_id IN (
                SELECT o.id FROM options o
                JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
                JOIN competitors c ON c.id = cl.competitor_id
                WHERE o.source='competitor' AND c.seller_domain != 'headout.com'
            )
            """
        )
        n_mappings = cur.rowcount or 0

        # 2. competitor options for non-Headout sellers
        cur = conn.execute(
            """
            DELETE FROM options
            WHERE source='competitor' AND competitor_listing_id IN (
                SELECT cl.id FROM competitor_listings cl
                JOIN competitors c ON c.id = cl.competitor_id
                WHERE c.seller_domain != 'headout.com'
            )
            """
        )
        n_options = cur.rowcount or 0

        # 3. competitor listings for non-Headout sellers
        cur = conn.execute(
            """
            DELETE FROM competitor_listings
            WHERE competitor_id IN (
                SELECT id FROM competitors WHERE seller_domain != 'headout.com'
            )
            """
        )
        n_listings = cur.rowcount or 0

        # 4. the non-Headout competitor rows themselves
        cur = conn.execute(
            "DELETE FROM competitors WHERE seller_domain != 'headout.com'"
        )
        n_competitors = cur.rowcount or 0

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
    }
    return summary


if __name__ == "__main__":
    result = wipe()
    print("wipe_non_headout_competitors: done")
    for k, v in result.items():
        print(f"  {k:<32} {v}")
