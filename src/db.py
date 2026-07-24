"""SQLite schema + connection helpers. SQL is written portable to Postgres."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from src import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT,
    city TEXT,
    country TEXT,
    market TEXT NOT NULL,
    currency TEXT NOT NULL,
    url TEXT,
    raw_json TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    rayna_product_id INTEGER,
    competitor_listing_id INTEGER,
    name TEXT NOT NULL,
    pricing_basis TEXT,
    price REAL,
    currency TEXT,
    market TEXT NOT NULL,
    fingerprint_json TEXT,
    raw_extracted_json TEXT,
    extraction_model TEXT,
    extracted_at TEXT,
    FOREIGN KEY (rayna_product_id) REFERENCES products(id),
    FOREIGN KEY (competitor_listing_id) REFERENCES competitor_listings(id)
);

CREATE INDEX IF NOT EXISTS idx_options_source ON options(source);
CREATE INDEX IF NOT EXISTS idx_options_rayna_product ON options(rayna_product_id);
CREATE INDEX IF NOT EXISTS idx_options_competitor_listing ON options(competitor_listing_id);

CREATE TABLE IF NOT EXISTS competitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rayna_product_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    seller_domain TEXT NOT NULL,
    seller_name TEXT,
    seed_url TEXT,
    snippet TEXT,
    search_rank INTEGER,
    search_query TEXT,
    classified_as TEXT,
    classifier_confidence REAL,
    classifier_reason TEXT,
    sells_this_product INTEGER,
    classified_at TEXT,
    discovered_at TEXT NOT NULL,
    UNIQUE(rayna_product_id, market, seller_domain),
    FOREIGN KEY (rayna_product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS competitor_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id INTEGER NOT NULL,
    listing_url TEXT NOT NULL,
    title TEXT,
    raw_markdown TEXT,
    raw_html TEXT,
    scraped_at TEXT NOT NULL,
    scrape_method TEXT,
    FOREIGN KEY (competitor_id) REFERENCES competitors(id)
);

CREATE INDEX IF NOT EXISTS idx_listings_competitor ON competitor_listings(competitor_id);

CREATE TABLE IF NOT EXISTS mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rayna_option_id INTEGER NOT NULL,
    competitor_option_id INTEGER NOT NULL,
    verdict TEXT NOT NULL,
    confidence REAL NOT NULL,
    diff_notes TEXT,
    judge_model TEXT,
    human_reviewed INTEGER DEFAULT 0,
    human_verdict TEXT,
    is_manual INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(rayna_option_id, competitor_option_id),
    FOREIGN KEY (rayna_option_id) REFERENCES options(id),
    FOREIGN KEY (competitor_option_id) REFERENCES options(id)
);

CREATE TABLE IF NOT EXISTS price_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    option_id INTEGER NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    market TEXT NOT NULL,
    target_date TEXT,
    captured_at TEXT NOT NULL,
    is_spike_flagged INTEGER DEFAULT 0,
    capture_method TEXT,
    FOREIGN KEY (option_id) REFERENCES options(id)
);

CREATE INDEX IF NOT EXISTS idx_price_obs_option ON price_observations(option_id);
"""


def get_conn() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def tx():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
