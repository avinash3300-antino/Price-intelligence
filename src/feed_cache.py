"""Live-feed cache: per-product warm-cache built from the Vercel API.

The bulk JSON endpoint (`/api/enriched-feed?format=json`) is currently
cache-poisoned on the Vercel side and returns only the most-recently-queried
product. The per-product variant (`?productId=X&productType=Y`) works fine
and is the only reliable source for options + variants.

This module warms a local cache of every product's options in parallel,
persists it to ``data/feed_cache.json``, and exposes accessors used by the
sync job and (eventually) the backend.

Only `activities` products return options; other types return an empty
options array, and we just record that fact rather than fall back to dummy
data (per Avinash's instruction: competitors stay dummy, everything else
must be real).
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import httpx

from src import config

FEED_CACHE_PATH: Path = config.DATA_DIR / "feed_cache.json"
PER_PRODUCT_URL = config.RAYNA_API_BASE + "/api/enriched-feed"
REQUEST_TIMEOUT_S = 30
DEFAULT_PARALLELISM = 30
DEFAULT_MAX_AGE_S = 6 * 3600

# Synthetic IDs live above this offset so they never collide with the
# legacy autoincrement option IDs (which are all < 1e9 in practice).
SYNTHETIC_ID_OFFSET = 1_000_000_000


def variant_synthetic_id(
    product_id: int, group_id: int | str, transfer_option_id: int | str
) -> int:
    """Stable deterministic int ID for one bookable variant.

    Same inputs → same int across runs. Used so re-syncing the cache leaves
    existing mappings intact instead of churning the FK.
    """
    s = f"{product_id}:{group_id}:{transfer_option_id}"
    h = hashlib.sha1(s.encode("utf-8")).digest()
    return SYNTHETIC_ID_OFFSET + int.from_bytes(h[:6], "big")


def _normalize_variant(
    product: dict[str, Any],
    option: dict[str, Any],
    variant: dict[str, Any],
) -> dict[str, Any]:
    """Flatten one (option, variant) pair into a row we can store + map."""
    pid = product["productId"]
    group_id = option.get("group_id")
    transfer_option_id = variant.get("option_id")

    # Prefer discounted_price (what the customer actually pays), fall back
    # to price_adult, then `amount` (= MRP). Some yacht variants only have
    # `amount` populated.
    price = (
        variant.get("discounted_price")
        or variant.get("price_adult")
        or variant.get("amount")
    )
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None

    transfer_type = variant.get("transfer_type") or "Standard"
    group_name = option.get("name") or product.get("name") or "Option"
    full_name = f"{group_name} – {transfer_type}"

    fingerprint = {
        "tier": (transfer_type or "standard").lower().replace(" ", "_"),
        "group_id": group_id,
        "transfer_type": transfer_type,
        "transfer_included": transfer_type and "without" not in transfer_type.lower(),
        "duration_minutes": variant.get("duration_minutes"),
        "pricing_basis": "per_adult",
        "cancellation_text": option.get("cancellation_text"),
        "vercel_option_id": transfer_option_id,
    }

    return {
        "variant_key": f"{pid}:{group_id}:{transfer_option_id}",
        "synthetic_id": variant_synthetic_id(pid, group_id, transfer_option_id),
        "product_id": pid,
        "product_name": product.get("name") or "",
        "product_type": product.get("type"),
        "country": product.get("country"),
        "city": product.get("city"),
        "currency": variant.get("currency") or product.get("currency") or "AED",
        "group_id": group_id,
        "group_name": group_name,
        "transfer_type": transfer_type,
        "name": full_name,
        "pricing_basis": "per_adult",
        "price": price,
        "duration_minutes": variant.get("duration_minutes"),
        "fingerprint": fingerprint,
    }


def _fetch_one(client: httpx.Client, product_id: int, product_type: str) -> dict[str, Any]:
    """Hit the per-product endpoint once; returns the raw product dict."""
    resp = client.get(
        PER_PRODUCT_URL,
        params={
            "format": "json",
            "productId": product_id,
            "productType": product_type or "activities",
        },
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    data = resp.json()
    products = data.get("products") or []
    if not products:
        return {}
    return products[0]


def _load_catalog_directory() -> list[dict[str, Any]]:
    """Read the existing rayna_catalog_live.json — the 1491-product directory
    that ingest_rayna.py keeps fresh. We use it as the list of (productId,
    productType) pairs to enrich.
    """
    if not config.CATALOG_LIVE_PATH.exists():
        raise RuntimeError(
            f"{config.CATALOG_LIVE_PATH} not found — run "
            f"`python -m src.ingest_rayna` first to populate the catalog directory."
        )
    raw = json.loads(config.CATALOG_LIVE_PATH.read_text())
    rows = raw.get("products") or []
    # dedup on productId — the API can return duplicate rows per enriched product
    by_id: dict[int, dict[str, Any]] = {}
    for r in rows:
        pid = r.get("productId")
        if pid is None:
            continue
        # prefer enriched
        prev = by_id.get(pid)
        if prev is None or (r.get("_enriched") and not prev.get("_enriched")):
            by_id[pid] = r
    return list(by_id.values())


def refresh_all(
    parallelism: int = DEFAULT_PARALLELISM,
    only_product_ids: Optional[Iterable[int]] = None,
    progress_every: int = 50,
) -> dict[str, Any]:
    """Fetch options for every catalog product, write to disk cache.

    Returns the on-disk payload (also written to FEED_CACHE_PATH).
    """
    directory = _load_catalog_directory()
    if only_product_ids is not None:
        keep = set(int(i) for i in only_product_ids)
        directory = [p for p in directory if p.get("productId") in keep]

    print(f"feed_cache: fetching options for {len(directory)} products "
          f"(parallelism={parallelism}) …")

    enriched: dict[int, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    started = time.monotonic()

    with httpx.Client(http2=False) as client:
        with ThreadPoolExecutor(max_workers=parallelism) as pool:
            futs = {
                pool.submit(
                    _fetch_one,
                    client,
                    p["productId"],
                    p.get("type") or "activities",
                ): p
                for p in directory
            }
            done = 0
            for fut in as_completed(futs):
                p = futs[fut]
                pid = p["productId"]
                try:
                    res = fut.result()
                except Exception as e:
                    failures.append({"product_id": pid, "error": f"{type(e).__name__}: {e}"})
                    res = {}

                enriched[pid] = {
                    # Keep the catalog metadata as source of truth for
                    # name/country/city/currency — the per-product response
                    # often returns blank fields there.
                    "productId": pid,
                    "name": p.get("name") or res.get("name") or "",
                    "type": p.get("type"),
                    "country": p.get("country"),
                    "city": p.get("city"),
                    "currency": p.get("currency") or res.get("currency") or "AED",
                    "url": p.get("url"),
                    "options_count": len(res.get("options") or []),
                    "options": res.get("options") or [],
                }
                done += 1
                if done % progress_every == 0 or done == len(directory):
                    rate = done / max(time.monotonic() - started, 0.001)
                    print(f"  {done}/{len(directory)}  ({rate:.1f}/s)")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "product_count": len(enriched),
        "products_with_options": sum(1 for p in enriched.values() if p["options_count"]),
        "failures": failures,
        "products": enriched,
    }
    FEED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEED_CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False))
    elapsed = time.monotonic() - started
    print(
        f"feed_cache: wrote {len(enriched)} products "
        f"({payload['products_with_options']} with options) "
        f"in {elapsed:.1f}s; {len(failures)} failures"
    )
    return payload


# -------- in-memory accessors (used by backend later) --------------------

_lock = threading.Lock()
_payload: dict[str, Any] | None = None
_variant_index: dict[int, dict[str, Any]] = {}
_by_product: dict[int, list[dict[str, Any]]] = {}


def _build_indexes(payload: dict[str, Any]) -> None:
    global _payload, _variant_index, _by_product
    variant_index: dict[int, dict[str, Any]] = {}
    by_product: dict[int, list[dict[str, Any]]] = {}
    for pid_str, prod in payload.get("products", {}).items():
        pid = int(pid_str) if isinstance(pid_str, str) else int(prod["productId"])
        variants: list[dict[str, Any]] = []
        for opt in prod.get("options") or []:
            for variant in opt.get("variants") or []:
                v = _normalize_variant(prod, opt, variant)
                variants.append(v)
                variant_index[v["synthetic_id"]] = v
        by_product[pid] = variants
    _payload = payload
    _variant_index = variant_index
    _by_product = by_product


def load_from_disk(force: bool = False, max_age_s: int = DEFAULT_MAX_AGE_S) -> bool:
    """Load the on-disk cache into memory. Returns True if loaded."""
    with _lock:
        if _payload is not None and not force:
            return True
        if not FEED_CACHE_PATH.exists():
            return False
        payload = json.loads(FEED_CACHE_PATH.read_text())
        _build_indexes(payload)
        return True


def is_stale(max_age_s: int = DEFAULT_MAX_AGE_S) -> bool:
    if not FEED_CACHE_PATH.exists():
        return True
    age = time.time() - FEED_CACHE_PATH.stat().st_mtime
    return age > max_age_s


def get_product(product_id: int) -> dict[str, Any] | None:
    load_from_disk()
    if _payload is None:
        return None
    return _payload.get("products", {}).get(str(product_id))


def get_variants_for(product_id: int) -> list[dict[str, Any]]:
    load_from_disk()
    return list(_by_product.get(int(product_id), []))


def get_variant(synthetic_id: int) -> dict[str, Any] | None:
    load_from_disk()
    return _variant_index.get(int(synthetic_id))


def get_all_variants() -> list[dict[str, Any]]:
    load_from_disk()
    return list(_variant_index.values())


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--parallelism", type=int, default=DEFAULT_PARALLELISM)
    p.add_argument(
        "--pilot",
        action="store_true",
        help="Only refresh the 5 PoC products (config.PILOT_PRODUCT_IDS)",
    )
    args = p.parse_args()
    only = config.PILOT_PRODUCT_IDS if args.pilot else None
    refresh_all(parallelism=args.parallelism, only_product_ids=only)
