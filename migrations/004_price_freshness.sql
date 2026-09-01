-- Track when a competitor price was last checked, and whether the option is
-- still on the seller's page.
--
-- Until now a competitor price was written once, when someone pasted the URL,
-- and never touched again. /mapped compared a Rayna price refreshed that
-- morning against a competitor price up to twelve days old and presented the
-- difference as a live gap.
--
-- These columns let the nightly refresh answer three questions the page could
-- not: when did we last look, did the page change since, and is this option
-- still there.

BEGIN;

-- ------------------------------------------------------- competitor_listings
-- Hash of the fetched page content. When it matches the previous run the page
-- has not changed, so the Claude extraction is skipped — that is what makes a
-- nightly refresh affordable rather than a fixed nightly bill.
ALTER TABLE competitor_listings ADD COLUMN IF NOT EXISTS content_hash    TEXT;
ALTER TABLE competitor_listings ADD COLUMN IF NOT EXISTS last_checked_at TEXT;
-- Why the last check ended: 'unchanged' | 'updated' | 'blocked' | 'error'.
-- Kept so a seller that has quietly started blocking us is visible rather than
-- looking like a page that simply never changes.
ALTER TABLE competitor_listings ADD COLUMN IF NOT EXISTS last_check_status TEXT;

-- -------------------------------------------------------------------- options
ALTER TABLE options ADD COLUMN IF NOT EXISTS last_checked_at TEXT;
-- Last run in which this option was still found on the page. When it lags
-- behind last_checked_at the option has gone missing — delisted, renamed, or
-- the fetch degraded. The row and its mapping are kept either way; deleting a
-- human's mapping over one bad fetch is not a trade worth making.
ALTER TABLE options ADD COLUMN IF NOT EXISTS last_seen_at TEXT;
-- Price at the previous check, so a movement can be shown without joining the
-- observation history on every page load.
ALTER TABLE options ADD COLUMN IF NOT EXISTS previous_price DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_options_last_checked ON options (last_checked_at);

-- Existing rows were last (and only) checked when they were scraped.
UPDATE competitor_listings
   SET last_checked_at = scraped_at
 WHERE last_checked_at IS NULL;

UPDATE options o
   SET last_checked_at = cl.scraped_at,
       last_seen_at    = cl.scraped_at
  FROM competitor_listings cl
 WHERE cl.id = o.competitor_listing_id
   AND o.source = 'competitor'
   AND o.last_checked_at IS NULL;

COMMIT;
