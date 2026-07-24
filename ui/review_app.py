"""Streamlit review UI: side-by-side fingerprint diff + price gap per Rayna option.

Two tabs:
  1. Comparison — for a chosen Rayna product, all matched competitor options
     grouped by Rayna option, with verdict, confidence, diff_notes, and price gap.
  2. Review queue — mappings flagged for human review (confidence < 0.7 or
     pricing_basis_mismatch). This is the brief's human checkpoint.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# Make `src` importable when launched via `streamlit run ui/review_app.py`
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from src import config


st.set_page_config(
    page_title="Rayna Market Intelligence — PoC",
    layout="wide",
    initial_sidebar_state="expanded",
)


# -------- data access --------


@st.cache_resource
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_products(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM products ORDER BY id")]


def fetch_rayna_options(conn, product_id: int) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM options WHERE source='rayna' AND rayna_product_id=? ORDER BY id",
            (product_id,),
        )
    ]


def fetch_mappings_for_rayna_option(conn, rayna_option_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT m.*, o.name AS competitor_option_name, o.price AS competitor_price,
               o.currency AS competitor_currency, o.pricing_basis AS competitor_basis,
               o.fingerprint_json AS competitor_fp, c.seller_domain
        FROM mappings m
        JOIN options o ON o.id = m.competitor_option_id
        JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
        JOIN competitors c ON c.id = cl.competitor_id
        WHERE m.rayna_option_id=?
        ORDER BY
          CASE m.verdict WHEN 'identical' THEN 0 WHEN 'near' THEN 1 ELSE 2 END,
          m.confidence DESC
        """,
        (rayna_option_id,),
    )
    return [dict(r) for r in rows]


def fetch_review_queue(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT m.*, p.name AS product_name, p.id AS product_id,
               ro.name AS rayna_option_name, ro.price AS rayna_price, ro.currency AS rayna_currency,
               ro.pricing_basis AS rayna_basis,
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
           OR (ro.pricing_basis != co.pricing_basis AND ro.pricing_basis != 'unknown' AND co.pricing_basis != 'unknown')
           OR m.human_reviewed = 0
        ORDER BY m.confidence ASC
        """
    )
    return [dict(r) for r in rows]


# -------- rendering helpers --------


VERDICT_BADGE = {
    "identical": ("✓ identical", "#1f7a3b"),
    "near": ("≈ near", "#a76800"),
    "different": ("✗ different", "#8a1f1f"),
}


def render_verdict(verdict: str, confidence: float, basis_mismatch: bool) -> str:
    label, color = VERDICT_BADGE.get(verdict, (verdict, "#444"))
    review = " ◆ review" if confidence < 0.7 else ""
    basis = " ⚠ basis-mismatch" if basis_mismatch else ""
    return (
        f"<span style='background:{color};color:white;padding:2px 8px;"
        f"border-radius:4px;font-size:0.85em'>{label} ({confidence:.2f}){review}{basis}</span>"
    )


def render_price_gap(rayna_price, rayna_currency, comp_price, comp_currency):
    if rayna_price is None or comp_price is None:
        return "—"
    if rayna_currency != comp_currency:
        return f"R: {rayna_price} {rayna_currency}  vs  C: {comp_price} {comp_currency} (mixed currencies)"
    diff = comp_price - rayna_price
    pct = (diff / rayna_price * 100) if rayna_price else 0
    if diff < 0:
        color = "#8a1f1f"
        sign = ""
    else:
        color = "#1f7a3b"
        sign = "+"
    return (
        f"R: {rayna_price} {rayna_currency}  |  C: {comp_price} {comp_currency}  "
        f"<span style='color:{color};font-weight:600'>(gap {sign}{diff:.0f}, {pct:+.1f}%)</span>"
    )


def render_fingerprint(fp_json: str) -> dict:
    fp = json.loads(fp_json)
    return {k: v for k, v in fp.items() if v not in (None, "", [], {})}


def fp_side_by_side(rayna_fp: dict, comp_fp: dict) -> pd.DataFrame:
    keys = sorted(set(rayna_fp) | set(comp_fp))

    def fmt(v):
        if isinstance(v, list):
            return ", ".join(map(str, v))
        return v if v is not None else "—"

    return pd.DataFrame(
        [(k, fmt(rayna_fp.get(k)), fmt(comp_fp.get(k))) for k in keys],
        columns=["field", "Rayna", "competitor"],
    )


# -------- app --------


def main():
    conn = get_conn()
    products = fetch_products(conn)

    st.title("Rayna Market Intelligence — PoC")
    st.caption(
        f"{config.PILOT_MARKET} pilot · {config.PILOT_CURRENCY} reference · "
        f"{len(products)} products · option-level comparison"
    )

    tab1, tab2 = st.tabs(["📊 Comparison", "🔍 Review queue"])

    # ---- TAB 1: COMPARISON ----
    with tab1:
        st.sidebar.header("Product")
        product_choice = st.sidebar.selectbox(
            "Choose Rayna product",
            options=[p["id"] for p in products],
            format_func=lambda pid: f"{pid} — {next(p['name'] for p in products if p['id']==pid)}",
        )
        product = next(p for p in products if p["id"] == product_choice)

        st.subheader(product["name"])
        st.caption(
            f"{product['city']}, {product['country']} · {product['type']} · "
            f"{product['currency']} · market: {product['market']}"
        )
        st.markdown(f"[Open on raynatours.com →]({product['url']})")

        rayna_opts = fetch_rayna_options(conn, product_choice)
        if not rayna_opts:
            st.warning("No Rayna options extracted yet. Run `python -m src.extract_options`.")
            return

        st.markdown(f"**{len(rayna_opts)} Rayna option(s) for this product:**")

        for ropt in rayna_opts:
            with st.expander(
                f"🅁 {ropt['name']}  ·  "
                f"{ropt['price'] if ropt['price'] is not None else '(no price)'} "
                f"{ropt['currency'] or ''}  ·  {ropt['pricing_basis']}",
                expanded=True,
            ):
                rayna_fp = render_fingerprint(ropt["fingerprint_json"])

                mappings = fetch_mappings_for_rayna_option(conn, ropt["id"])
                if not mappings:
                    st.info("No competitor mappings yet. Run `python -m src.map_options`.")
                    st.markdown("**Rayna option fingerprint:**")
                    st.json(rayna_fp, expanded=False)
                    continue

                # Headline: cheapest like-for-like competitor
                # Filter price>0 to drop zeros that Claude sometimes extracts from
                # "free cancellation" / promo phrases. Also require same pricing_basis
                # so we don't compare per_adult vs per_boat as "cheapest".
                comparable = [
                    m for m in mappings
                    if m["verdict"] in ("identical", "near")
                    and m["competitor_price"] is not None
                    and m["competitor_price"] > 0
                    and m["competitor_basis"] == ropt["pricing_basis"]
                    and m["competitor_currency"] == ropt["currency"]
                ]
                if comparable and ropt["price"] is not None:
                    cheapest = min(comparable, key=lambda m: m["competitor_price"])
                    diff = cheapest["competitor_price"] - ropt["price"]
                    pct = diff / ropt["price"] * 100 if ropt["price"] else 0
                    if diff < 0:
                        st.error(
                            f"**We are {abs(pct):.1f}% higher than the cheapest competitor.** "
                            f"{cheapest['seller_domain']} → {cheapest['competitor_price']} {cheapest['competitor_currency']}  "
                            f"(Rayna: {ropt['price']} {ropt['currency']})"
                        )
                    else:
                        st.success(
                            f"**We are the cheapest like-for-like.** "
                            f"Next cheapest: {cheapest['seller_domain']} at {cheapest['competitor_price']} {cheapest['competitor_currency']} "
                            f"({pct:+.1f}%)"
                        )

                # Per-mapping cards
                for m in mappings:
                    if m["verdict"] == "different":
                        continue
                    comp_fp = render_fingerprint(m["competitor_fp"])
                    basis_mm = (
                        ropt["pricing_basis"] != m["competitor_basis"]
                        and "unknown" not in (ropt["pricing_basis"], m["competitor_basis"])
                    )

                    st.markdown(
                        f"**{m['seller_domain']}** · {m['competitor_option_name']}",
                        help=m["diff_notes"],
                    )
                    st.markdown(render_verdict(m["verdict"], m["confidence"], basis_mm), unsafe_allow_html=True)
                    st.markdown(
                        render_price_gap(
                            ropt["price"], ropt["currency"],
                            m["competitor_price"], m["competitor_currency"],
                        ),
                        unsafe_allow_html=True,
                    )
                    st.caption(f"💬 {m['diff_notes']}")

                    with st.expander("Fingerprint diff", expanded=False):
                        df = fp_side_by_side(rayna_fp, comp_fp)
                        st.dataframe(df, use_container_width=True, hide_index=True)
                    st.divider()

                # Different-verdict count (don't render details)
                n_diff = sum(1 for m in mappings if m["verdict"] == "different")
                if n_diff:
                    st.caption(f"({n_diff} competitor option(s) judged 'different' — not shown)")

    # ---- TAB 2: REVIEW QUEUE ----
    with tab2:
        st.subheader("Mappings flagged for human review")
        st.caption(
            "Brief's human checkpoint. Low confidence (<0.70), pricing-basis mismatches, "
            "and any unreviewed mapping shows here."
        )
        queue = fetch_review_queue(conn)
        st.caption(f"{len(queue)} item(s) need review")

        if not queue:
            st.info("Nothing in the queue yet. Run mapping first.")
            return

        rows = []
        for m in queue:
            basis_mm = (
                m["rayna_basis"] != m["competitor_basis"]
                and "unknown" not in (m["rayna_basis"], m["competitor_basis"])
            )
            rows.append({
                "product": m["product_name"],
                "rayna option": m["rayna_option_name"],
                "seller": m["seller_domain"],
                "competitor option": m["competitor_option_name"],
                "verdict": m["verdict"],
                "conf": round(m["confidence"], 2),
                "basis ⚠": "yes" if basis_mm else "",
                "Rayna price": f"{m['rayna_price']} {m['rayna_currency']}" if m["rayna_price"] else "—",
                "Comp price": f"{m['competitor_price']} {m['competitor_currency']}" if m["competitor_price"] else "—",
                "diff": m["diff_notes"],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=600)


if __name__ == "__main__":
    main()
