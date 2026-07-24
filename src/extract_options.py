"""Extract structured bookable options from Rayna product descriptions.

Brief's Idea 1: the unit of comparison is the option, not the product.
Brief's Idea 2: matching runs on structured fields, not on prose.

The Rayna catalog feed is product-level only — every option is implicit in the
description prose / amenities. This module asks Claude Sonnet (with prompt caching
on the system prompt + tool schema) to parse that prose into structured options.

The same module will be reused for competitor listings — we'll feed it scraped
Markdown instead of feed text, with a flag that switches the user template.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from anthropic import Anthropic

from src import config, db
from src.models import ExtractionResult

SYSTEM_PROMPT = """You are an expert in tours and attractions pricing.

Your job: read a product's description + amenities text, and extract every distinct \
bookable OPTION a customer would see when picking variants at booking — not the \
product as a whole.

An OPTION is a specific variant the customer selects at checkout. Examples:
- "Burj Khalifa Standard 124/125, non-prime time" vs "...prime time" vs "SKY 148 floor"
- "Desert Safari without transfer" vs "with shared transfer" vs "with private transfer"
- "Deep Sea Fishing 4-hour package" vs "6-hour" vs "8-hour"
- "City tour on SIC (shared) basis" vs "private vehicle"
- "Tour with quad biking add-on" vs "without"

RULES:

1. Extract every option you find CLEAR EVIDENCE for in the text. Quote that evidence \
in `source_evidence` (a short direct quote from the input).

2. If the text describes only one undifferentiated product with no variants mentioned, \
return a single option containing the product's basics.

3. NEVER invent options. If a typical product has prime/non-prime tiers but the text \
does not mention them, do NOT add them — flag in `extraction_notes` that variants \
likely exist but were not present in this text.

4. CRITICAL — determine the `pricing_basis` for each option:
   - `per_adult`: price is per single adult ticket. Most attraction tickets and SIC \
group tours. Default suspect for any SIC tour text.
   - `private_group`: price is for a whole private booking regardless of headcount.
   - `per_vehicle`: price is per vehicle (some private transfers, private safaris).
   - `per_boat` / `per_yacht`: price for full boat / yacht charter.
   - `unknown`: text is genuinely ambiguous — say so honestly.
   The brief mandates per_adult for cross-vendor comparison. If you set anything \
other than per_adult, also mention this in `extraction_notes`.

5. For `inclusions` and `exclusions`, extract discrete atomic items the text lists \
(e.g. "BBQ dinner", "camel ride", "hotel transfer", "quad biking"). Each item should \
be short (3-6 words) and self-contained.

6. `transfer_included`, `meal_included`, `meal_type`, `transfer_type` — infer ONLY \
from the text. Leave as null if not stated.

7. `duration_minutes`: convert ranges and labels to minutes when unambiguous \
(e.g. "08:30 am - 02:30 pm" → 360, "4 hours" → 240). Use `duration_label` for the \
original string when conversion is ambiguous (e.g. "as per selected time slot").

8. Output ONLY via the `record_options` tool. Do not write prose outside the tool call.

9. Keep `notes` and `extraction_notes` concise — flag exactly what is uncertain and why.
"""

USER_TEMPLATE = """PRODUCT: {name}
RAYNA PRODUCT ID: {product_id}
FEED LISTING PRICE: {price} {currency}
(this is the single price exposed in the feed; treat it as the starting reference, \
not necessarily per-adult — judge from the text)

LOCATION:
address: {location_address}
venue: {location_title}

AMENITIES (individual signals — do not merge into one line):
duration: {amenity_duration}
cancellation: {amenity_cancellation}
confirmation: {amenity_confirmation}
voucher: {amenity_voucher}

RAW AMENITIES (pipe-delimited catalog string, fallback):
{amenities}

DESCRIPTION:
{description}

Extract the bookable options. Use the `record_options` tool."""


def build_tools() -> list[dict[str, Any]]:
    schema = ExtractionResult.model_json_schema()
    return [
        {
            "name": "record_options",
            "description": "Record the bookable options extracted from this product. Required: one entry per distinct option supported by clear textual evidence.",
            "input_schema": schema,
        }
    ]


def extract_for_product(client: Anthropic, product_row, tools: list[dict[str, Any]]):
    raw = json.loads(product_row["raw_json"])

    user_text = USER_TEMPLATE.format(
        name=raw["name"],
        product_id=raw["productId"],
        price=raw.get("price_totalPrice"),
        currency=raw.get("price_currency") or raw.get("currency"),
        location_address=raw.get("location_address") or "(not stated)",
        location_title=raw.get("location_title") or "(not stated)",
        amenity_duration=raw.get("amenity_duration") or "(not stated)",
        amenity_cancellation=raw.get("amenity_cancellation") or "(not stated)",
        amenity_confirmation=raw.get("amenity_confirmation") or "(not stated)",
        amenity_voucher=raw.get("amenity_voucher") or "(not stated)",
        amenities=raw.get("amenities_all") or "(no amenities text)",
        description=raw.get("description_text") or "(no description text)",
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
            f"Claude did not call record_options for product {raw['productId']}; "
            f"stop_reason={resp.stop_reason}"
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


def save_options(parsed: ExtractionResult, product_row, model_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db.tx() as conn:
        # FK: drop everything that references the options we're about to delete
        # (mappings + per-date price observations), else FK constraint fires.
        conn.execute(
            """DELETE FROM mappings
               WHERE rayna_option_id IN (
                 SELECT id FROM options
                 WHERE source='rayna' AND rayna_product_id=?
               )""",
            (product_row["id"],),
        )
        conn.execute(
            """DELETE FROM price_observations
               WHERE option_id IN (
                 SELECT id FROM options
                 WHERE source='rayna' AND rayna_product_id=?
               )""",
            (product_row["id"],),
        )
        conn.execute(
            "DELETE FROM options WHERE source='rayna' AND rayna_product_id=?",
            (product_row["id"],),
        )
        for opt in parsed.options:
            conn.execute(
                """
                INSERT INTO options (
                    source, rayna_product_id, name, pricing_basis, price, currency,
                    market, fingerprint_json, raw_extracted_json, extraction_model, extracted_at
                ) VALUES ('rayna', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_row["id"],
                    opt.name,
                    opt.fingerprint.pricing_basis,
                    opt.price,
                    opt.currency or product_row["currency"],
                    product_row["market"],
                    opt.fingerprint.model_dump_json(),
                    opt.model_dump_json(),
                    model_id,
                    now,
                ),
            )


def run(
    product_ids: list[int] | None = None,
    city: str | None = None,
    country: str | None = None,
) -> None:
    """Extract Rayna options.

    WARNING: this DELETEs existing options + their mappings for each product
    it re-runs on. Pass ``product_ids`` / ``city`` / ``country`` to scope the
    re-extraction; otherwise all Rayna products are re-processed and all
    manual mappings under them are lost.
    """
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    db.init_db()
    tools = build_tools()

    conn = db.get_conn()
    where: list[str] = []
    params: list[Any] = []
    if product_ids:
        where.append("id IN (" + ",".join("?" * len(product_ids)) + ")")
        params.extend(product_ids)
    if city:
        where.append("city = ?")
        params.append(city)
    if country:
        where.append("country = ?")
        params.append(country)
    sql = "SELECT * FROM products"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id"
    products = list(conn.execute(sql, params))
    conn.close()

    totals = {"input": 0, "cache_create": 0, "cache_read": 0, "output": 0}

    for p in products:
        print(f"\n→ [{p['id']}] {p['name']}")
        try:
            parsed, meta = extract_for_product(client, p, tools)
        except Exception as e:
            print(f"  ! extraction failed: {e}")
            continue

        save_options(parsed, p, meta["model"])

        totals["input"] += meta["input_tokens"]
        totals["cache_create"] += meta["cache_creation_input_tokens"]
        totals["cache_read"] += meta["cache_read_input_tokens"]
        totals["output"] += meta["output_tokens"]

        print(f"  {len(parsed.options)} option(s):")
        for o in parsed.options:
            fp = o.fingerprint
            tags = [f"basis={fp.pricing_basis}"]
            if fp.transfer_included is not None:
                tags.append(f"transfer={'yes' if fp.transfer_included else 'no'}")
            if fp.meal_included is not None:
                tags.append(f"meal={'yes' if fp.meal_included else 'no'}")
            if fp.duration_label:
                tags.append(f"dur={fp.duration_label!r}")
            elif fp.duration_minutes:
                tags.append(f"dur={fp.duration_minutes}m")
            if fp.tier:
                tags.append(f"tier={fp.tier}")
            price_str = f"{o.price} {o.currency}" if o.price is not None else "(no price)"
            print(f"    • {o.name}  —  {price_str}  [{' '.join(tags)}]")
        if parsed.extraction_notes:
            print(f"  notes: {parsed.extraction_notes}")

    print(
        f"\nTokens — input:{totals['input']}  "
        f"cache_create:{totals['cache_create']}  "
        f"cache_read:{totals['cache_read']}  "
        f"output:{totals['output']}"
    )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--rayna-product-id",
        type=int,
        action="append",
        default=[],
        help="Restrict re-extraction to these product IDs. Repeatable. "
        "Omit to re-run all products (drops existing mappings — read the "
        "docstring on save_options).",
    )
    p.add_argument("--city", default=None, help="Restrict by product city.")
    p.add_argument("--country", default=None, help="Restrict by product country.")
    args = p.parse_args()
    run(
        product_ids=args.rayna_product_id or None,
        city=args.city,
        country=args.country,
    )
