"""Extract structured options from scraped competitor PDPs.

Same fingerprint schema as Rayna extraction (brief's Idea 2 — match on structured
fields), but the input is Firecrawl markdown rather than feed fields, and the
extraction is anchored to a specific Rayna product so we only pull comparable
options off the page (some scraped pages are aggregator listings with 20 tours).

Idempotent: re-running clears prior competitor-option rows for each listing.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from anthropic import Anthropic

from src import config, db
from src.models import ExtractionResult

MAX_MARKDOWN_CHARS = 30_000  # ~7K tokens; PDPs are usually under this above-the-fold
PARALLEL_WORKERS = 6

_db_lock = threading.Lock()

SYSTEM_PROMPT = """You are an expert in tours and attractions pricing.

You will be given scraped markdown from a competitor's webpage along with the \
Rayna product we are trying to compare against. Your job: extract structured \
bookable OPTIONS on the competitor's page that are plausibly comparable to the \
Rayna product — NOT every tour on the page.

"PLAUSIBLY COMPARABLE" means similar activity type and venue/operator scope. \
Use a wide net here — fine-grained matching (identical / near / different) is a \
SEPARATE step done by a different model later. Your job is recall at this stage.

If the page describes ONE product with multiple variants (e.g. with/without \
transfer, prime/non-prime, durations), extract every variant.

If the page is an AGGREGATOR listing with many distinct tours, extract only the \
2-5 most comparable to the anchor product. Skip the rest.

If NOTHING on the page is plausibly comparable, return an empty options list and \
say so in extraction_notes.

PRICE CAPTURE — critical:
- Capture the price exactly as shown on the page, in the currency shown.
- Prefer the price a customer would see at the availability check, not a marketing \
"from" price. If only a "from" price is visible, capture it and say so in notes.
- pricing_basis: per_adult is most common. Set per_boat/per_yacht/per_vehicle/\
private_group when the page makes it clear the price is for the whole vessel/group.
- If unclear, set pricing_basis="unknown" — do NOT guess.

NEVER invent options or prices. Quote evidence in source_evidence (short direct \
quote from the markdown, ideally the line containing the price or variant name).

Output ONLY via the `record_options` tool. The markdown may have noisy nav/cookie/\
footer text — focus on the actual product offerings.
"""

USER_TEMPLATE = """COMPETITOR PAGE
  URL: {url}
  Domain: {domain}
  Page title: {title}

RAYNA ANCHOR PRODUCT (we're comparing against this):
  Name: {anchor_name}
  Type: {anchor_type}
  City: {anchor_city}
  Rayna's own description (for context only — do NOT just copy our options): \
{anchor_summary}

PAGE MARKDOWN (truncated at {max_chars} chars):

{markdown}
"""


def build_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "record_options",
            "description": "Record the bookable options on this competitor page that are plausibly comparable to the Rayna anchor product.",
            "input_schema": ExtractionResult.model_json_schema(),
        }
    ]


def extract_for_listing(client: Anthropic, listing, anchor_product, tools, anchor_summary: str):
    md = (listing["raw_markdown"] or "")[:MAX_MARKDOWN_CHARS]
    if len(md) < 200:
        return None, None  # skipped

    user_text = USER_TEMPLATE.format(
        url=listing["listing_url"],
        domain=listing["seller_domain"],
        title=listing["title"] or "(no title)",
        anchor_name=anchor_product["name"],
        anchor_type=anchor_product["type"] or "activities",
        anchor_city=anchor_product["city"] or "Dubai",
        anchor_summary=anchor_summary[:1500],
        max_chars=MAX_MARKDOWN_CHARS,
        markdown=md,
    )

    resp = client.messages.create(
        model=config.CLAUDE_ADJUDICATOR_MODEL,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=tools,
        tool_choice={"type": "tool", "name": "record_options"},
        messages=[{"role": "user", "content": user_text}],
    )

    tool_blocks = [b for b in resp.content if b.type == "tool_use" and b.name == "record_options"]
    if not tool_blocks:
        raise RuntimeError(
            f"No record_options call for listing {listing['id']}; stop={resp.stop_reason}"
        )

    parsed = ExtractionResult.model_validate(tool_blocks[0].input)
    usage = resp.usage
    meta = {
        "model": resp.model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    return parsed, meta


def save_options(parsed: ExtractionResult, listing, model_id: str, market: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _db_lock, db.tx() as conn:
        # FK: drop mappings that reference options we're about to delete
        conn.execute(
            """DELETE FROM mappings
               WHERE competitor_option_id IN (
                 SELECT id FROM options
                 WHERE source='competitor' AND competitor_listing_id=?
               )""",
            (listing["id"],),
        )
        conn.execute(
            "DELETE FROM options WHERE source='competitor' AND competitor_listing_id=?",
            (listing["id"],),
        )
        for opt in parsed.options:
            conn.execute(
                """
                INSERT INTO options (
                    source, competitor_listing_id, name, pricing_basis, price, currency,
                    market, fingerprint_json, raw_extracted_json, extraction_model, extracted_at
                ) VALUES ('competitor', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    listing["id"],
                    opt.name,
                    opt.fingerprint.pricing_basis,
                    opt.price,
                    opt.currency,
                    market,
                    opt.fingerprint.model_dump_json(),
                    opt.model_dump_json(),
                    model_id,
                    now,
                ),
            )


def _already_extracted(listing_id: int) -> bool:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM options WHERE source='competitor' AND competitor_listing_id=? LIMIT 1",
            (listing_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _process_one(client, lst, anchor_product, tools, anchor_summary, market):
    try:
        parsed, meta = extract_for_listing(client, lst, anchor_product, tools, anchor_summary)
    except Exception as e:
        return lst, None, None, f"{type(e).__name__}: {e}"
    if parsed is None:
        return lst, None, None, "markdown too short"
    save_options(parsed, lst, meta["model"], market)
    return lst, parsed, meta, None


def run() -> None:
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    db.init_db()
    tools = build_tools()

    conn = db.get_conn()

    anchor_summaries: dict[int, str] = {}
    for r in conn.execute(
        """SELECT rayna_product_id, name FROM options
           WHERE source='rayna' ORDER BY rayna_product_id, id"""
    ):
        if r["rayna_product_id"] not in anchor_summaries:
            anchor_summaries[r["rayna_product_id"]] = r["name"]

    listings = list(
        conn.execute(
            """SELECT cl.id, cl.competitor_id, cl.listing_url, cl.title, cl.raw_markdown,
                      c.rayna_product_id, c.seller_domain,
                      p.name AS rayna_product_name, p.type AS rayna_product_type,
                      p.city AS rayna_product_city, p.market AS rayna_market
               FROM competitor_listings cl
               JOIN competitors c ON c.id = cl.competitor_id
               JOIN products p ON p.id = c.rayna_product_id
               WHERE cl.raw_markdown IS NOT NULL AND length(cl.raw_markdown) > 200
               ORDER BY c.rayna_product_id, c.search_rank"""
        )
    )
    conn.close()

    pending = [l for l in listings if not _already_extracted(l["id"])]
    skipped = len(listings) - len(pending)
    print(
        f"Extracting options from {len(pending)} competitor listing(s) "
        f"({skipped} already extracted, skipped) using {PARALLEL_WORKERS} workers\n"
    )

    totals = {"input": 0, "cache_read": 0, "cache_create": 0, "output": 0}
    done = 0

    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
        futures = []
        for lst in pending:
            anchor_product = {
                "id": lst["rayna_product_id"],
                "name": lst["rayna_product_name"],
                "type": lst["rayna_product_type"],
                "city": lst["rayna_product_city"],
            }
            anchor_summary = anchor_summaries.get(lst["rayna_product_id"], lst["rayna_product_name"])
            futures.append(
                pool.submit(
                    _process_one, client, lst, anchor_product, tools, anchor_summary, lst["rayna_market"]
                )
            )

        for fut in as_completed(futures):
            lst, parsed, meta, err = fut.result()
            done += 1
            if err:
                print(f"  [{done}/{len(pending)}] ! {lst['seller_domain']:<28}  {err}")
                continue
            totals["input"] += meta["input_tokens"]
            totals["output"] += meta["output_tokens"]
            totals["cache_create"] += meta["cache_creation_input_tokens"]
            totals["cache_read"] += meta["cache_read_input_tokens"]
            print(
                f"  [{done}/{len(pending)}] ✓ {lst['seller_domain']:<28}  "
                f"{len(parsed.options)} options"
            )

    print(
        f"\nTokens — input:{totals['input']}  cache_create:{totals['cache_create']}  "
        f"cache_read:{totals['cache_read']}  output:{totals['output']}"
    )


if __name__ == "__main__":
    run()
