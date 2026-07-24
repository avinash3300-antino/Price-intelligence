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
# Headout Partner API — used as a real live competitor source. Sandbox is fine
# for the demo; production key would need swapping the base URL below too.
HEADOUT_API_KEY = os.environ.get("HEADOUT_API_KEY", "")
HEADOUT_BASE = "https://www.sandbox-headout.com"

# GlobalTix Partner API 3.0 — second live competitor source.
# Auth is per-request Bearer JWT (24hr) obtained via POST /api/auth/authorize
# with headers x-api-key=<agent>/<key> and x-api-agent=<agent>.
GLOBALTIX_BASE = "https://stg-api.globaltix.com"
GLOBALTIX_AGENT = os.environ.get("GLOBALTIX_AGENT", "")
GLOBALTIX_API_KEY = os.environ.get("GLOBALTIX_API_KEY", "")
GLOBALTIX_USERNAME = os.environ.get("GLOBALTIX_USERNAME", "")

DATA_DIR = ROOT / "data"
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

# How many days ahead we pre-cache per-date prices for the date-picker feature
# (used by src.refresh_headout_date_prices and src.refresh_rayna_date_prices).
DATE_LOOKAHEAD_DAYS = 60

PILOT_PRODUCT_IDS = [18, 33, 36, 39, 47]

# Maps Rayna's free-text city name → Headout's cityCode. Only include entries
# we've verified return products from Headout's sandbox. Missing entries will
# just skip Headout ingest for that city.
HEADOUT_CITY_CODES: dict[str, str] = {
    "Dubai": "DUBAI",
    "Abu Dhabi": "ABU_DHABI",
    "Bangkok": "BANGKOK",
    "Phuket": "PHUKET",
    "Pattaya": "PATTAYA",
    "Singapore": "SINGAPORE",
    "Kuala Lumpur": "KUALA_LUMPUR",
    "Langkawi": "LANGKAWI",
    "Bali": "BALI",
    "Ho Chi Minh City": "HO_CHI_MINH_CITY",
    "Hanoi": "HANOI",
    "Tokyo": "TOKYO",
    "Osaka": "OSAKA",
    "Kyoto": "KYOTO",
    "Seoul": "SEOUL",
    "Hong Kong": "HONG_KONG",
    "Cairo": "CAIRO",
    "Istanbul": "ISTANBUL",
    "London": "LONDON",
    "Paris": "PARIS",
    "Rome": "ROME",
    "Barcelona": "BARCELONA",
    "New York": "NEW_YORK",
    "Orlando": "ORLANDO",
    "Los Angeles": "LOS_ANGELES",
    "Sydney": "SYDNEY",
    "Melbourne": "MELBOURNE",
    "Auckland": "AUCKLAND",
    "Queenstown": "QUEENSTOWN",
    "Mauritius": "MAURITIUS",
}
