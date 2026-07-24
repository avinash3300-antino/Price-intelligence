"""FastAPI backend for the Market Intelligence Next.js UI.

Read-only API over the SQLite pipeline DB. Endpoints map 1:1 to the pages the
Next.js frontend renders, so the frontend never sees a SQL query directly.

Run: uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "market_intel.db"


@contextmanager
def conn():
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail=f"DB not found at {DB_PATH}")
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


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


class AddByUrlResponse(BaseModel):
    mapping_id: Optional[int]  # None if verdict='different' and low confidence
    rayna_option_id: int
    competitor_option_id: int
    seller_domain: str
    listing_url: str
    verdict: str
    confidence: float
    diff_notes: str
    saved_mapping: bool
    # A minimal preview of what got extracted so the UI can render immediately.
    competitor_name: str
    competitor_price: Optional[float]
    competitor_currency: Optional[str]
    competitor_pricing_basis: str


class MappedItem(BaseModel):
    mapping_id: int
    product_id: int
    product_name: str
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


class ReviewItem(BaseModel):
    mapping_id: int
    product_id: int
    product_name: str
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
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"ok": True, "db": str(DB_PATH), "db_exists": DB_PATH.exists()}


@app.get("/api/dashboard", response_model=DashboardPayload)
def dashboard() -> DashboardPayload:
    with conn() as c:
        products = [row_to_dict(r) for r in c.execute("SELECT * FROM products ORDER BY id")]

        def scalar(sql: str, *args) -> int:
            return c.execute(sql, args).fetchone()[0]

        pipeline = PipelineStats(
            products=scalar("SELECT COUNT(*) FROM products"),
            rayna_options=scalar("SELECT COUNT(*) FROM options WHERE source='rayna'"),
            competitors=scalar("SELECT COUNT(*) FROM competitors WHERE sells_this_product=1"),
            scraped_listings=scalar("SELECT COUNT(*) FROM competitor_listings"),
            competitor_options=scalar("SELECT COUNT(*) FROM options WHERE source='competitor'"),
            mappings=scalar("SELECT COUNT(*) FROM mappings"),
            identical=scalar("SELECT COUNT(*) FROM mappings WHERE verdict='identical'"),
            near=scalar("SELECT COUNT(*) FROM mappings WHERE verdict='near'"),
            different=scalar("SELECT COUNT(*) FROM mappings WHERE verdict='different'"),
            needs_review=scalar("SELECT COUNT(*) FROM mappings WHERE confidence < 0.7"),
        )

        stats: list[DashboardStat] = []
        for p in products:
            option_count = scalar(
                "SELECT COUNT(*) FROM options WHERE source='rayna' AND rayna_product_id=?",
                p["id"],
            )
            seller_count = scalar(
                "SELECT COUNT(*) FROM competitors WHERE rayna_product_id=? AND sells_this_product=1",
                p["id"],
            )

            comparable_rows = c.execute(
                """SELECT ro.price AS rp, o.price AS cp, o.currency AS cc, c.seller_domain
                   FROM mappings m
                   JOIN options o ON o.id = m.competitor_option_id
                   JOIN options ro ON ro.id = m.rayna_option_id
                   JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
                   JOIN competitors c ON c.id = cl.competitor_id
                   WHERE ro.rayna_product_id = ?
                     AND m.verdict IN ('identical','near')
                     AND o.price IS NOT NULL AND o.price > 0
                     AND ro.price IS NOT NULL AND ro.price > 0
                     AND o.pricing_basis = ro.pricing_basis
                     AND o.currency = ro.currency""",
                (p["id"],),
            ).fetchall()

            cheapest = None
            if comparable_rows:
                best = min(comparable_rows, key=lambda r: r["cp"])
                cheapest = CheapestCompetitor(
                    domain=best["seller_domain"],
                    price=best["cp"],
                    currency=best["cc"],
                    gap_aed=best["cp"] - best["rp"],
                    gap_pct=(best["cp"] - best["rp"]) / best["rp"] * 100,
                    rayna_price=best["rp"],
                )

            rayna_opt_rows = c.execute(
                """SELECT price, currency, pricing_basis
                   FROM options
                   WHERE source='rayna' AND rayna_product_id=?""",
                (p["id"],),
            ).fetchall()
            priced = [r for r in rayna_opt_rows if r["price"] is not None]
            unpriced = [r for r in rayna_opt_rows if r["price"] is None]
            bases = {r["pricing_basis"] for r in rayna_opt_rows}
            price_summary = RaynaPriceSummary(
                min_price=min((r["price"] for r in priced), default=None),
                max_price=max((r["price"] for r in priced), default=None),
                currency=priced[0]["currency"] if priced else None,
                priced_count=len(priced),
                unpriced_count=len(unpriced),
                pricing_basis=next(iter(bases)) if len(bases) == 1 else None,
            )

            stats.append(
                DashboardStat(
                    product=Product(**p),
                    option_count=option_count,
                    seller_count=seller_count,
                    comparable_count=len(comparable_rows),
                    rayna_price=price_summary,
                    cheapest_competitor=cheapest,
                )
            )

        return DashboardPayload(pipeline=pipeline, products=stats)


@app.get("/api/products/{product_id}/comparison", response_model=ProductComparison)
def product_comparison(product_id: int) -> ProductComparison:
    with conn() as c:
        p = c.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not p:
            raise HTTPException(status_code=404, detail="Product not found")

        rayna_options = c.execute(
            "SELECT * FROM options WHERE source='rayna' AND rayna_product_id=? ORDER BY id",
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
                   WHERE m.rayna_option_id=?
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
def review_queue() -> list[ReviewItem]:
    with conn() as c:
        rows = c.execute(
            """SELECT m.id AS mapping_id, m.verdict, m.confidence, m.diff_notes,
                      p.id AS product_id, p.name AS product_name,
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
               WHERE m.confidence < 0.7
                  OR (ro.pricing_basis != co.pricing_basis
                      AND ro.pricing_basis != 'unknown'
                      AND co.pricing_basis != 'unknown')
               ORDER BY m.confidence ASC""",
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
                 WHERE c2.rayna_product_id = p.id AND c2.sells_this_product = 1) AS seller_count,
              (SELECT COUNT(*) FROM mappings m
                 WHERE m.rayna_option_id = o.id AND m.is_manual = 1) AS mapped_count
            FROM options o
            JOIN products p ON p.id = o.rayna_product_id
            WHERE o.source = 'rayna'
            """
        )
        args: list[Any] = []
        if country:
            sql += " AND p.country = ?"
            args.append(country)
        if city:
            sql += " AND p.city = ?"
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
    ph = ",".join("?" * len(option_ids))
    rows = c.execute(
        f"""
        SELECT po.option_id, po.price, po.currency
        FROM price_observations po
        WHERE po.target_date = ? AND po.option_id IN ({ph})
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
) -> ProductMappingPayload:
    """Everything the mapping split-view needs for one Rayna product.

    When ``date=YYYY-MM-DD`` is passed, per-option prices are substituted from
    the ``price_observations`` table (Rayna's date_price[] and Headout's
    per-slot inventory, ingested nightly). Options with no observation for
    that date fall back to the default price and are marked
    ``date_price_source='default'``.
    """
    with conn() as c:
        p = c.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not p:
            raise HTTPException(status_code=404, detail="Product not found")

        rayna_opts = c.execute(
            "SELECT * FROM options WHERE source='rayna' AND rayna_product_id=? ORDER BY id",
            (product_id,),
        ).fetchall()

        # collect option ids we'll look up date-observations for
        rayna_ids = [ro["id"] for ro in rayna_opts]
        comp_rows_pre = c.execute(
            """SELECT o.id FROM options o
               JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
               JOIN competitors cc ON cc.id = cl.competitor_id
               WHERE o.source='competitor' AND cc.rayna_product_id=?""",
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
                      o.fingerprint_json, c.seller_domain, cl.id AS listing_id,
                      cl.listing_url,
                      m.id AS mapping_id, m.rayna_option_id, m.is_manual
               FROM options o
               JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
               JOIN competitors c ON c.id = cl.competitor_id
               LEFT JOIN mappings m ON m.competitor_option_id = o.id AND m.is_manual = 1
               WHERE o.source='competitor' AND c.rayna_product_id=?
               ORDER BY c.seller_domain, cl.id, o.id""",
            (product_id,),
        ).fetchall()

        # group by seller_domain
        sellers_dict: dict[str, dict[str, Any]] = {}
        for r in rows:
            sd = r["seller_domain"]
            if sd not in sellers_dict:
                sellers_dict[sd] = {"listing_ids": set(), "options": []}

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
def create_manual_mapping(req: ManualMapRequest) -> ManualMapResponse:
    with conn() as c:
        # sanity: both options must exist and have the right sources
        rayna = c.execute(
            "SELECT id, source, rayna_product_id FROM options WHERE id=?",
            (req.rayna_option_id,),
        ).fetchone()
        comp = c.execute(
            """SELECT o.id, o.source, c.rayna_product_id
               FROM options o
               JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
               JOIN competitors c ON c.id = cl.competitor_id
               WHERE o.id=?""",
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
               WHERE m.rayna_option_id = ?
                 AND m.competitor_option_id != ?
                 AND c2.seller_domain = (
                   SELECT c3.seller_domain
                   FROM options o3
                   JOIN competitor_listings cl3 ON cl3.id = o3.competitor_listing_id
                   JOIN competitors c3 ON c3.id = cl3.competitor_id
                   WHERE o3.id = ?
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
               WHERE competitor_option_id=? AND is_manual=1
                 AND rayna_option_id != ?""",
            (req.competitor_option_id, req.rayna_option_id),
        )

        # 2. Look for an existing row on the unique (rayna_option_id, competitor_option_id)
        #    key. If it exists (Claude-generated or already manual), upgrade/refresh it
        #    rather than INSERT (which would violate the UNIQUE constraint).
        existing = c.execute(
            """SELECT id FROM mappings
               WHERE rayna_option_id=? AND competitor_option_id=?""",
            (req.rayna_option_id, req.competitor_option_id),
        ).fetchone()

        if existing:
            c.execute(
                """UPDATE mappings
                   SET verdict='identical', confidence=1.0,
                       diff_notes='Manually mapped by reviewer', judge_model='manual',
                       human_reviewed=1, human_verdict='identical', is_manual=1,
                       created_at=?
                   WHERE id=?""",
                (now, existing["id"]),
            )
            mapping_id = existing["id"]
        else:
            cur = c.execute(
                """INSERT INTO mappings
                     (rayna_option_id, competitor_option_id, verdict, confidence,
                      diff_notes, judge_model, human_reviewed, human_verdict,
                      is_manual, created_at)
                   VALUES (?, ?, 'identical', 1.0, 'Manually mapped by reviewer',
                           'manual', 1, 'identical', 1, ?)""",
                (req.rayna_option_id, req.competitor_option_id, now),
            )
            mapping_id = cur.lastrowid
        c.commit()

        return ManualMapResponse(
            mapping_id=mapping_id,
            rayna_option_id=req.rayna_option_id,
            competitor_option_id=req.competitor_option_id,
            created_at=now,
        )


@app.post("/api/mappings/from-url", response_model=AddByUrlResponse, status_code=201)
def create_mapping_from_url(req: AddByUrlRequest) -> AddByUrlResponse:
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

    from src import add_by_url, config

    with conn() as c:
        # 1. Validate Rayna option + get its anchor product
        rayna = c.execute(
            """SELECT o.id, o.name, o.pricing_basis, o.price, o.currency,
                      o.fingerprint_json, o.rayna_product_id,
                      p.name AS anchor_name, p.city AS anchor_city,
                      p.type AS anchor_type, p.market
               FROM options o
               JOIN products p ON o.rayna_product_id = p.id
               WHERE o.id=? AND o.source='rayna'""",
            (req.rayna_option_id,),
        ).fetchone()
        if not rayna:
            raise HTTPException(status_code=404, detail="Rayna option not found")

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
               WHERE m.rayna_option_id = ? AND c2.seller_domain = ?""",
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

    # 5. Claude extraction + adjudication (network + $)
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    try:
        extracted = add_by_url.extract_competitor_option(
            client, content, req.url, page_title,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Extraction failed: {type(e).__name__}: {e}",
        ) from e

    # Shape rayna_opt + competitor_opt like the adjudicator expects.
    rayna_opt_dict = {
        "name": rayna["name"],
        "price": rayna["price"],
        "currency": rayna["currency"],
        "pricing_basis": rayna["pricing_basis"] or "unknown",
        "fingerprint_json": rayna["fingerprint_json"] or "{}",
    }
    competitor_opt_dict = {
        "name": extracted.name,
        "price": extracted.price,
        "currency": extracted.currency,
        "pricing_basis": extracted.fingerprint.pricing_basis or "unknown",
        "fingerprint_json": extracted.fingerprint.model_dump_json(),
    }
    anchor_product = {
        "name": rayna["anchor_name"],
        "city": rayna["anchor_city"],
        "type": rayna["anchor_type"],
    }

    try:
        verdict, _usage, judge_model = add_by_url.adjudicate_pair(
            client,
            rayna_opt_dict,
            competitor_opt_dict,
            anchor_product,
            seller_domain,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Adjudication failed: {type(e).__name__}: {e}",
        ) from e

    # 6. Decide save-mapping vs save-competitor-only.
    #    Rule: save the mapping if verdict is identical/near, OR if verdict is
    #    'different' but confidence is low (< 0.6) — the model isn't sure, so
    #    let the human decide.
    should_save_mapping = verdict.verdict in ("identical", "near") or (
        verdict.verdict == "different" and verdict.confidence < 0.6
    )

    # 7. Persist competitors + listing + option + (optional) mapping.
    now = datetime.now(timezone.utc).isoformat()
    diff_prefix = f"[Manual URL paste] {req.note.strip()} — " if req.note else "[Manual URL paste] "

    with conn() as c:
        # 7a. Upsert competitor row
        comp_row = c.execute(
            """SELECT id FROM competitors
               WHERE rayna_product_id=? AND market=? AND seller_domain=?""",
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
                     classified_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, 'sells_this_product', 1.0,
                           'Manually added via URL paste', ?)""",
                (
                    rayna["rayna_product_id"], rayna["market"], seller_domain,
                    seller_domain, req.url, now, now,
                ),
            )
            competitor_id = cur.lastrowid

        # 7b. Insert competitor_listings row (always fresh — one row per paste)
        cur = c.execute(
            """INSERT INTO competitor_listings
                (competitor_id, listing_url, title, raw_markdown,
                 raw_html, scraped_at, scrape_method)
               VALUES (?, ?, ?, ?, NULL, ?, 'manual_url')""",
            (
                competitor_id, req.url, page_title or extracted.name,
                content[:200000],  # cap at 200KB to be safe
                now,
            ),
        )
        listing_id = cur.lastrowid

        # 7c. Insert options row
        cur = c.execute(
            """INSERT INTO options
                (source, competitor_listing_id, name, pricing_basis,
                 price, currency, market, fingerprint_json,
                 raw_extracted_json, extraction_model, extracted_at)
               VALUES ('competitor', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                listing_id,
                extracted.name,
                extracted.fingerprint.pricing_basis or "unknown",
                extracted.price,
                extracted.currency,
                rayna["market"],
                extracted.fingerprint.model_dump_json(),
                extracted.model_dump_json(),
                "manual-url",
                now,
            ),
        )
        competitor_option_id = cur.lastrowid

        # 7d. Insert mapping if the verdict permits it
        mapping_id: Optional[int] = None
        if should_save_mapping:
            cur = c.execute(
                """INSERT INTO mappings
                    (rayna_option_id, competitor_option_id, verdict, confidence,
                     diff_notes, judge_model, human_reviewed, human_verdict,
                     is_manual, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 0, NULL, 1, ?)""",
                (
                    req.rayna_option_id, competitor_option_id,
                    verdict.verdict, verdict.confidence,
                    diff_prefix + verdict.diff_notes, judge_model,
                    now,
                ),
            )
            mapping_id = cur.lastrowid

        c.commit()

    return AddByUrlResponse(
        mapping_id=mapping_id,
        rayna_option_id=req.rayna_option_id,
        competitor_option_id=competitor_option_id,
        seller_domain=seller_domain,
        listing_url=req.url,
        verdict=verdict.verdict,
        confidence=verdict.confidence,
        diff_notes=verdict.diff_notes,
        saved_mapping=should_save_mapping,
        competitor_name=extracted.name,
        competitor_price=extracted.price,
        competitor_currency=extracted.currency,
        competitor_pricing_basis=extracted.fingerprint.pricing_basis or "unknown",
    )


@app.delete("/api/mappings/{mapping_id}", status_code=204)
def delete_mapping(mapping_id: int):
    with conn() as c:
        row = c.execute("SELECT is_manual FROM mappings WHERE id=?", (mapping_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Mapping not found")
        if row["is_manual"] != 1:
            raise HTTPException(
                status_code=403,
                detail="Refusing to delete an automated (Claude) mapping; only is_manual=1 rows can be deleted via this endpoint.",
            )
        c.execute("DELETE FROM mappings WHERE id=?", (mapping_id,))
        c.commit()
        return None


@app.get("/api/mapped", response_model=list[MappedItem])
def mapped_list(date: Optional[str] = None) -> list[MappedItem]:
    """List all manual mappings. When ``date=YYYY-MM-DD`` is passed, both
    Rayna and competitor prices are swapped with the most recent
    ``price_observations`` entry for that date. Options without an
    observation fall back to the default price (marked ``…_date_price_source
    ='default'``)."""
    with conn() as c:
        rows = c.execute(
            """SELECT m.id AS mapping_id, m.created_at,
                      p.id AS product_id, p.name AS product_name,
                      ro.id AS rayna_option_id, ro.name AS rayna_option_name,
                      ro.price AS rayna_price, ro.currency AS rayna_currency,
                      ro.pricing_basis AS rayna_basis,
                      co.id AS competitor_option_id, co.name AS competitor_option_name,
                      co.price AS competitor_price, co.currency AS competitor_currency,
                      co.pricing_basis AS competitor_basis,
                      c.seller_domain, cl.listing_url
               FROM mappings m
               JOIN options ro ON ro.id = m.rayna_option_id
               JOIN options co ON co.id = m.competitor_option_id
               JOIN products p ON p.id = ro.rayna_product_id
               JOIN competitor_listings cl ON cl.id = co.competitor_listing_id
               JOIN competitors c ON c.id = cl.competitor_id
               WHERE m.is_manual = 1
               ORDER BY m.created_at DESC"""
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
