"""Per-product competitor discovery via SearchAPI.io (Google, UAE locale).

Brief's Idea 3: competitors are discovered per product per market, not assumed.
This module bulk-collects ranked organic results. Classification of which
results are real sellers (vs review sites / aggregators / noise) is a separate
Claude pass run later — kept separate so re-running discovery doesn't re-burn
classification tokens.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import httpx

from src import config, db

CACHE_DIR = config.DATA_DIR / "searchapi_cache"

# Hard-coded query packs for the 5 PoC products. v0: easy to swap; later we'll
# generate queries with Claude or pull them from the product itself.
QUERIES_BY_PRODUCT: dict[int, list[str]] = {
    18: [
        "burj khalifa at the top tickets",
        "burj khalifa tickets dubai",
        "burj khalifa observation deck booking",
    ],
    33: [
        "dubai city tour",
        "dubai sightseeing tour half day",
        "dubai city tour sic shared",
    ],
    36: [
        "red dune safari dubai",
        "dubai desert safari evening",
        "al lahbab desert safari",
    ],
    39: [
        "dinner in desert dubai",
        "desert dinner safari dubai no dune bashing",
        "dubai desert dinner experience",
    ],
    47: [
        "deep sea fishing dubai",
        "dubai fishing charter",
        "dubai marina fishing trip",
    ],
}

# Domains we never want to compare against. Own site + obvious non-sellers.
# Aggregators (viator/getyourguide/klook) ARE real competitors and stay in.
EXCLUDE_DOMAINS = {
    "raynatours.com",
    "google.com",
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "wikipedia.org",
    "reddit.com",
    "quora.com",
    "linkedin.com",
}


def registrable_domain(url: str) -> str | None:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return None
    host = host.lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    # crude eTLD+1 — fine for the obvious TLDs we'll see in this market
    parts = host.split(".")
    if len(parts) < 2:
        return host or None
    # handle .co.uk / .com.au style two-part TLDs
    two_part_tlds = {"co.uk", "co.in", "com.au", "co.nz", "co.jp", "com.sg"}
    tail = ".".join(parts[-2:])
    if tail in two_part_tlds and len(parts) >= 3:
        return ".".join(parts[-3:])
    return tail


def _cache_path(query: str, gl: str, hl: str) -> Path:
    h = hashlib.sha1(f"{query}|{gl}|{hl}".encode()).hexdigest()[:16]
    safe = re.sub(r"[^a-z0-9]+", "-", query.lower())[:60]
    return CACHE_DIR / f"{safe}-{h}.json"


def search(query: str, gl: str = "ae", hl: str = "en", num: int = 10) -> dict:
    """Run a Google search via SearchAPI. Cached on disk by query+locale."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_path(query, gl, hl)
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    r = httpx.get(
        "https://www.searchapi.io/api/v1/search",
        params={
            "engine": "google",
            "q": query,
            "gl": gl,
            "hl": hl,
            "num": num,
            "api_key": config.SEARCHAPI_KEY,
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return data


def _iter_organic(payload: dict) -> Iterable[dict]:
    for r in payload.get("organic_results", []) or []:
        yield r


def discover_for_product(product_id: int, queries: list[str]) -> int:
    """Run all queries for one product, dedupe by domain, store in `competitors`."""
    now = datetime.now(timezone.utc).isoformat()
    seen: dict[str, dict] = {}  # domain -> best record

    for q in queries:
        payload = search(q, gl="ae", hl="en", num=10)
        for rank, item in enumerate(_iter_organic(payload), 1):
            url = item.get("link") or ""
            domain = registrable_domain(url)
            if not domain or domain in EXCLUDE_DOMAINS:
                continue
            # Keep the highest-ranked sighting of each domain
            prior = seen.get(domain)
            if prior is None or rank < prior["search_rank"]:
                seen[domain] = {
                    "domain": domain,
                    "seller_name": (item.get("title") or "").split(" - ")[0][:120],
                    "search_rank": rank,
                    "search_query": q,
                    "url": url,
                    "snippet": (item.get("snippet") or "")[:500],
                }

    with db.tx() as conn:
        for rec in seen.values():
            conn.execute(
                """
                INSERT OR IGNORE INTO competitors
                  (rayna_product_id, market, seller_domain, seller_name,
                   seed_url, snippet, search_rank, search_query, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    config.PILOT_MARKET,
                    rec["domain"],
                    rec["seller_name"],
                    rec["url"],
                    rec["snippet"],
                    rec["search_rank"],
                    rec["search_query"],
                    now,
                ),
            )
    return len(seen)


def run() -> None:
    db.init_db()
    conn = db.get_conn()
    products = list(conn.execute("SELECT id, name FROM products ORDER BY id"))
    conn.close()

    for p in products:
        queries = QUERIES_BY_PRODUCT.get(p["id"], [p["name"]])
        print(f"\n→ [{p['id']}] {p['name']}")
        for q in queries:
            print(f"   q: {q}")
        n = discover_for_product(p["id"], queries)
        print(f"   {n} unique competitor domains")

    print()
    conn = db.get_conn()
    print("Top 5 competitors per product:")
    for p in products:
        print(f"\n  [{p['id']}] {p['name']}")
        for c in conn.execute(
            "SELECT seller_domain, seller_name, search_rank, search_query "
            "FROM competitors WHERE rayna_product_id=? ORDER BY search_rank LIMIT 5",
            (p["id"],),
        ):
            print(f"    {c['search_rank']:>2}. {c['seller_domain']:<35} — {c['seller_name'][:60]}")
    conn.close()


if __name__ == "__main__":
    run()
