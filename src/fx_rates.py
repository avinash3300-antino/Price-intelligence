"""FX rates cache — daily-refreshed conversion table with AED as the base.

Design (per Avinash / owner's instruction):
- Use ExchangeRate-API's open endpoint (no key, no signup). Request ~once/day
  and cache; caller-side we can call every request and the cache dedupes.
- AED is the base currency (Rayna's home market). Store rate per unit foreign
  currency → AED so `amount_in_aed = amount * rate_to_aed[currency]`.
- AED↔USD is a hard peg at 3.6725. Override whatever the API returns so we
  don't drift on USD, which covers most OTA defaults.
- Never let the LLM do conversion math — it's this module's job.

Cache path: ``data/fx_rates.json``. Format:
    {
      "fetched_at": "2026-08-07T...",
      "base": "AED",
      "rates_from_aed": { "USD": 0.2723, "SGD": 0.3506, ... },  # 1 AED = X foreign
      "rates_to_aed":   { "USD": 3.6725, "SGD": 2.852,  ... },  # 1 foreign = X AED
      "source": "open.er-api.com" | "cached" | "fallback",
      "raw": <original API payload>
    }
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from src import config

# https://www.exchangerate-api.com/docs/free — no key required, one call
# returns the base's rates against ~160 currencies. Their docs ask that we
# don't spam it, so we cache once per day.
OPEN_ENDPOINT = "https://open.er-api.com/v6/latest/AED"
FETCH_TIMEOUT_S = 15
DEFAULT_MAX_AGE_S = 24 * 60 * 60  # 24h — matches provider's refresh cadence

# UAE Central Bank pegs AED to USD at 3.6725 since 1997. We hardcode it so
# tiny inter-provider USD drift never leaks into the gap calculation.
USD_TO_AED = 3.6725

RATES_CACHE_PATH: Path = config.DATA_DIR / "fx_rates.json"


# ---------- disk cache ----------


def _read_cache() -> Optional[dict[str, Any]]:
    if not RATES_CACHE_PATH.exists():
        return None
    try:
        return json.loads(RATES_CACHE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(payload: dict[str, Any]) -> None:
    RATES_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RATES_CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def _is_fresh(payload: dict[str, Any], max_age_s: int) -> bool:
    ts = payload.get("fetched_at")
    if not ts:
        return False
    try:
        fetched = datetime.fromisoformat(ts)
    except ValueError:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - fetched).total_seconds()
    return age < max_age_s


# ---------- fetch ----------


def _fetch_live() -> dict[str, Any]:
    """Hit open.er-api.com and normalize into our cache shape."""
    r = httpx.get(OPEN_ENDPOINT, timeout=FETCH_TIMEOUT_S)
    r.raise_for_status()
    body = r.json()
    if body.get("result") != "success":
        raise RuntimeError(f"exchangerate-api returned non-success: {body!r}")
    # `rates` from the endpoint are: 1 AED = X foreign
    rates_from_aed: dict[str, float] = {
        k.upper(): float(v) for k, v in (body.get("rates") or {}).items()
    }
    # Invert to get: 1 foreign = X AED — what we actually multiply prices by.
    rates_to_aed: dict[str, float] = {}
    for cur, rate_from in rates_from_aed.items():
        if rate_from > 0:
            rates_to_aed[cur] = round(1.0 / rate_from, 6)

    # Hard-peg USD ↔ AED overrides whatever the API returned (the API's USD
    # rate drifts slightly and we don't want that noise in gap analysis).
    rates_to_aed["USD"] = USD_TO_AED
    rates_from_aed["USD"] = round(1.0 / USD_TO_AED, 6)
    rates_to_aed["AED"] = 1.0
    rates_from_aed["AED"] = 1.0

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "base": "AED",
        "rates_from_aed": rates_from_aed,
        "rates_to_aed": rates_to_aed,
        "source": "open.er-api.com",
        "raw_result": body.get("result"),
        "provider_last_update": body.get("time_last_update_utc"),
    }


# ---------- public API ----------


def get_rates(max_age_s: int = DEFAULT_MAX_AGE_S) -> dict[str, float]:
    """Return the `{CUR: rate_to_aed}` table, refreshing from the network if
    the cache is missing or older than ``max_age_s``.

    On network failure with an existing (stale) cache, keeps using the stale
    cache and logs — better a slightly-old rate than an error mid-conversion.
    """
    cached = _read_cache()
    if cached and _is_fresh(cached, max_age_s):
        return dict(cached["rates_to_aed"])

    try:
        fresh = _fetch_live()
        _write_cache(fresh)
        return dict(fresh["rates_to_aed"])
    except Exception as e:  # noqa: BLE001
        print(f"[fx_rates] live fetch failed: {type(e).__name__}: {e}")
        if cached and cached.get("rates_to_aed"):
            print("[fx_rates] using stale cache")
            return dict(cached["rates_to_aed"])
        # No cache and no network — return just the USD peg + AED so callers
        # can at least handle the common cases without crashing.
        return {"USD": USD_TO_AED, "AED": 1.0}


def to_aed(amount: Optional[float], currency: Optional[str]) -> Optional[float]:
    """Convert an amount to AED using today's cached rates.

    - None amount → None (no-op).
    - None/blank currency → assume AED (best guess for un-tagged rows).
    - USD → AED uses the hard peg (3.6725), no API involvement.
    - Unknown currency → None (surface the miss to the caller rather than
      silently returning the wrong value).
    """
    if amount is None:
        return None
    cur = (currency or "AED").strip().upper()
    if cur == "AED":
        return round(float(amount), 4)
    if cur == "USD":
        return round(float(amount) * USD_TO_AED, 4)
    rates = get_rates()
    rate = rates.get(cur)
    if rate is None:
        print(f"[fx_rates] no rate for {cur}; returning None")
        return None
    return round(float(amount) * rate, 4)


def _purge_sessions() -> None:
    """Housekeeping bolted onto the nightly run.

    Expired sessions are refused at resolve time, but rows for sessions nobody
    returns to would accumulate forever. This is the last step of the nightly
    chain, so it is the natural place to sweep.
    """
    try:
        from src import auth, db
        conn = db.get_conn()
        try:
            n = auth.purge_expired_sessions(conn)
            conn.commit()
            print(f"sessions: purged {n} expired")
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        # Never let housekeeping fail the refresh it is riding along with.
        print(f"sessions: purge skipped ({type(e).__name__}: {e})")


if __name__ == "__main__":
    # Manual refresh: `python -m src.fx_rates` forces a live pull.
    payload = _fetch_live()
    _write_cache(payload)
    _purge_sessions()
    print(
        f"fx_rates: refreshed {len(payload['rates_to_aed'])} currencies "
        f"from {payload['source']} at {payload['fetched_at']}"
    )
    for cur in ("USD", "EUR", "GBP", "SGD", "INR", "THB"):
        print(f"  1 {cur} = AED {payload['rates_to_aed'].get(cur, 'n/a')}")
