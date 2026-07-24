"""Classify discovered competitor domains: real_seller / ota_aggregator / noise.

Brief's Idea 3 (second half): not every search result is a real competitor.
Review sites, blogs, official-info pages, and unrelated noise need to be
filtered out before we burn scraping budget on them.

Cheap first-pass with Haiku (one tool-use call per candidate). The system
prompt is cached so the marginal cost per candidate is tiny.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from anthropic import Anthropic
from pydantic import BaseModel, Field

from src import config, db

Category = Literal[
    "real_seller",
    "ota_aggregator",
    "operator_directory",
    "review_site",
    "blog_or_news",
    "noise",
]


class CompetitorClassification(BaseModel):
    category: Category
    sells_this_product: bool = Field(
        description="True if a customer can actually buy this exact product on this site today."
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(description="One short sentence (max ~25 words).")


SYSTEM_PROMPT = """You classify search-result websites for a tour/attraction price comparison system.

For each candidate, decide whether it sells the given Rayna product to customers TODAY.

CATEGORIES:
- real_seller: the operator's own site, or a specific direct seller of this exact product. Customer can book on this site.
- ota_aggregator: a multi-vendor tour booking platform (Viator, GetYourGuide, Klook, Headout, Tiqets, Tripadvisor Experiences, Civitatis, Musement, Headout, etc.). These ARE real competitors — they sell the product.
- operator_directory: lists or compares operators but doesn't sell directly (e.g. UAE government tourism portals when they only link out).
- review_site: review-only listings (e.g. TripAdvisor "Things to Do" review pages without booking integration), Yelp.
- blog_or_news: editorial articles, travel blogs, news coverage. No booking.
- noise: completely unrelated to the product.

sells_this_product MUST be true ONLY for `real_seller` and `ota_aggregator`. False for everything else.

Be decisive but honest. If genuinely unsure between two categories, pick the more conservative (less-likely-seller) one and lower confidence below 0.7.

Use the URL pattern (especially path segments like /book, /tour, /e-, /experience), the title, and the snippet to judge. Output ONLY via the `classify` tool.
"""

USER_TEMPLATE = """RAYNA PRODUCT: {product_name}
TYPE: {product_type} in {city}

CANDIDATE:
  Domain:  {domain}
  URL:     {url}
  Title:   {title}
  Snippet: {snippet}

Classify."""


def build_tools():
    return [
        {
            "name": "classify",
            "description": "Record the classification of this candidate.",
            "input_schema": CompetitorClassification.model_json_schema(),
        }
    ]


def classify_one(client: Anthropic, product, competitor, tools):
    resp = client.messages.create(
        model=config.CLAUDE_CLASSIFIER_MODEL,
        max_tokens=300,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=tools,
        tool_choice={"type": "tool", "name": "classify"},
        messages=[
            {
                "role": "user",
                "content": USER_TEMPLATE.format(
                    product_name=product["name"],
                    product_type=product["type"] or "activities",
                    city=product["city"] or "Dubai",
                    domain=competitor["seller_domain"],
                    url=competitor["seed_url"] or f"https://{competitor['seller_domain']}/",
                    title=competitor["seller_name"] or "(no title)",
                    snippet=competitor["snippet"] or "(no snippet)",
                ),
            }
        ],
    )
    tool_blocks = [b for b in resp.content if b.type == "tool_use" and b.name == "classify"]
    if not tool_blocks:
        raise RuntimeError(f"No tool call returned for competitor {competitor['id']}")
    parsed = CompetitorClassification.model_validate(tool_blocks[0].input)
    return parsed, resp.usage


def run() -> None:
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    db.init_db()
    tools = build_tools()
    now = datetime.now(timezone.utc).isoformat()

    conn = db.get_conn()
    products_by_id = {p["id"]: dict(p) for p in conn.execute("SELECT * FROM products")}
    pending = list(
        conn.execute(
            "SELECT * FROM competitors WHERE classified_as IS NULL ORDER BY rayna_product_id, search_rank"
        )
    )
    conn.close()

    print(f"Classifying {len(pending)} competitors with {config.CLAUDE_CLASSIFIER_MODEL}\n")

    totals = {"input": 0, "cache_read": 0, "cache_create": 0, "output": 0}
    by_category: dict[str, int] = {}

    for c in pending:
        product = products_by_id.get(c["rayna_product_id"])
        if not product:
            continue
        try:
            parsed, usage = classify_one(client, product, c, tools)
        except Exception as e:
            print(f"  ! [{c['seller_domain']}] failed: {e}")
            continue

        with db.tx() as conn:
            conn.execute(
                """
                UPDATE competitors
                SET classified_as=?, classifier_confidence=?, classifier_reason=?,
                    sells_this_product=?, classified_at=?
                WHERE id=?
                """,
                (
                    parsed.category,
                    parsed.confidence,
                    parsed.reason,
                    1 if parsed.sells_this_product else 0,
                    now,
                    c["id"],
                ),
            )

        totals["input"] += usage.input_tokens
        totals["output"] += usage.output_tokens
        totals["cache_create"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
        totals["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0
        by_category[parsed.category] = by_category.get(parsed.category, 0) + 1

        flag = "✓" if parsed.sells_this_product else "·"
        print(
            f"  {flag} [{c['seller_domain'][:32]:<32}] → {parsed.category:<18} "
            f"conf={parsed.confidence:.2f}  {parsed.reason[:80]}"
        )

    print(
        f"\nDone. By category: {dict(sorted(by_category.items()))}\n"
        f"Tokens — input:{totals['input']} cache_create:{totals['cache_create']} "
        f"cache_read:{totals['cache_read']} output:{totals['output']}"
    )

    conn = db.get_conn()
    print("\nSummary — sellers worth scraping per product:")
    for pid, p in products_by_id.items():
        rows = list(
            conn.execute(
                "SELECT seller_domain, classified_as, classifier_confidence, search_rank "
                "FROM competitors WHERE rayna_product_id=? AND sells_this_product=1 "
                "ORDER BY search_rank",
                (pid,),
            )
        )
        print(f"\n  [{pid}] {p['name']}  ({len(rows)} sellers)")
        for r in rows[:10]:
            print(
                f"    rank={r['search_rank']:>2}  {r['seller_domain']:<35} "
                f"({r['classified_as']}, conf={r['classifier_confidence']:.2f})"
            )
    conn.close()


if __name__ == "__main__":
    run()
