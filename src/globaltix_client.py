"""Thin GlobalTix Partner API 3.0 client.

Auth is a per-session Bearer JWT (24hr) obtained via POST /api/auth/authorize
with headers ``x-api-key: <agent>/<key>`` and ``x-api-agent: <agent>`` plus a
JSON body ``{"username": "..."}``. We cache the token in-memory and refresh
on 401 or when it's within 10 minutes of expiry.

Only the endpoints we actually use are wrapped:

    list_countries()               -> /api/country/getAllCountries
    list_products(country_code)    -> /api/product/list?countryCode=&page=&size=
    list_options(product_id)       -> /api/product/options?id=
    check_availability(...)        -> /api/ticketType/checkEventAvailability

All errors and timeouts get 3 retries with a small backoff.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from src import config

_TIMEOUT = 45
_RETRIES = 3
_RETRY_SLEEP = 1.5
_TOKEN_LEEWAY_SEC = 600  # refresh 10 min before actual expiry
_PAGE_SIZE = 500

_lock = threading.Lock()
_token: str | None = None
_token_expiry: float = 0.0


def _require_creds() -> None:
    missing = [
        name
        for name, val in {
            "GLOBALTIX_AGENT": config.GLOBALTIX_AGENT,
            "GLOBALTIX_API_KEY": config.GLOBALTIX_API_KEY,
            "GLOBALTIX_USERNAME": config.GLOBALTIX_USERNAME,
        }.items()
        if not val
    ]
    if missing:
        raise RuntimeError(f"GlobalTix credentials missing in .env: {missing}")


def authenticate(force: bool = False) -> str:
    """Return a valid Bearer token, refreshing if needed."""
    global _token, _token_expiry
    _require_creds()

    with _lock:
        if _token and not force and time.time() < (_token_expiry - _TOKEN_LEEWAY_SEC):
            return _token

        r = httpx.post(
            f"{config.GLOBALTIX_BASE}/api/auth/authorize",
            headers={
                "x-api-key": f"{config.GLOBALTIX_AGENT}/{config.GLOBALTIX_API_KEY}",
                "x-api-agent": config.GLOBALTIX_AGENT,
                "Content-Type": "application/json",
            },
            json={"username": config.GLOBALTIX_USERNAME},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json().get("data") or {}
        tok = data.get("accessToken")
        if not tok:
            raise RuntimeError(f"GlobalTix auth returned no accessToken: {r.text[:400]}")
        _token = tok
        _token_expiry = time.time() + int(data.get("expiration") or 86400)
        return _token


def _headers() -> dict[str, str]:
    return {
        "Accept-Version": "1.0",
        "Authorization": f"Bearer {authenticate()}",
        "x-api-agent": config.GLOBALTIX_AGENT,
        "Accept": "application/json",
    }


def _get(client: httpx.Client, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    last_err: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            r = client.get(
                f"{config.GLOBALTIX_BASE}{path}",
                params=params,
                headers=_headers(),
                timeout=_TIMEOUT,
            )
            if r.status_code == 401:
                # token likely expired mid-run — refresh once and retry
                authenticate(force=True)
                r = client.get(
                    f"{config.GLOBALTIX_BASE}{path}",
                    params=params,
                    headers=_headers(),
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


def list_countries() -> list[dict[str, Any]]:
    """All GlobalTix countries with their cities nested."""
    with httpx.Client() as c:
        return _get(c, "/api/country/getAllCountries").get("data") or []


def list_products(country_code: str) -> list[dict[str, Any]]:
    """Paginate every product for a country.

    The staging default page size is 16; we explicitly send page=0&size=500 to
    grab everything in one shot for smaller markets, and paginate if needed.
    """
    with httpx.Client() as client:
        products: list[dict[str, Any]] = []
        page = 0
        while True:
            data = _get(
                client,
                "/api/product/list",
                {"countryCode": country_code, "page": page, "size": _PAGE_SIZE},
            )
            items = data.get("data") or []
            if not items:
                break
            products.extend(items)
            if len(items) < _PAGE_SIZE:
                break
            page += 1
            time.sleep(0.15)
        return products


def list_options(product_id: int | str) -> list[dict[str, Any]]:
    with httpx.Client() as c:
        return _get(
            c,
            "/api/product/options",
            {"id": product_id, "isDynamicPrice": "false"},
        ).get("data") or []


def check_availability(
    option_id: int | str,
    date_from: str,
    date_to: str,
) -> list[dict[str, Any]]:
    with httpx.Client() as c:
        return _get(
            c,
            "/api/ticketType/checkEventAvailability",
            {"id": option_id, "dateFrom": date_from, "dateTo": date_to},
        ).get("data") or []
