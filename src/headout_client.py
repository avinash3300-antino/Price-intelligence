"""Thin Headout Partner API client.

Only the two calls we actually use:

    list_products(city_code) → paginate /api/public/v2/products/
    list_inventory_by_variant(variant_id, ...) → /api/v1/inventory/list-by/variant

Docs live at https://github.com/headout/api-docs — see the accompanying
project notes for gotchas (v1 vs v2, 50-item pagination, per-window inventory).
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from src import config

_TIMEOUT = 90  # Dubai catalog + some inventory calls exceed 30s intermittently
_RETRIES = 5
_RETRY_SLEEP = 2.0

_HEADERS = {
    "Headout-Auth": config.HEADOUT_API_KEY,
    "Accept": "application/json",
}


def _get(client: httpx.Client, path: str, params: dict[str, Any]) -> dict[str, Any]:
    last_err: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            r = client.get(
                f"{config.HEADOUT_BASE}{path}",
                params=params,
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            last_err = e
            if attempt < _RETRIES - 1:
                time.sleep(_RETRY_SLEEP * (attempt + 1))
    assert last_err is not None
    raise last_err


def list_products(city_code: str, page_size: int = 50) -> list[dict[str, Any]]:
    """Paginate through every Headout product for a city."""
    if not config.HEADOUT_API_KEY:
        raise RuntimeError("HEADOUT_API_KEY not set in .env")
    with httpx.Client() as client:
        products: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = _get(
                client,
                "/api/public/v2/products/",
                {"cityCode": city_code, "offset": offset, "limit": page_size},
            )
            items = data.get("products") or []
            if not items:
                break
            products.extend(items)
            total = data.get("total") or 0
            if len(products) >= total:
                break
            offset += page_size
            time.sleep(0.15)
        return products


def list_inventory_by_variant(
    variant_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    force_currency: str | None = "USD",
) -> dict[str, Any]:
    """Fetch inventory (bookable slots + prices) for one variant.

    Dates are optional YYYY-MM-DD strings. When omitted, Headout defaults to
    the next ~30 days. Prefer explicit 7-day windows for reliable pagination.
    """
    if not config.HEADOUT_API_KEY:
        raise RuntimeError("HEADOUT_API_KEY not set in .env")
    params: dict[str, Any] = {"variantId": variant_id}
    if start_date:
        params["startDateTime"] = f"{start_date}T00:00:00"
    if end_date:
        params["endDateTime"] = f"{end_date}T23:59:59"
    if force_currency:
        params["currencyCode"] = force_currency
    with httpx.Client() as client:
        return _get(client, "/api/v1/inventory/list-by/variant", params)


def pick_person_price(persons: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Given a `pricing.persons` list, pick the most representative row.

    Order: adult non-resident → adult resident → adult → general → first entry.
    Returns None if the list is empty.
    """
    if not persons:
        return None
    priority = [
        "ADULT_NON_RESIDENT",
        "ADULT_RESIDENT",
        "ADULT",
        "GENERAL",
    ]
    for want in priority:
        for p in persons:
            if (p.get("type") or "") == want:
                return p
    # last resort — anything with ADULT in the type
    for p in persons:
        if "ADULT" in (p.get("type") or ""):
            return p
    return persons[0]
