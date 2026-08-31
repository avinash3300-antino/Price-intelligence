"""Project configuration. Secrets are read from .env and never logged."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SEARCHAPI_KEY = os.environ["SEARCHAPI_KEY"]
FIRECRAWL_KEY = os.environ["FIRECRAWL_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

DATA_DIR = ROOT / "data"

# Postgres connection string. Overridden per environment via .env; the default
# targets the local PostgreSQL 18 instance used for development.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://localhost:5433/market_intel"
)

# Legacy SQLite path. The application no longer reads this — it is kept so the
# migration script and the pre-cutover backups can still find the old file.
DB_PATH = DATA_DIR / "market_intel.db"
CATALOG_PATH = DATA_DIR / "rayna_catalog_sample.json"
CATALOG_LIVE_PATH = DATA_DIR / "rayna_catalog_live.json"
LOGS_DIR = ROOT / "logs"

RAYNA_API_BASE = "https://data-projects-flax.vercel.app"
RAYNA_ENRICHED_FEED = "/api/enriched-feed?format=json"

CLAUDE_ADJUDICATOR_MODEL = "claude-sonnet-4-6"
CLAUDE_CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"

PILOT_MARKET = "UAE"
PILOT_CURRENCY = "AED"

# How many days ahead we pre-cache per-date prices for the date-picker
# feature (used by src.refresh_rayna_date_prices).
DATE_LOOKAHEAD_DAYS = 60

PILOT_PRODUCT_IDS = [18, 33, 36, 39, 47]
