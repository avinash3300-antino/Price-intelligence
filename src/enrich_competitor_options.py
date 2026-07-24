"""Enrich competitor options' fingerprint_json from persisted raw API JSON.

The Headout / GlobalTix ingest scripts now stash the full API response in
``competitor_listings.raw_markdown`` (product-level) and
``options.raw_extracted_json`` (variant / per-option level).

This module reads that raw JSON per competitor option and asks Claude Sonnet
to fit it to :class:`OptionFingerprint` — filling in inclusions, exclusions,
highlights, duration, transfer / meal flags, cancellation, languages, etc.

It only UPDATES ``fingerprint_json`` and ``extraction_model`` on existing
option rows. It never inserts, deletes, or touches mappings — safe to re-run
and safe to run partway through a session.

Usage
-----

    # pilot: one product's competitors
    python -m src.enrich_competitor_options --rayna-product-id 5966

    # a few products at a time
    python -m src.enrich_competitor_options --rayna-product-id 5966 --rayna-product-id 18

    # everything
    python -m src.enrich_competitor_options --all

    # limit for cost control
    python -m src.enrich_competitor_options --all --limit 20

Skips options that already have a rich fingerprint unless ``--force`` is passed.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from anthropic import Anthropic

from src import config, db
from src.models import OptionFingerprint

SYSTEM_PROMPT = """You are an expert in tours and attractions data.

Your job: read a JSON blob from a competitor's product/variant API response \
and fit its content to the OptionFingerprint schema. Ignore anything you \
can't confidently map.

RULES:

1. Read every string field carefully. Field names vary between vendors and \
change over time — you may see "description", "shortDescription", "summary", \
"htmlDescription", "highlights", "keyDetails", "whatsInBox", "inclusions", \
"exclusions", "cancellationPolicy", "duration", "durationText", "categories", \
"languages", "capacity", etc. Extract the meaning, not the field name.

2. `highlights` — short marketing bullets (e.g. "Skip the line", "Sunset views"). \
Distinct from inclusions.

3. `inclusions` — atomic items included in the price (e.g. "BBQ dinner", \
"hotel transfer", "guide"). Short, 3–6 words each. Do NOT include highlights.

4. `exclusions` — atomic items explicitly excluded (e.g. "gratuities", \
"personal expenses").

5. `duration_minutes` — convert cleanly-numeric durations to minutes \
("2 hours" → 120, "PT4H30M" → 270, "half day" → use duration_label instead).

6. `cancellation_window_hours` — e.g. "Free cancellation up to 24 hours prior" \
→ 24. If the policy is "non-refundable" or "no cancellation", leave the \
window null but note in `notes`.

7. `transfer_included` / `meal_included` — only set true/false if the text \
is explicit. Never guess.

8. `pricing_basis` — leave whatever the caller-provided fingerprint already \
has unless the raw JSON is clearly contradictory.

9. `venue` — if a specific anchor venue name appears (e.g. "Burj Khalifa", \
"Aquaventure Waterpark"), fill it. For operator-led tours without a venue, \
leave null.

10. `notes` — free text for anything material you noticed but couldn't fit \
elsewhere. Keep it short (1–2 sentences).

11. If the JSON is extremely thin (e.g. only variant name + price), populate \
what you can and leave everything else empty. Don't invent.

12. Output ONLY via the `record_fingerprint` tool. Do not write prose \
outside the tool call."""


USER_TEMPLATE = """VENDOR: {vendor}
COMPETITOR OPTION NAME: {name}
CURRENT PRICING BASIS: {pricing_basis}

PARENT PRODUCT (from listing.raw_markdown):
{product_json}

VARIANT / PER-OPTION RAW JSON:
{option_json}

Extract the OptionFingerprint. Use the `record_fingerprint` tool."""


def _build_tools() -> list[dict[str, Any]]:
    schema = OptionFingerprint.model_json_schema()
    return [
        {
            "name": "record_fingerprint",
            "description": "Record the structured OptionFingerprint extracted from the raw vendor JSON.",
            "input_schema": schema,
        }
    ]


def _is_thin(fp_json: str | None) -> bool:
    """A fingerprint is 'thin' if it has no rich fields set."""
    if not fp_json:
        return True
    try:
        fp = json.loads(fp_json)
    except json.JSONDecodeError:
        return True
    rich_keys = (
        "highlights",
        "inclusions",
        "exclusions",
        "duration_minutes",
        "duration_label",
        "transfer_included",
        "meal_included",
        "languages",
        "cancellation_window_hours",
        "notes",
        "venue",
        "activity_category",
    )
    for k in rich_keys:
        v = fp.get(k)
        if v in (None, "", [], {}):
            continue
        return False
    return True


def _rows_for_products(
    conn,
    product_ids: list[int] | None,
    source_domain: str | None,
    city: str | None = None,
    country: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch competitor options with their parent product JSON."""
    where = ["o.source = 'competitor'"]
    params: list[Any] = []
    if product_ids:
        where.append(
            "c.rayna_product_id IN (" + ",".join("?" * len(product_ids)) + ")"
        )
        params.extend(product_ids)
    if source_domain:
        where.append("c.seller_domain = ?")
        params.append(source_domain)
    if city:
        where.append("p.city = ?")
        params.append(city)
    if country:
        where.append("p.country = ?")
        params.append(country)
    sql = f"""
        SELECT o.id AS option_id,
               o.name,
               o.pricing_basis,
               o.fingerprint_json,
               o.raw_extracted_json,
               cl.raw_markdown AS listing_raw,
               c.seller_domain
        FROM options o
        JOIN competitor_listings cl ON o.competitor_listing_id = cl.id
        JOIN competitors c ON cl.competitor_id = c.id
        JOIN products p ON c.rayna_product_id = p.id
        WHERE {' AND '.join(where)}
        ORDER BY o.id
    """
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _extract(
    client: Anthropic,
    tools: list[dict[str, Any]],
    row: dict[str, Any],
    model: str = config.CLAUDE_ADJUDICATOR_MODEL,
) -> tuple[dict[str, Any], dict[str, int]]:
    listing_raw = row["listing_raw"] or ""
    option_raw = row["raw_extracted_json"] or ""
    # Trim aggressively — Claude doesn't need runaway HTML, and huge inputs
    # blow up cache + latency. 32k chars ≈ 8k tokens which is generous.
    product_json = (listing_raw or "(no product json)").strip()[:32000]
    option_json = (option_raw or "(no per-option json)").strip()[:16000]

    vendor = row["seller_domain"] or "unknown"

    user_text = USER_TEMPLATE.format(
        vendor=vendor,
        name=row["name"],
        pricing_basis=row["pricing_basis"] or "unknown",
        product_json=product_json,
        option_json=option_json,
    )

    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=tools,
        tool_choice={"type": "tool", "name": "record_fingerprint"},
        messages=[{"role": "user", "content": user_text}],
    )

    tool_blocks = [
        b for b in resp.content if b.type == "tool_use" and b.name == "record_fingerprint"
    ]
    if not tool_blocks:
        raise RuntimeError(
            f"Claude did not call record_fingerprint for option {row['option_id']}; "
            f"stop_reason={resp.stop_reason}"
        )

    # Claude sometimes emits "" for optional numeric fields; coerce to None so
    # Pydantic doesn't 500 the whole enrichment on trivial type-parse issues.
    raw_fp = dict(tool_blocks[0].input)
    for k, v in list(raw_fp.items()):
        if v == "":
            raw_fp[k] = None
    parsed = OptionFingerprint.model_validate(raw_fp)

    # Preserve vendor-specific keys the ingest wrote (headout_variant_id, etc.)
    # by merging Claude's output on top of the existing fingerprint.
    existing = {}
    try:
        existing = json.loads(row["fingerprint_json"] or "{}") or {}
    except json.JSONDecodeError:
        existing = {}
    merged: dict[str, Any] = dict(existing)
    claude_out = parsed.model_dump(exclude_none=False)
    for k, v in claude_out.items():
        # Only overwrite empty/absent existing values, EXCEPT for our rich
        # fields which should always take Claude's latest read.
        if k in {
            "highlights",
            "inclusions",
            "exclusions",
            "duration_minutes",
            "duration_label",
            "transfer_included",
            "transfer_type",
            "meal_included",
            "meal_type",
            "languages",
            "cancellation_window_hours",
            "notes",
            "venue",
            "activity_category",
            "group_min",
            "group_max",
        }:
            merged[k] = v
        elif k not in merged or merged.get(k) in (None, "", []):
            merged[k] = v

    usage = resp.usage
    meta = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    return merged, meta


def run(args: argparse.Namespace) -> None:
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    db.init_db()
    tools = _build_tools()

    conn = db.get_conn()
    conn.row_factory = __import__("sqlite3").Row
    product_ids = args.rayna_product_id or None
    rows = _rows_for_products(
        conn,
        product_ids,
        args.seller_domain,
        city=args.city,
        country=args.country,
    )
    if args.limit:
        rows = rows[: args.limit]

    if not rows:
        print("No matching competitor options found.")
        conn.close()
        return

    print(f"Enriching {len(rows)} option(s)…\n")

    totals = {"input": 0, "cache_create": 0, "cache_read": 0, "output": 0}
    n_updated = 0
    n_skipped = 0
    n_failed = 0

    for row in rows:
        if not args.force and not _is_thin(row["fingerprint_json"]):
            n_skipped += 1
            continue
        # Also skip rows with no raw JSON — nothing for Claude to read
        if not (row["listing_raw"] or row["raw_extracted_json"]):
            n_skipped += 1
            print(
                f"  ? #{row['option_id']} [{row['seller_domain']}] "
                f"{(row['name'] or '')[:60]}  — no raw JSON, skip"
            )
            continue

        try:
            merged_fp, meta = _extract(client, tools, row, model=args.model)
        except Exception as e:  # noqa: BLE001
            n_failed += 1
            print(
                f"  ! #{row['option_id']} [{row['seller_domain']}] "
                f"{(row['name'] or '')[:60]}  — {e}"
            )
            continue

        now = datetime.now(timezone.utc).isoformat()
        with db.tx() as tx_conn:
            tx_conn.execute(
                """UPDATE options
                   SET fingerprint_json = ?,
                       extraction_model = ?,
                       extracted_at = ?
                   WHERE id = ?""",
                (
                    json.dumps(merged_fp, ensure_ascii=False),
                    args.model,
                    now,
                    row["option_id"],
                ),
            )

        totals["input"] += meta["input_tokens"]
        totals["cache_create"] += meta["cache_creation_input_tokens"]
        totals["cache_read"] += meta["cache_read_input_tokens"]
        totals["output"] += meta["output_tokens"]
        n_updated += 1

        # Compact summary
        parts = [
            f"highlights={len(merged_fp.get('highlights') or [])}",
            f"incl={len(merged_fp.get('inclusions') or [])}",
            f"excl={len(merged_fp.get('exclusions') or [])}",
        ]
        if merged_fp.get("duration_minutes"):
            parts.append(f"dur={merged_fp['duration_minutes']}m")
        elif merged_fp.get("duration_label"):
            parts.append(f"dur={merged_fp['duration_label']!r}")
        if merged_fp.get("cancellation_window_hours") is not None:
            parts.append(f"cancel={merged_fp['cancellation_window_hours']}h")
        print(
            f"  ✓ #{row['option_id']} [{row['seller_domain']}] "
            f"{(row['name'] or '')[:60]}  — {', '.join(parts)}"
        )

    conn.close()

    print()
    print(f"Updated:  {n_updated}")
    print(f"Skipped:  {n_skipped}")
    print(f"Failed:   {n_failed}")
    print(
        f"Tokens — input:{totals['input']}  "
        f"cache_create:{totals['cache_create']}  "
        f"cache_read:{totals['cache_read']}  "
        f"output:{totals['output']}"
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--rayna-product-id",
        type=int,
        action="append",
        default=[],
        help="Restrict to competitor options under this Rayna product. Repeatable.",
    )
    p.add_argument(
        "--seller-domain",
        default=None,
        help="e.g. 'headout.com' or 'globaltix.com'. Default: all sellers.",
    )
    p.add_argument("--all", action="store_true", help="Enrich all competitor options.")
    p.add_argument("--city", default=None, help="Restrict by Rayna product city.")
    p.add_argument("--country", default=None, help="Restrict by Rayna product country.")
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-enrich even options that already have rich fingerprints.",
    )
    p.add_argument(
        "--limit", type=int, default=None, help="Max options to process (cost control)."
    )
    p.add_argument(
        "--model",
        default=config.CLAUDE_ADJUDICATOR_MODEL,
        help=f"Claude model id. Default {config.CLAUDE_ADJUDICATOR_MODEL} (Sonnet). "
        f"For a cheaper run use {config.CLAUDE_CLASSIFIER_MODEL} (Haiku).",
    )
    args = p.parse_args()
    if not args.rayna_product_id and not args.all and not args.city and not args.country:
        p.error("Pass --rayna-product-id, --city, --country, or --all.")
    return args


if __name__ == "__main__":
    run(_parse_args())
