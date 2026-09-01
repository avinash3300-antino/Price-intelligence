"""FastAPI backend for the Market Intelligence Next.js UI.

Read-only API over the SQLite pipeline DB. Endpoints map 1:1 to the pages the
Next.js frontend renders, so the frontend never sees a SQL query directly.

Run: uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

import psycopg

from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend import deps
from backend.deps import assert_option_in_scope, assert_product_in_scope, require, require_admin
from backend.routes_admin import router as admin_router
from backend.routes_auth import router as auth_router
from src import auth, db

ROOT = Path(__file__).resolve().parent.parent

# The connection helper and the auth gates live in backend.deps so this module
# and the auth/admin routers share exactly one implementation.
conn = deps.conn


def row_to_dict(row: Any) -> dict[str, Any]:
    """Rows already arrive as dicts from psycopg's dict_row factory; copy so
    callers can mutate without touching the cursor's buffer."""
    return dict(row)


# ---------- Response models ----------


class Product(BaseModel):
    id: int
    name: str
    type: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    market: str
    currency: str
    url: Optional[str] = None


class CheapestCompetitor(BaseModel):
    domain: str
    price: float
    currency: str
    gap_aed: float
    gap_pct: float
    rayna_price: float


class RaynaPriceSummary(BaseModel):
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    currency: Optional[str] = None
    priced_count: int = 0
    unpriced_count: int = 0
    pricing_basis: Optional[str] = None  # if all options share the same basis


class DashboardStat(BaseModel):
    product: Product
    option_count: int
    seller_count: int
    comparable_count: int
    # Count of this product's Rayna options that have at least one manual
    # mapping. Renders as "N/option_count mapped" on the Products list.
    options_mapped_count: int = 0
    rayna_price: RaynaPriceSummary
    cheapest_competitor: Optional[CheapestCompetitor] = None


class PipelineStats(BaseModel):
    products: int
    rayna_options: int
    competitors: int
    scraped_listings: int
    competitor_options: int
    mappings: int
    identical: int
    near: int
    different: int
    needs_review: int


class DashboardPayload(BaseModel):
    pipeline: PipelineStats
    products: list[DashboardStat]


class RaynaOption(BaseModel):
    id: int
    name: str
    pricing_basis: str
    price: Optional[float] = None
    currency: Optional[str] = None
    market: str
    fingerprint: dict[str, Any]
    # Set only when the caller requested ?date=YYYY-MM-DD. Tells the UI
    # whether `price` is a real per-date observation or the fallback default.
    date_price_source: Optional[str] = None  # 'observation' | 'default' | None


class MappedCompetitorOption(BaseModel):
    mapping_id: int
    verdict: str
    confidence: float
    diff_notes: str
    competitor_option_id: int
    seller_domain: str
    listing_url: str
    name: str
    pricing_basis: str
    price: Optional[float] = None
    currency: Optional[str] = None
    fingerprint: dict[str, Any]


class RaynaOptionWithMappings(BaseModel):
    option: RaynaOption
    mappings: list[MappedCompetitorOption]


class ProductComparison(BaseModel):
    product: Product
    options: list[RaynaOptionWithMappings]


class CompetitorOptionForMapping(BaseModel):
    option_id: int
    name: str
    pricing_basis: str
    price: Optional[float] = None
    currency: Optional[str] = None
    tier: Optional[str] = None
    listing_url: str
    fingerprint: dict[str, Any]
    mapping: Optional[dict[str, Any]] = None  # {mapping_id, rayna_option_id, rayna_option_name} when mapped
    date_price_source: Optional[str] = None  # 'observation' | 'default' | None


class SellerGroup(BaseModel):
    seller_domain: str
    competitor_id: int
    listing_count: int
    options: list[CompetitorOptionForMapping]


class ProductMappingPayload(BaseModel):
    product: Product
    rayna_options: list[RaynaOption]
    sellers: list[SellerGroup]
    total_competitor_options: int


class OptionListItem(BaseModel):
    option_id: int
    name: str
    pricing_basis: str
    price: Optional[float] = None
    currency: Optional[str] = None
    fingerprint: dict[str, Any]
    product_id: int
    product_name: str
    product_city: Optional[str] = None
    product_country: Optional[str] = None
    product_type: Optional[str] = None
    seller_count: int
    mapped_count: int


class ManualMapRequest(BaseModel):
    rayna_option_id: int = Field(gt=0)
    competitor_option_id: int = Field(gt=0)


class ManualMapResponse(BaseModel):
    mapping_id: int
    rayna_option_id: int
    competitor_option_id: int
    created_at: str
    is_manual: bool = True


class AddByUrlRequest(BaseModel):
    rayna_option_id: int = Field(gt=0)
    url: str = Field(min_length=8)
    # Optional. When set, we skip the direct fetch entirely and use this text
    # instead. The UI sends this after a first fetch failed (paste-fallback).
    pasted_content: Optional[str] = None
    # Free-text reviewer note that gets stored in diff_notes prefix.
    note: Optional[str] = None


class ExtractedCompetitorOption(BaseModel):
    """One competitor option saved from a URL paste. Multiple of these may be
    returned per URL (Klook/GYG pages often list several packages)."""
    competitor_option_id: int
    name: str
    price: Optional[float] = None
    currency: Optional[str] = None
    pricing_basis: str
    # If the caller's Rayna option was mapped to this competitor option, these
    # fields carry the adjudicated verdict. Otherwise None.
    verdict: Optional[str] = None
    confidence: Optional[float] = None
    diff_notes: Optional[str] = None
    mapping_id: Optional[int] = None
    is_target: bool = False  # True for the option that got mapped to the user's target


class AddByUrlResponse(BaseModel):
    # Legacy per-option fields describe the option that got mapped to the
    # caller's target (backwards compat with the single-option UI). Set to
    # None if no option was a good enough match to auto-map.
    mapping_id: Optional[int]
    rayna_option_id: int
    competitor_option_id: int
    seller_domain: str
    listing_url: str
    verdict: str
    confidence: float
    diff_notes: str
    saved_mapping: bool
    competitor_name: str
    competitor_price: Optional[float]
    competitor_currency: Optional[str]
    competitor_pricing_basis: str
    # New: full list of every option extracted from the URL, in the order
    # Claude returned them. The UI shows all of these so the reviewer can
    # see the whole catalog on that page, not just the auto-mapped one.
    all_options: list[ExtractedCompetitorOption] = []


class MappedItem(BaseModel):
    mapping_id: int
    product_id: int
    product_name: str
    product_country: Optional[str] = None
    product_city: Optional[str] = None
    # Link to the product on raynatours.com, so the drawer can offer both
    # sides of the comparison rather than only the competitor's page.
    product_url: Optional[str] = None
    rayna_option_id: int
    rayna_option_name: str
    rayna_price: Optional[float] = None
    rayna_currency: Optional[str] = None
    rayna_basis: str
    competitor_option_id: int
    competitor_option_name: str
    competitor_price: Optional[float] = None
    competitor_currency: Optional[str] = None
    competitor_basis: str
    seller_domain: str
    listing_url: str
    created_at: str
    # Set only when the caller passed ?date=YYYY-MM-DD. Tells the UI whether
    # each price side is a real per-date observation or the fallback default.
    rayna_date_price_source: Optional[str] = None
    competitor_date_price_source: Optional[str] = None
    # ---- Evidence: why this pair is considered a match ----
    # These already existed on `mappings` but never reached /mapped, so the
    # page showed a price gap with no way to see what the adjudicator
    # actually concluded (or that a human overrode it by hand).
    verdict: str
    confidence: float
    diff_notes: str = ""
    judge_model: Optional[str] = None
    is_manual: bool = False
    human_reviewed: bool = False
    rayna_fingerprint: dict[str, Any] = {}
    competitor_fingerprint: dict[str, Any] = {}
    # When the seller page was last fetched — drives the staleness hint.
    listing_scraped_at: Optional[str] = None
    # Who created this link. Null for rows that predate RBAC on a deployment
    # that never ran the backfill, and for accounts since deleted.
    created_by_email: Optional[str] = None
    created_by_name: Optional[str] = None


class ReviewItem(BaseModel):
    mapping_id: int
    product_id: int
    product_name: str
    product_url: Optional[str] = None
    product_country: Optional[str] = None
    product_city: Optional[str] = None
    rayna_option_id: Optional[int] = None
    rayna_option_name: str
    rayna_price: Optional[float] = None
    rayna_currency: Optional[str] = None
    rayna_basis: str
    competitor_option_name: str
    competitor_price: Optional[float] = None
    competitor_currency: Optional[str] = None
    competitor_basis: str
    seller_domain: str
    verdict: str
    confidence: float
    diff_notes: str
    reasons: list[str]


# ---------- App ----------


app = FastAPI(title="Rayna Market Intelligence API", version="0.1.0")

# CORS — allow the Next.js frontend (3001 / 3002) plus localhost variants
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        "http://localhost:3000",
    ],
    # Required for the session cookie to survive a cross-origin request.
    # Local dev goes through the Next rewrite (same origin) and prod goes
    # through nginx, so this only matters if someone points the browser
    # straight at the API host.
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(admin_router)


@app.get("/api/health")
def health():
    """Liveness + database reachability. The UI polls this for the
    'crawler live' indicator, so it must not raise."""
    try:
        with conn() as c:
            c.execute("SELECT 1")
        return {"ok": True, "db": "postgres", "db_exists": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "db": "postgres", "db_exists": False, "error": str(e)[:200]}


@app.get("/api/dashboard", response_model=DashboardPayload)
def dashboard(
    user: dict[str, Any] = Depends(
        deps.require_any("mapping.view", "comparison.view", "mapped.view")
    ),
) -> DashboardPayload:
    with conn() as c:
        # Everything below is restricted to the caller's countries/cities.
        # For an admin this resolves to TRUE and the queries are unchanged;
        # for a user with no scope rows it resolves to FALSE, so they see an
        # empty catalogue rather than someone else's.
        scope_sql, scope_params = auth.scope_predicate(c, user, "p")

        products = [
            row_to_dict(r)
            for r in c.execute(
                f"SELECT p.* FROM products p WHERE {scope_sql} ORDER BY p.id",
                scope_params,
            )
        ]

        def scalar(sql: str, *args) -> int:
            # dict_row keys the result by column name; every caller here
            # selects a single aggregate, so take whatever the one value is.
            return next(iter(c.execute(sql, args).fetchone().values()))

        # Each total is joined back to products and filtered, so a scoped
        # user's KPI strip counts only their own market. Leaving these global
        # would leak the size of markets they cannot see.
        comp_join = (
            "FROM competitors comp JOIN products p ON p.id = comp.rayna_product_id"
        )
        listing_join = (
            "FROM competitor_listings cl "
            "JOIN competitors comp ON comp.id = cl.competitor_id "
            "JOIN products p ON p.id = comp.rayna_product_id"
        )
        comp_opt_join = (
            "FROM options o "
            "JOIN competitor_listings cl ON cl.id = o.competitor_listing_id "
            "JOIN competitors comp ON comp.id = cl.competitor_id "
            "JOIN products p ON p.id = comp.rayna_product_id"
        )
        map_join = (
            "FROM mappings m "
            "JOIN options ro ON ro.id = m.rayna_option_id "
            "JOIN products p ON p.id = ro.rayna_product_id"
        )

        def scoped(sql_head: str, extra: str = "") -> int:
            where = f"WHERE {scope_sql}" + (f" AND {extra}" if extra else "")
            return scalar(f"{sql_head} {where}", *scope_params)

        pipeline = PipelineStats(
            products=scoped("SELECT COUNT(*) FROM products p"),
            rayna_options=scoped(
                "SELECT COUNT(*) FROM options o JOIN products p ON p.id = o.rayna_product_id",
                "o.source='rayna'",
            ),
            competitors=scoped(f"SELECT COUNT(*) {comp_join}", "comp.sells_this_product = TRUE"),
            scraped_listings=scoped(f"SELECT COUNT(*) {listing_join}"),
            competitor_options=scoped(f"SELECT COUNT(*) {comp_opt_join}", "o.source='competitor'"),
            mappings=scoped(f"SELECT COUNT(*) {map_join}"),
            identical=scoped(f"SELECT COUNT(*) {map_join}", "m.verdict='identical'"),
            near=scoped(f"SELECT COUNT(*) {map_join}", "m.verdict='near'"),
            different=scoped(f"SELECT COUNT(*) {map_join}", "m.verdict='different'"),
            needs_review=scoped(f"SELECT COUNT(*) {map_join}", "m.confidence < 0.7"),
        )

        # ------------------------------------------------------------------
        # Per-product aggregates.
        #
        # This used to run five correlated queries per product — ~6,900 round
        # trips for the 1,380-product catalogue. SQLite absorbed that because
        # its queries are in-process function calls; Postgres does not, and the
        # endpoint measured 5.5x slower before this was folded into four
        # grouped queries.
        # ------------------------------------------------------------------

        # Rayna option counts + price summary. COALESCE on pricing_basis keeps
        # NULL as a distinct value: a product mixing NULL and 'per_adult' has
        # two bases and must report None, which COUNT(DISTINCT) alone would
        # miss because it skips NULLs.
        # Sentinel standing in for a NULL pricing_basis. Cannot be a NUL byte —
        # Postgres text columns reject those — and cannot collide with a real
        # basis value (per_adult, private_group, per_vehicle, ...).
        NULL_BASIS = "__null_basis__"
        opt_agg: dict[int, dict[str, Any]] = {
            r["pid"]: r
            for r in c.execute(
                """SELECT rayna_product_id AS pid,
                          COUNT(*)                      AS option_count,
                          COUNT(price)                  AS priced_count,
                          MIN(price)                    AS min_price,
                          MAX(price)                    AS max_price,
                          COUNT(DISTINCT COALESCE(pricing_basis, %s)) AS n_bases,
                          MIN(COALESCE(pricing_basis, %s))            AS any_basis,
                          (ARRAY_AGG(currency ORDER BY id)
                             FILTER (WHERE price IS NOT NULL))[1]     AS first_priced_currency
                   FROM options
                   WHERE source='rayna' AND rayna_product_id IS NOT NULL
                   GROUP BY rayna_product_id""",
                (NULL_BASIS, NULL_BASIS),
            )
        }

        seller_counts: dict[int, int] = {
            r["pid"]: r["n"]
            for r in c.execute(
                """SELECT rayna_product_id AS pid, COUNT(*) AS n
                   FROM competitors WHERE sells_this_product = TRUE
                   GROUP BY rayna_product_id"""
            )
        }

        mapped_counts: dict[int, int] = {
            r["pid"]: r["n"]
            for r in c.execute(
                """SELECT ro.rayna_product_id AS pid,
                          COUNT(DISTINCT m.rayna_option_id) AS n
                   FROM mappings m
                   JOIN options ro ON ro.id = m.rayna_option_id
                   WHERE m.is_manual = TRUE
                   GROUP BY ro.rayna_product_id"""
            )
        }

        # Comparable pairs for every product in one pass. Ordered by price so
        # the first row of each group is the cheapest — same answer the old
        # per-product min() gave, but with ties broken deterministically
        # instead of by whatever order the engine happened to return.
        comparable: dict[int, list[dict[str, Any]]] = {}
        for r in c.execute(
            """SELECT ro.rayna_product_id AS pid,
                      ro.price AS rp, o.price AS cp, o.currency AS cc,
                      c2.seller_domain
               FROM mappings m
               JOIN options o  ON o.id  = m.competitor_option_id
               JOIN options ro ON ro.id = m.rayna_option_id
               JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
               JOIN competitors c2 ON c2.id = cl.competitor_id
               WHERE m.verdict IN ('identical','near')
                 AND o.price IS NOT NULL AND o.price > 0
                 AND ro.price IS NOT NULL AND ro.price > 0
                 AND o.pricing_basis = ro.pricing_basis
                 AND o.currency = ro.currency
               ORDER BY ro.rayna_product_id, o.price, c2.seller_domain"""
        ):
            comparable.setdefault(r["pid"], []).append(r)

        stats: list[DashboardStat] = []
        for p in products:
            pid = p["id"]
            agg = opt_agg.get(pid)
            rows = comparable.get(pid, [])

            cheapest = None
            if rows:
                best = rows[0]  # ORDER BY o.price put the cheapest first
                cheapest = CheapestCompetitor(
                    domain=best["seller_domain"],
                    price=best["cp"],
                    currency=best["cc"],
                    gap_aed=best["cp"] - best["rp"],
                    gap_pct=(best["cp"] - best["rp"]) / best["rp"] * 100,
                    rayna_price=best["rp"],
                )

            if agg:
                basis = agg["any_basis"]
                price_summary = RaynaPriceSummary(
                    min_price=agg["min_price"],
                    max_price=agg["max_price"],
                    currency=agg["first_priced_currency"],
                    priced_count=agg["priced_count"],
                    unpriced_count=agg["option_count"] - agg["priced_count"],
                    pricing_basis=(
                        None
                        if agg["n_bases"] != 1 or basis == NULL_BASIS
                        else basis
                    ),
                )
                option_count = agg["option_count"]
            else:
                price_summary = RaynaPriceSummary(
                    min_price=None, max_price=None, currency=None,
                    priced_count=0, unpriced_count=0, pricing_basis=None,
                )
                option_count = 0

            stats.append(
                DashboardStat(
                    product=Product(**p),
                    option_count=option_count,
                    seller_count=seller_counts.get(pid, 0),
                    comparable_count=len(rows),
                    options_mapped_count=mapped_counts.get(pid, 0),
                    rayna_price=price_summary,
                    cheapest_competitor=cheapest,
                )
            )

        return DashboardPayload(pipeline=pipeline, products=stats)


@app.get("/api/products/{product_id}/comparison", response_model=ProductComparison)
def product_comparison(
    product_id: int,
    user: dict[str, Any] = Depends(require("comparison.view")),
) -> ProductComparison:
    with conn() as c:
        assert_product_in_scope(c, user, product_id)
        p = c.execute("SELECT * FROM products WHERE id=%s", (product_id,)).fetchone()
        if not p:
            raise HTTPException(status_code=404, detail="Product not found")

        rayna_options = c.execute(
            "SELECT * FROM options WHERE source='rayna' AND rayna_product_id=%s ORDER BY id",
            (product_id,),
        ).fetchall()

        options_payload: list[RaynaOptionWithMappings] = []
        for ro in rayna_options:
            mappings = c.execute(
                """SELECT m.id AS mapping_id, m.verdict, m.confidence, m.diff_notes,
                          o.id AS competitor_option_id, o.name, o.pricing_basis,
                          o.price, o.currency, o.fingerprint_json,
                          c.seller_domain, cl.listing_url
                   FROM mappings m
                   JOIN options o ON o.id = m.competitor_option_id
                   JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
                   JOIN competitors c ON c.id = cl.competitor_id
                   WHERE m.rayna_option_id=%s
                   ORDER BY
                     CASE m.verdict WHEN 'identical' THEN 0 WHEN 'near' THEN 1 ELSE 2 END,
                     m.confidence DESC""",
                (ro["id"],),
            ).fetchall()

            options_payload.append(
                RaynaOptionWithMappings(
                    option=RaynaOption(
                        id=ro["id"],
                        name=ro["name"],
                        pricing_basis=ro["pricing_basis"],
                        price=ro["price"],
                        currency=ro["currency"],
                        market=ro["market"],
                        fingerprint=json.loads(ro["fingerprint_json"] or "{}"),
                    ),
                    mappings=[
                        MappedCompetitorOption(
                            mapping_id=m["mapping_id"],
                            verdict=m["verdict"],
                            confidence=m["confidence"],
                            diff_notes=m["diff_notes"] or "",
                            competitor_option_id=m["competitor_option_id"],
                            seller_domain=m["seller_domain"],
                            listing_url=m["listing_url"],
                            name=m["name"],
                            pricing_basis=m["pricing_basis"],
                            price=m["price"],
                            currency=m["currency"],
                            fingerprint=json.loads(m["fingerprint_json"] or "{}"),
                        )
                        for m in mappings
                    ],
                )
            )

        return ProductComparison(product=Product(**row_to_dict(p)), options=options_payload)


@app.get("/api/review-queue", response_model=list[ReviewItem])
def review_queue(
    user: dict[str, Any] = Depends(require("review.decide")),
) -> list[ReviewItem]:
    with conn() as c:
        scope_sql, scope_params = auth.scope_predicate(c, user, "p")
        rows = c.execute(
            f"""SELECT m.id AS mapping_id, m.verdict, m.confidence, m.diff_notes,
                      p.id AS product_id, p.name AS product_name,
                      p.url AS product_url,
                      p.country AS product_country, p.city AS product_city,
                      ro.id AS rayna_option_id,
                      ro.name AS rayna_option_name, ro.price AS rayna_price,
                      ro.currency AS rayna_currency, ro.pricing_basis AS rayna_basis,
                      co.name AS competitor_option_name, co.price AS competitor_price,
                      co.currency AS competitor_currency, co.pricing_basis AS competitor_basis,
                      c.seller_domain
               FROM mappings m
               JOIN options ro ON ro.id = m.rayna_option_id
               JOIN options co ON co.id = m.competitor_option_id
               JOIN products p ON p.id = ro.rayna_product_id
               JOIN competitor_listings cl ON cl.id = co.competitor_listing_id
               JOIN competitors c ON c.id = cl.competitor_id
               WHERE (m.human_reviewed IS NULL OR m.human_reviewed = FALSE)
                 AND (m.confidence < 0.7
                      OR (ro.pricing_basis != co.pricing_basis
                          AND ro.pricing_basis != 'unknown'
                          AND co.pricing_basis != 'unknown'))
                 AND {scope_sql}
               ORDER BY m.confidence ASC""",
            scope_params,
        ).fetchall()

        items = []
        for r in rows:
            reasons: list[str] = []
            if r["confidence"] < 0.7:
                reasons.append(f"conf {r['confidence']:.2f}")
            basis_mm = (
                r["rayna_basis"] != r["competitor_basis"]
                and r["rayna_basis"] != "unknown"
                and r["competitor_basis"] != "unknown"
            )
            if basis_mm:
                reasons.append(f"basis: {r['rayna_basis']} vs {r['competitor_basis']}")
            items.append(ReviewItem(**{k: r[k] for k in r.keys()}, reasons=reasons))
        return items


# ---------- Manual mapping endpoints ----------


@app.get("/api/options/by-location", response_model=list[OptionListItem])
def options_by_location(
    country: Optional[str] = None,
    city: Optional[str] = None,
    user: dict[str, Any] = Depends(require("mapping.view")),
) -> list[OptionListItem]:
    """All Rayna options for products matching country/city. One row per option."""
    with conn() as c:
        sql = (
            """
            SELECT
              o.id              AS option_id,
              o.name            AS option_name,
              o.pricing_basis,
              o.price,
              o.currency,
              o.fingerprint_json,
              p.id              AS product_id,
              p.name            AS product_name,
              p.city            AS product_city,
              p.country         AS product_country,
              p.type            AS product_type,
              (SELECT COUNT(*) FROM competitors c2
                 WHERE c2.rayna_product_id = p.id AND c2.sells_this_product = TRUE) AS seller_count,
              (SELECT COUNT(*) FROM mappings m
                 WHERE m.rayna_option_id = o.id AND m.is_manual = TRUE) AS mapped_count
            FROM options o
            JOIN products p ON p.id = o.rayna_product_id
            WHERE o.source = 'rayna'
            """
        )
        args: list[Any] = []
        # The caller's own country/city filter narrows within their scope; it
        # can never widen past it.
        scope_sql, scope_params = auth.scope_predicate(c, user, "p")
        sql += f" AND {scope_sql}"
        args.extend(scope_params)
        if country:
            sql += " AND p.country = %s"
            args.append(country)
        if city:
            sql += " AND p.city = %s"
            args.append(city)
        sql += " ORDER BY p.id, o.id"

        rows = c.execute(sql, args).fetchall()
        return [
            OptionListItem(
                option_id=r["option_id"],
                name=r["option_name"],
                pricing_basis=r["pricing_basis"],
                price=r["price"],
                currency=r["currency"],
                fingerprint=json.loads(r["fingerprint_json"] or "{}"),
                product_id=r["product_id"],
                product_name=r["product_name"],
                product_city=r["product_city"],
                product_country=r["product_country"],
                product_type=r["product_type"],
                seller_count=r["seller_count"],
                mapped_count=r["mapped_count"],
            )
            for r in rows
        ]


def _observations_for(c, option_ids: list[int], target_date: str) -> dict[int, tuple[float, str]]:
    """Return {option_id: (price, currency)} for the most recent observation
    of each option on ``target_date``. Options with no observation are absent
    from the result (caller falls back to the option's default price)."""
    if not option_ids:
        return {}
    ph = ",".join(["%s"] * len(option_ids))
    rows = c.execute(
        f"""
        SELECT po.option_id, po.price, po.currency
        FROM price_observations po
        WHERE po.target_date = %s AND po.option_id IN ({ph})
        AND po.captured_at = (
            SELECT MAX(captured_at) FROM price_observations
            WHERE option_id = po.option_id AND target_date = po.target_date
        )
        """,
        [target_date, *option_ids],
    ).fetchall()
    return {r["option_id"]: (r["price"], r["currency"]) for r in rows}


@app.get(
    "/api/products/{product_id}/mapping-workspace",
    response_model=ProductMappingPayload,
)
def mapping_workspace(
    product_id: int,
    date: Optional[str] = None,
    user: dict[str, Any] = Depends(require("mapping.view")),
) -> ProductMappingPayload:
    """Everything the mapping split-view needs for one Rayna product.

    When ``date=YYYY-MM-DD`` is passed, per-option prices are substituted from
    the ``price_observations`` table (Rayna's date_price[] and Headout's
    per-slot inventory, ingested nightly). Options with no observation for
    that date fall back to the default price and are marked
    ``date_price_source='default'``.
    """
    with conn() as c:
        assert_product_in_scope(c, user, product_id)
        p = c.execute("SELECT * FROM products WHERE id=%s", (product_id,)).fetchone()
        if not p:
            raise HTTPException(status_code=404, detail="Product not found")

        rayna_opts = c.execute(
            "SELECT * FROM options WHERE source='rayna' AND rayna_product_id=%s ORDER BY id",
            (product_id,),
        ).fetchall()

        # collect option ids we'll look up date-observations for
        rayna_ids = [ro["id"] for ro in rayna_opts]
        comp_rows_pre = c.execute(
            """SELECT o.id FROM options o
               JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
               JOIN competitors cc ON cc.id = cl.competitor_id
               WHERE o.source='competitor' AND cc.rayna_product_id=%s""",
            (product_id,),
        ).fetchall()
        comp_ids = [r["id"] for r in comp_rows_pre]

        rayna_obs: dict[int, tuple[float, str]] = {}
        comp_obs: dict[int, tuple[float, str]] = {}
        if date:
            rayna_obs = _observations_for(c, rayna_ids, date)
            comp_obs = _observations_for(c, comp_ids, date)

        rayna_options_payload = []
        for ro in rayna_opts:
            if date:
                if ro["id"] in rayna_obs:
                    price, currency = rayna_obs[ro["id"]]
                    src = "observation"
                else:
                    price, currency = ro["price"], ro["currency"]
                    src = "default"
            else:
                price, currency, src = ro["price"], ro["currency"], None
            rayna_options_payload.append(
                RaynaOption(
                    id=ro["id"],
                    name=ro["name"],
                    pricing_basis=ro["pricing_basis"],
                    price=price,
                    currency=currency,
                    market=ro["market"],
                    fingerprint=json.loads(ro["fingerprint_json"] or "{}"),
                    date_price_source=src,
                )
            )
        rayna_id_to_name = {ro["id"]: ro["name"] for ro in rayna_opts}

        # all competitor options for this product, with manual-mapping state
        rows = c.execute(
            """SELECT o.id AS option_id, o.name, o.pricing_basis, o.price, o.currency,
                      o.fingerprint_json, c.id AS competitor_id, c.seller_domain,
                      cl.id AS listing_id, cl.listing_url,
                      m.id AS mapping_id, m.rayna_option_id, m.is_manual
               FROM options o
               JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
               JOIN competitors c ON c.id = cl.competitor_id
               LEFT JOIN mappings m ON m.competitor_option_id = o.id AND m.is_manual = TRUE
               WHERE o.source='competitor' AND c.rayna_product_id=%s
               ORDER BY c.seller_domain, cl.id, o.id""",
            (product_id,),
        ).fetchall()

        # group by seller_domain
        sellers_dict: dict[str, dict[str, Any]] = {}
        for r in rows:
            sd = r["seller_domain"]
            if sd not in sellers_dict:
                sellers_dict[sd] = {
                    "competitor_id": r["competitor_id"],
                    "listing_ids": set(),
                    "options": [],
                }

            fp = json.loads(r["fingerprint_json"] or "{}")
            mapping = None
            if r["mapping_id"] is not None:
                mapping = {
                    "mapping_id": r["mapping_id"],
                    "rayna_option_id": r["rayna_option_id"],
                    "rayna_option_name": rayna_id_to_name.get(r["rayna_option_id"], ""),
                }

            if date:
                if r["option_id"] in comp_obs:
                    price, currency = comp_obs[r["option_id"]]
                    src = "observation"
                else:
                    price, currency = r["price"], r["currency"]
                    src = "default"
            else:
                price, currency, src = r["price"], r["currency"], None

            sellers_dict[sd]["listing_ids"].add(r["listing_id"])
            sellers_dict[sd]["options"].append(
                CompetitorOptionForMapping(
                    option_id=r["option_id"],
                    name=r["name"],
                    pricing_basis=r["pricing_basis"],
                    price=price,
                    currency=currency,
                    tier=fp.get("tier"),
                    listing_url=r["listing_url"],
                    fingerprint=fp,
                    mapping=mapping,
                    date_price_source=src,
                )
            )

        sellers = [
            SellerGroup(
                seller_domain=sd,
                competitor_id=info["competitor_id"],
                listing_count=len(info["listing_ids"]),
                options=info["options"],
            )
            for sd, info in sorted(sellers_dict.items())
        ]

        return ProductMappingPayload(
            product=Product(**row_to_dict(p)),
            rayna_options=rayna_options_payload,
            sellers=sellers,
            total_competitor_options=sum(len(s.options) for s in sellers),
        )


@app.post("/api/mappings/manual", response_model=ManualMapResponse, status_code=201)
def create_manual_mapping(
    req: ManualMapRequest,
    request: Request,
    user: dict[str, Any] = Depends(require("mapping.create")),
) -> ManualMapResponse:
    with conn() as c:
        # sanity: both options must exist and have the right sources
        rayna = c.execute(
            "SELECT id, source, rayna_product_id FROM options WHERE id=%s",
            (req.rayna_option_id,),
        ).fetchone()
        comp = c.execute(
            """SELECT o.id, o.source, c.rayna_product_id
               FROM options o
               JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
               JOIN competitors c ON c.id = cl.competitor_id
               WHERE o.id=%s""",
            (req.competitor_option_id,),
        ).fetchone()

        if not rayna or rayna["source"] != "rayna":
            raise HTTPException(status_code=400, detail="rayna_option_id not a Rayna option")
        if not comp or comp["source"] != "competitor":
            raise HTTPException(status_code=400, detail="competitor_option_id not a competitor option")
        if rayna["rayna_product_id"] != comp["rayna_product_id"]:
            raise HTTPException(
                status_code=400,
                detail="Rayna option and competitor option belong to different Rayna products",
            )

        # Both options hang off the same product, so one check covers the pair.
        assert_product_in_scope(c, user, rayna["rayna_product_id"])

        # Constraint: one Rayna option can be mapped to at most one option per
        # seller_domain. Different sellers are fine (Headout + GlobalTix OK),
        # but not two options from the same seller. Blocking here also lets the
        # auto-adjudicator's replace-on-higher-confidence logic stay simple.
        conflict = c.execute(
            """SELECT m.id AS mapping_id, o2.name AS other_name, c2.seller_domain
               FROM mappings m
               JOIN options o2 ON o2.id = m.competitor_option_id
               JOIN competitor_listings cl2 ON cl2.id = o2.competitor_listing_id
               JOIN competitors c2 ON c2.id = cl2.competitor_id
               WHERE m.rayna_option_id = %s
                 AND m.competitor_option_id != %s
                 AND c2.seller_domain = (
                   SELECT c3.seller_domain
                   FROM options o3
                   JOIN competitor_listings cl3 ON cl3.id = o3.competitor_listing_id
                   JOIN competitors c3 ON c3.id = cl3.competitor_id
                   WHERE o3.id = %s
                 )""",
            (req.rayna_option_id, req.competitor_option_id, req.competitor_option_id),
        ).fetchone()
        if conflict:
            # Truncate other option name so the toast stays readable.
            other = conflict["other_name"] or "another option"
            if len(other) > 60:
                other = other[:57] + "…"
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This Rayna option is already mapped to \"{other}\" on "
                    f"{conflict['seller_domain']}. Unmap that first."
                ),
            )

        now = datetime.now(timezone.utc).isoformat()

        # 1. If this competitor option is already manually mapped to a DIFFERENT
        #    Rayna option, drop that prior manual mapping — a competitor option
        #    can only be linked to one Rayna option at a time.
        c.execute(
            """DELETE FROM mappings
               WHERE competitor_option_id=%s AND is_manual = TRUE
                 AND rayna_option_id != %s""",
            (req.competitor_option_id, req.rayna_option_id),
        )

        # 2. Look for an existing row on the unique (rayna_option_id, competitor_option_id)
        #    key. If it exists (Claude-generated or already manual), upgrade/refresh it
        #    rather than INSERT (which would violate the UNIQUE constraint).
        existing = c.execute(
            """SELECT id FROM mappings
               WHERE rayna_option_id=%s AND competitor_option_id=%s""",
            (req.rayna_option_id, req.competitor_option_id),
        ).fetchone()

        if existing:
            c.execute(
                """UPDATE mappings
                   SET verdict='identical', confidence=1.0,
                       diff_notes='Manually mapped by reviewer', judge_model='manual',
                       human_reviewed=TRUE, human_verdict='identical', is_manual=TRUE,
                       created_at=%s, created_by=%s
                   WHERE id=%s""",
                (now, user["id"], existing["id"]),
            )
            mapping_id = existing["id"]
        else:
            cur = c.execute(
                """INSERT INTO mappings
                     (rayna_option_id, competitor_option_id, verdict, confidence,
                      diff_notes, judge_model, human_reviewed, human_verdict,
                      is_manual, created_at, created_by)
                   VALUES (%s, %s, 'identical', 1.0, 'Manually mapped by reviewer',
                           'manual', TRUE, 'identical', TRUE, %s, %s)
                   RETURNING id""",
                (req.rayna_option_id, req.competitor_option_id, now, user["id"]),
            )
            mapping_id = cur.fetchone()["id"]

        auth.audit(
            c, user, "mapping.create", "mapping", mapping_id,
            after={
                "rayna_option_id": req.rayna_option_id,
                "competitor_option_id": req.competitor_option_id,
                "product_id": rayna["rayna_product_id"],
            },
            ip=deps.client_ip(request),
        )
        c.commit()

        return ManualMapResponse(
            mapping_id=mapping_id,
            rayna_option_id=req.rayna_option_id,
            competitor_option_id=req.competitor_option_id,
            created_at=now,
        )


@app.post("/api/mappings/from-url", response_model=AddByUrlResponse, status_code=201)
def create_mapping_from_url(
    req: AddByUrlRequest,
    request: Request,
    user: dict[str, Any] = Depends(require("competitor.add_url")),
) -> AddByUrlResponse:
    """Paste-a-URL flow.

    Fetches (or accepts pasted text for) a seller PDP, extracts one option
    with Claude, adjudicates the pair, and — if Claude judges it a like-for-
    like or 'near' match — creates a competitors + competitor_listing +
    options + mappings chain.

    Enforces the same same-seller constraint as `/api/mappings/manual`:
    if the Rayna option is already mapped to something on this seller_domain,
    returns 409 before any Claude/network work.
    """
    # Imports here (not top-of-file) so the read-only endpoints don't pay the
    # anthropic + src module load cost on every cold start.
    from anthropic import Anthropic

    from src import add_by_url, config, fx_rates

    with conn() as c:
        # 1. Validate Rayna option + get its anchor product
        rayna = c.execute(
            """SELECT o.id, o.name, o.pricing_basis, o.price, o.currency,
                      o.fingerprint_json, o.rayna_product_id,
                      p.name AS anchor_name, p.city AS anchor_city,
                      p.type AS anchor_type, p.market
               FROM options o
               JOIN products p ON o.rayna_product_id = p.id
               WHERE o.id=%s AND o.source='rayna'""",
            (req.rayna_option_id,),
        ).fetchone()
        if not rayna:
            raise HTTPException(status_code=404, detail="Rayna option not found")

        # Checked before any network or Claude spend, not after.
        assert_product_in_scope(c, user, rayna["rayna_product_id"])

        # 2. Seller domain from URL
        seller_domain = add_by_url.normalize_seller_domain(req.url)
        if not seller_domain:
            raise HTTPException(status_code=400, detail="Could not parse a seller host from the URL")

        # 3. Pre-check the 409 same-seller constraint — fail before we spend
        #    Claude money or hit the network.
        conflict = c.execute(
            """SELECT o2.name AS other_name
               FROM mappings m
               JOIN options o2 ON o2.id = m.competitor_option_id
               JOIN competitor_listings cl2 ON cl2.id = o2.competitor_listing_id
               JOIN competitors c2 ON c2.id = cl2.competitor_id
               WHERE m.rayna_option_id = %s AND c2.seller_domain = %s""",
            (req.rayna_option_id, seller_domain),
        ).fetchone()
        if conflict:
            other = conflict["other_name"] or "another option"
            if len(other) > 60:
                other = other[:57] + "…"
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This Rayna option is already mapped to \"{other}\" on "
                    f"{seller_domain}. Unmap that first."
                ),
            )

    # 4. Get the page content — either from pasted_content or a live fetch.
    page_title: Optional[str] = None
    if req.pasted_content and len(req.pasted_content.strip()) >= 200:
        content = req.pasted_content
    else:
        try:
            content, page_title = add_by_url.fetch_url_as_text(req.url)
        except add_by_url.FetchBlockedError as e:
            # 422 = the request is valid but we couldn't do it. UI reads this
            # as "show the paste-text textarea".
            raise HTTPException(status_code=422, detail=str(e)) from e

    # 5. Claude extraction — ALL bookable options on the page, not just one.
    print(
        f"[from-url] fetched {len(content)} chars from {req.url} "
        f"(title={page_title!r}); first 400 chars: {content[:400]!r}"
    )
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    try:
        extracted_list = add_by_url.extract_competitor_options(
            client, content, req.url, page_title,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Extraction failed: {type(e).__name__}: {e}",
        ) from e
    if not extracted_list:
        raise HTTPException(
            status_code=502,
            detail=(
                "Extraction returned zero options. Either the URL is a "
                "listing/category page (not a product page), or the page's "
                "package picker didn't render. Try pasting the page text "
                "into the fallback textarea."
            ),
        )

    rayna_opt_dict = {
        "name": rayna["name"],
        "price": rayna["price"],
        "currency": rayna["currency"],
        "pricing_basis": rayna["pricing_basis"] or "unknown",
        "fingerprint_json": rayna["fingerprint_json"] or "{}",
    }
    anchor_product = {
        "name": rayna["anchor_name"],
        "city": rayna["anchor_city"],
        "type": rayna["anchor_type"],
    }

    # 6. Adjudicate EACH extracted option against the target Rayna option.
    #    The best-match becomes the auto-mapped one. The others are still
    #    saved so the reviewer can map them to *other* Rayna options later.
    verdicts: list[Any] = []  # parallel to extracted_list
    judge_model = "manual-url"
    for opt in extracted_list:
        comp_dict = {
            "name": opt.name,
            "price": opt.price,
            "currency": opt.currency,
            "pricing_basis": opt.fingerprint.pricing_basis or "unknown",
            "fingerprint_json": opt.fingerprint.model_dump_json(),
        }
        try:
            v, _usage, judge_model = add_by_url.adjudicate_pair(
                client, rayna_opt_dict, comp_dict, anchor_product, seller_domain,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[from-url] adjudication failed for opt={opt.name!r}: {e}")
            v = None
        verdicts.append(v)

    # Pick the best index to auto-map: prefer 'identical' > 'near' > 'different',
    # then by confidence. None (adjudicator crash) is treated as worst.
    def _rank(v: Any) -> tuple[int, float]:
        if v is None:
            return (99, 0.0)
        order = {"identical": 0, "near": 1, "different": 2}
        return (order.get(v.verdict, 3), -float(v.confidence or 0))

    best_idx = min(range(len(verdicts)), key=lambda i: _rank(verdicts[i])) if verdicts else -1
    best_verdict = verdicts[best_idx] if best_idx >= 0 else None
    should_save_mapping = best_verdict is not None and (
        best_verdict.verdict in ("identical", "near")
        or (best_verdict.verdict == "different" and best_verdict.confidence < 0.6)
    )

    # 7. Persist competitors + listing + one options row per extracted option +
    #    one mapping (best_idx only).
    now = datetime.now(timezone.utc).isoformat()
    diff_prefix = f"[Manual URL paste] {req.note.strip()} — " if req.note else "[Manual URL paste] "

    saved_options: list[dict[str, Any]] = []  # rows to emit back to the UI

    with conn() as c:
        # 7a. Upsert competitor row
        comp_row = c.execute(
            """SELECT id FROM competitors
               WHERE rayna_product_id=%s AND market=%s AND seller_domain=%s""",
            (rayna["rayna_product_id"], rayna["market"], seller_domain),
        ).fetchone()
        if comp_row:
            competitor_id = comp_row["id"]
        else:
            cur = c.execute(
                """INSERT INTO competitors
                    (rayna_product_id, market, seller_domain, seller_name,
                     seed_url, sells_this_product, discovered_at,
                     classified_as, classifier_confidence, classifier_reason,
                     classified_at, created_by)
                   VALUES (%s, %s, %s, %s, %s, TRUE, %s, 'sells_this_product', 1.0,
                           'Manually added via URL paste', %s, %s)
                   RETURNING id""",
                (
                    rayna["rayna_product_id"], rayna["market"], seller_domain,
                    seller_domain, req.url, now, now, user["id"],
                ),
            )
            competitor_id = cur.fetchone()["id"]

        # 7b. Insert competitor_listings row (always fresh — one row per paste)
        cur = c.execute(
            """INSERT INTO competitor_listings
                (competitor_id, listing_url, title, raw_markdown,
                 raw_html, scraped_at, scrape_method, created_by)
               VALUES (%s, %s, %s, %s, NULL, %s, 'manual_url', %s)
               RETURNING id""",
            (
                competitor_id, req.url,
                page_title or (extracted_list[0].name if extracted_list else ""),
                content[:200000],
                now,
                user["id"],
            ),
        )
        listing_id = cur.fetchone()["id"]

        # 7c. Insert every extracted option, mapping the best one only.
        # Every price is normalized to AED here using the daily fx_rates cache
        # so the modal + gap comparison never has to guess at conversion. The
        # ORIGINAL price + currency the seller quoted are stashed inside
        # raw_extracted_json (opt.model_dump_json) so we can always re-audit.
        mapping_id: Optional[int] = None
        for i, opt in enumerate(extracted_list):
            original_currency = (opt.currency or "").strip().upper() or None
            aed_price = fx_rates.to_aed(opt.price, original_currency)
            # If conversion failed (unknown currency, no rate), fall through
            # to the raw values so we never blank a row — the source of truth
            # is still preserved in raw_extracted_json.
            stored_price = aed_price if aed_price is not None else opt.price
            stored_currency = "AED" if aed_price is not None else original_currency

            cur = c.execute(
                """INSERT INTO options
                    (source, competitor_listing_id, name, pricing_basis,
                     price, currency, market, fingerprint_json,
                     raw_extracted_json, extraction_model, extracted_at)
                   VALUES ('competitor', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    listing_id,
                    opt.name,
                    opt.fingerprint.pricing_basis or "unknown",
                    stored_price,
                    stored_currency,
                    rayna["market"],
                    opt.fingerprint.model_dump_json(),
                    opt.model_dump_json(),
                    "manual-url",
                    now,
                ),
            )
            opt_id = cur.fetchone()["id"]
            v = verdicts[i]
            is_target = i == best_idx

            if is_target and should_save_mapping and v is not None:
                cur = c.execute(
                    """INSERT INTO mappings
                        (rayna_option_id, competitor_option_id, verdict, confidence,
                         diff_notes, judge_model, human_reviewed, human_verdict,
                         is_manual, created_at, created_by)
                       VALUES (%s, %s, %s, %s, %s, %s, FALSE, NULL, TRUE, %s, %s)
                       RETURNING id""",
                    (
                        req.rayna_option_id, opt_id,
                        v.verdict, v.confidence,
                        diff_prefix + v.diff_notes, judge_model, now,
                        user["id"],
                    ),
                )
                mapping_id = cur.fetchone()["id"]

            saved_options.append({
                "competitor_option_id": opt_id,
                "name": opt.name,
                "price": stored_price,
                "currency": stored_currency,
                "pricing_basis": opt.fingerprint.pricing_basis or "unknown",
                "verdict": v.verdict if v is not None else None,
                "confidence": float(v.confidence) if v is not None else None,
                "diff_notes": v.diff_notes if v is not None else None,
                "mapping_id": mapping_id if is_target else None,
                "is_target": is_target,
            })

        auth.audit(
            c, user, "competitor.add_url", "listing", listing_id,
            after={
                "url": req.url,
                "seller_domain": seller_domain,
                "rayna_option_id": req.rayna_option_id,
                "options_extracted": len(saved_options),
                "mapping_id": mapping_id,
            },
            ip=deps.client_ip(request),
        )
        c.commit()

    # Legacy per-option fields describe the auto-mapped option (or the first
    # one, if nothing was mapped) so old clients keep working.
    primary = saved_options[best_idx] if best_idx >= 0 else saved_options[0]
    return AddByUrlResponse(
        mapping_id=mapping_id,
        rayna_option_id=req.rayna_option_id,
        competitor_option_id=primary["competitor_option_id"],
        seller_domain=seller_domain,
        listing_url=req.url,
        verdict=(best_verdict.verdict if best_verdict else "different"),
        confidence=float(best_verdict.confidence if best_verdict else 0.0),
        diff_notes=(best_verdict.diff_notes if best_verdict else "Could not adjudicate."),
        saved_mapping=should_save_mapping,
        competitor_name=primary["name"],
        competitor_price=primary["price"],
        competitor_currency=primary["currency"],
        competitor_pricing_basis=primary["pricing_basis"],
        all_options=[ExtractedCompetitorOption(**o) for o in saved_options],
    )


@app.delete("/api/mappings/{mapping_id}", status_code=204)
def delete_mapping(
    mapping_id: int,
    request: Request,
    user: dict[str, Any] = Depends(require("mapping.delete")),
):
    with conn() as c:
        row = c.execute(
            """SELECT m.is_manual, m.rayna_option_id, m.competitor_option_id,
                      ro.rayna_product_id
               FROM mappings m
               JOIN options ro ON ro.id = m.rayna_option_id
               WHERE m.id=%s""",
            (mapping_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Mapping not found")
        # is_manual is a BOOLEAN now; `!= 1` happened to work because Python
        # treats True as 1, but the intent is simply "not manual".
        if not row["is_manual"]:
            raise HTTPException(
                status_code=403,
                detail="Refusing to delete an automated (Claude) mapping; only manual rows can be deleted via this endpoint.",
            )
        assert_product_in_scope(c, user, row["rayna_product_id"])
        c.execute("DELETE FROM mappings WHERE id=%s", (mapping_id,))
        auth.audit(
            c, user, "mapping.delete", "mapping", mapping_id,
            before={
                "rayna_option_id": row["rayna_option_id"],
                "competitor_option_id": row["competitor_option_id"],
            },
            ip=deps.client_ip(request),
        )
        c.commit()
        return None


@app.delete("/api/competitor-options/{option_id}", status_code=204)
def delete_competitor_option(
    option_id: int,
    request: Request,
    user: dict[str, Any] = Depends(require("competitor.delete_option")),
):
    """Remove a single competitor option row. Cascades:
      1. Any mappings that reference it (usually 0 or 1 rows).
      2. The option row itself.
      3. The parent listing IF it has no options left AND no other listings
         for the same competitor point at it (keeps the listings table tidy).
    The parent `competitors` row is kept — a seller can still exist for the
    product with zero listings if the reviewer plans to add fresh URLs.
    """
    with conn() as c:
        row = c.execute(
            """SELECT o.id, o.name, o.competitor_listing_id, o.source
               FROM options o WHERE o.id=%s""",
            (option_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Competitor option not found")
        if row["source"] != "competitor":
            raise HTTPException(
                status_code=400,
                detail="This endpoint only deletes competitor options; Rayna options are catalog data.",
            )
        listing_id = row["competitor_listing_id"]
        assert_option_in_scope(c, user, option_id)
        auth.audit(
            c, user, "competitor.delete_option", "option", option_id,
            before={"name": row["name"], "listing_id": listing_id},
            ip=deps.client_ip(request),
        )

        c.execute("DELETE FROM mappings WHERE competitor_option_id=%s", (option_id,))
        c.execute("DELETE FROM price_observations WHERE option_id=%s", (option_id,))
        c.execute("DELETE FROM options WHERE id=%s", (option_id,))

        remaining = c.execute(
            "SELECT COUNT(*) AS n FROM options WHERE competitor_listing_id=%s",
            (listing_id,),
        ).fetchone()["n"]
        if remaining == 0:
            c.execute("DELETE FROM competitor_listings WHERE id=%s", (listing_id,))

        c.commit()
        return None


@app.delete("/api/competitors/{competitor_id}", status_code=204)
def delete_competitor(
    competitor_id: int,
    request: Request,
    user: dict[str, Any] = Depends(require("competitor.delete_seller")),
):
    """Wipe an entire seller for one Rayna product. Cascades everything:
    mappings → options → listings → the competitors row itself.
    Use when a whole seller was added by mistake or is no longer relevant.
    Reviewer can re-add later via Add-by-URL."""
    with conn() as c:
        row = c.execute(
            "SELECT id, seller_domain, rayna_product_id FROM competitors WHERE id=%s",
            (competitor_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Competitor not found")
        assert_product_in_scope(c, user, row["rayna_product_id"])
        auth.audit(
            c, user, "competitor.delete_seller", "competitor", competitor_id,
            before={
                "seller_domain": row["seller_domain"],
                "rayna_product_id": row["rayna_product_id"],
            },
            ip=deps.client_ip(request),
        )

        # 1. mappings whose competitor_option belongs to this seller
        c.execute(
            """DELETE FROM mappings
               WHERE competitor_option_id IN (
                 SELECT o.id FROM options o
                 JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
                 WHERE cl.competitor_id = %s
               )""",
            (competitor_id,),
        )
        # 2. per-date observations for those options
        c.execute(
            """DELETE FROM price_observations
               WHERE option_id IN (
                 SELECT o.id FROM options o
                 JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
                 WHERE cl.competitor_id = %s
               )""",
            (competitor_id,),
        )
        # 3. options
        c.execute(
            """DELETE FROM options
               WHERE competitor_listing_id IN (
                 SELECT id FROM competitor_listings WHERE competitor_id = %s
               )""",
            (competitor_id,),
        )
        # 4. listings
        c.execute(
            "DELETE FROM competitor_listings WHERE competitor_id=%s",
            (competitor_id,),
        )
        # 5. the seller row itself
        c.execute("DELETE FROM competitors WHERE id=%s", (competitor_id,))
        c.commit()
        return None


class ReviewDecisionRequest(BaseModel):
    approve: bool


class ReviewDecisionResponse(BaseModel):
    mapping_id: int
    action: str  # "approved" | "rejected"


@app.post(
    "/api/mappings/{mapping_id}/review",
    response_model=ReviewDecisionResponse,
    status_code=200,
)
def review_mapping(
    mapping_id: int,
    req: ReviewDecisionRequest,
    request: Request,
    user: dict[str, Any] = Depends(require("review.decide")),
) -> ReviewDecisionResponse:
    """Resolve a review-queue entry.

    ``approve=true`` — set human_reviewed=1 with the existing verdict so the
    mapping stays but drops off the queue.
    ``approve=false`` — delete the mapping outright. The competitor option row
    stays available in the workspace to be remapped elsewhere.
    """
    with conn() as c:
        row = c.execute(
            """SELECT m.verdict, ro.rayna_product_id
               FROM mappings m
               JOIN options ro ON ro.id = m.rayna_option_id
               WHERE m.id=%s""",
            (mapping_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Mapping not found")
        assert_product_in_scope(c, user, row["rayna_product_id"])
        if req.approve:
            c.execute(
                """UPDATE mappings
                     SET human_reviewed=TRUE,
                         human_verdict=%s
                   WHERE id=%s""",
                (row["verdict"], mapping_id),
            )
            action = "approved"
        else:
            c.execute("DELETE FROM mappings WHERE id=%s", (mapping_id,))
            action = "rejected"
        auth.audit(
            c, user, f"review.{action}", "mapping", mapping_id,
            after={"approve": req.approve, "verdict": row["verdict"]},
            ip=deps.client_ip(request),
        )
        c.commit()
        return ReviewDecisionResponse(mapping_id=mapping_id, action=action)


@app.get("/api/mapped", response_model=list[MappedItem])
def mapped_list(
    date: Optional[str] = None,
    user: dict[str, Any] = Depends(require("mapped.view")),
) -> list[MappedItem]:
    """List all manual mappings. When ``date=YYYY-MM-DD`` is passed, both
    Rayna and competitor prices are swapped with the most recent
    ``price_observations`` entry for that date. Options without an
    observation fall back to the default price (marked ``…_date_price_source
    ='default'``)."""
    with conn() as c:
        scope_sql, scope_params = auth.scope_predicate(c, user, "p")
        rows = c.execute(
            f"""SELECT m.id AS mapping_id, m.created_at,
                      m.verdict, m.confidence, m.diff_notes, m.judge_model,
                      m.is_manual, m.human_reviewed,
                      p.id AS product_id, p.name AS product_name,
                      p.country AS product_country, p.city AS product_city,
                      p.url AS product_url,
                      ro.id AS rayna_option_id, ro.name AS rayna_option_name,
                      ro.price AS rayna_price, ro.currency AS rayna_currency,
                      ro.pricing_basis AS rayna_basis,
                      ro.fingerprint_json AS rayna_fingerprint_json,
                      co.id AS competitor_option_id, co.name AS competitor_option_name,
                      co.price AS competitor_price, co.currency AS competitor_currency,
                      co.pricing_basis AS competitor_basis,
                      co.fingerprint_json AS competitor_fingerprint_json,
                      c.seller_domain, cl.listing_url,
                      cl.scraped_at AS listing_scraped_at,
                      cu.email AS created_by_email,
                      cu.full_name AS created_by_name
               FROM mappings m
               JOIN options ro ON ro.id = m.rayna_option_id
               JOIN options co ON co.id = m.competitor_option_id
               JOIN products p ON p.id = ro.rayna_product_id
               JOIN competitor_listings cl ON cl.id = co.competitor_listing_id
               JOIN competitors c ON c.id = cl.competitor_id
               LEFT JOIN users cu ON cu.id = m.created_by
               WHERE m.is_manual = TRUE AND {scope_sql}
               ORDER BY m.created_at DESC""",
            scope_params,
        ).fetchall()

        if not rows:
            return []

        # If a date is requested, look up both sides' observations in bulk
        # (one query for all rayna_option_ids, one for all competitor_option_ids).
        rayna_obs: dict[int, tuple[float, str]] = {}
        comp_obs: dict[int, tuple[float, str]] = {}
        if date:
            rayna_obs = _observations_for(c, [r["rayna_option_id"] for r in rows], date)
            comp_obs = _observations_for(c, [r["competitor_option_id"] for r in rows], date)

        out: list[MappedItem] = []
        for r in rows:
            d = {k: r[k] for k in r.keys()}
            # Fingerprints are stored as JSON text; the drawer wants objects.
            d["rayna_fingerprint"] = json.loads(d.pop("rayna_fingerprint_json") or "{}")
            d["competitor_fingerprint"] = json.loads(
                d.pop("competitor_fingerprint_json") or "{}"
            )
            d["diff_notes"] = d.get("diff_notes") or ""
            d["is_manual"] = bool(d.get("is_manual"))
            d["human_reviewed"] = bool(d.get("human_reviewed"))
            if date:
                if r["rayna_option_id"] in rayna_obs:
                    p, cur = rayna_obs[r["rayna_option_id"]]
                    d["rayna_price"] = p
                    d["rayna_currency"] = cur
                    d["rayna_date_price_source"] = "observation"
                else:
                    d["rayna_date_price_source"] = "default"
                if r["competitor_option_id"] in comp_obs:
                    p, cur = comp_obs[r["competitor_option_id"]]
                    d["competitor_price"] = p
                    d["competitor_currency"] = cur
                    d["competitor_date_price_source"] = "observation"
                else:
                    d["competitor_date_price_source"] = "default"
            out.append(MappedItem(**d))
        return out
