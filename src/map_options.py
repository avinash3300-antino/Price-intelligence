"""Option-pair mapping: Claude Sonnet adjudicates each (Rayna option, competitor option) pair.

Brief's Idea 2 in action: matching runs on structured fingerprints — Claude
returns identical / near / different + a confidence score + a written note of
exactly what differs.

Brief's principles in action:
- "Compare like for like, or say so" — `pricing_basis_mismatch=True` if the
  bases don't match (e.g. Rayna per_adult vs competitor per_boat) and the
  comparison is then flagged as invalid for human review.
- "Accuracy over coverage" — low-confidence pairs are flagged, not silently
  used. The Streamlit UI later routes ambiguous mappings to the human checkpoint.

Blocking: for each Rayna option, candidate competitor options are everything
extracted for that same anchor Rayna product. This is cheap and right for the
PoC; for scale we'd add city/venue/category filters first.
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Literal, Optional

from anthropic import Anthropic
from pydantic import BaseModel, Field

from src import config, db

PARALLEL_WORKERS = 6
_db_lock = threading.Lock()

Verdict = Literal["identical", "near", "different"]


class MappingVerdict(BaseModel):
    verdict: Verdict = Field(
        description="identical = same option; near = same product but a different variant (e.g. transfer differs); different = should not be compared"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="0..1. Below 0.7 means human review required.",
    )
    venue_match: bool = Field(
        description="Same venue / operator / activity anchor."
    )
    pricing_basis_mismatch: bool = Field(
        description="True if pricing bases differ (e.g. per_adult vs per_boat) — direct price comparison is INVALID until resolved."
    )
    inclusion_differences: list[str] = Field(
        default_factory=list,
        description="Material differences in what is included/excluded. Example: 'Rayna includes BBQ dinner; competitor does not'.",
    )
    tier_difference: Optional[str] = Field(
        default=None,
        description="Tier difference if any (e.g. 'Rayna is Standard 124/125; competitor is SKY 148'). None if tiers match.",
    )
    diff_notes: str = Field(
        description="One or two sentences summarizing the verdict and the most material difference. This is what the destination head will read."
    )


SYSTEM_PROMPT = """You are adjudicating whether two bookable options from different sellers \
represent the SAME purchase decision for the customer — i.e. like-for-like.

You will be given:
  • RAYNA OPTION — name, fingerprint (venue, duration, tier, pricing_basis, inclusions, exclusions, transfer, meal), price
  • COMPETITOR OPTION — same fields, from a different seller
  • The Rayna anchor product (for context)

Return a structured verdict via the `record_mapping` tool.

VERDICT:
- `identical`: same venue, same tier, same pricing basis, same major inclusions/exclusions. \
A customer would consider these directly interchangeable. The price gap is the headline number.
- `near`: same product family but a meaningful variant difference (e.g. one with transfer, \
one without; one is BBQ-dinner-included, the other isn't; durations differ). The two ARE \
comparable but the price gap must be read alongside the difference.
- `different`: should not be price-compared at all. Different venue, different category, \
or the competitor option isn't really the same experience.

CRITICAL RULES:
1. If `pricing_basis` differs (e.g. Rayna per_adult vs competitor per_boat), set \
`pricing_basis_mismatch=True`. The verdict can still be `near` if the underlying \
experience matches, but the price gap is NOT directly comparable until the basis is reconciled.

2. Be conservative on `identical`. Only use it when you have high confidence in every \
material dimension. If anything material differs, choose `near`.

3. NEVER claim things you can't see. If a fingerprint field is None on either side, \
say so in `diff_notes` ("competitor inclusions not stated") rather than assuming.

4. Confidence below 0.7 means human review is required — be honest. Don't inflate.

5. `diff_notes` is read by a destination head making a pricing call. Be specific and short. \
Example good: "Same Burj Khalifa 124/125 ticket; competitor adds hotel transfer Rayna lists separately." \
Example bad: "These seem similar."

Output ONLY via the `record_mapping` tool.
"""

USER_TEMPLATE = """ANCHOR (the Rayna product these options belong to):
  Name: {anchor_name}  ({anchor_city}, {anchor_type})

RAYNA OPTION
  Name:           {rayna_name}
  Price:          {rayna_price}
  Pricing basis:  {rayna_basis}
  Fingerprint:
{rayna_fp}

COMPETITOR OPTION
  Seller:         {competitor_domain}
  Name:           {competitor_name}
  Price:          {competitor_price}
  Pricing basis:  {competitor_basis}
  Fingerprint:
{competitor_fp}

Adjudicate via record_mapping."""


def build_tools():
    return [
        {
            "name": "record_mapping",
            "description": "Record the verdict + confidence + diff for this option pair.",
            "input_schema": MappingVerdict.model_json_schema(),
        }
    ]


def _fp_pretty(fp_json_str: str) -> str:
    """Render the fingerprint as readable key:value lines, dropping empties."""
    fp = json.loads(fp_json_str)
    lines = []
    for k, v in fp.items():
        if v in (None, "", [], {}):
            continue
        if isinstance(v, list):
            v = ", ".join(map(str, v))
        lines.append(f"    {k}: {v}")
    return "\n".join(lines) if lines else "    (empty)"


def _format_price(price, currency) -> str:
    if price is None:
        return "(not stated)"
    return f"{price} {currency or ''}".strip()


def adjudicate(client: Anthropic, anchor_product, rayna_opt, competitor_opt, competitor_domain, tools):
    user_text = USER_TEMPLATE.format(
        anchor_name=anchor_product["name"],
        anchor_city=anchor_product["city"] or "Dubai",
        anchor_type=anchor_product["type"] or "activities",
        rayna_name=rayna_opt["name"],
        rayna_price=_format_price(rayna_opt["price"], rayna_opt["currency"]),
        rayna_basis=rayna_opt["pricing_basis"],
        rayna_fp=_fp_pretty(rayna_opt["fingerprint_json"]),
        competitor_domain=competitor_domain,
        competitor_name=competitor_opt["name"],
        competitor_price=_format_price(competitor_opt["price"], competitor_opt["currency"]),
        competitor_basis=competitor_opt["pricing_basis"],
        competitor_fp=_fp_pretty(competitor_opt["fingerprint_json"]),
    )

    resp = client.messages.create(
        model=config.CLAUDE_ADJUDICATOR_MODEL,
        max_tokens=800,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=tools,
        tool_choice={"type": "tool", "name": "record_mapping"},
        messages=[{"role": "user", "content": user_text}],
    )

    tool_blocks = [b for b in resp.content if b.type == "tool_use" and b.name == "record_mapping"]
    if not tool_blocks:
        raise RuntimeError(f"No record_mapping call; stop={resp.stop_reason}")

    parsed = MappingVerdict.model_validate(tool_blocks[0].input)
    return parsed, resp.usage, resp.model


def _already_mapped(rayna_option_id: int, competitor_option_id: int) -> bool:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM mappings WHERE rayna_option_id=? AND competitor_option_id=? LIMIT 1",
            (rayna_option_id, competitor_option_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _save_mapping(rayna_opt_id, competitor_opt_id, parsed, model, now):
    with _db_lock, db.tx() as conn:
        # Constraint: one Rayna option can be mapped to at most one option per
        # seller_domain. If a mapping already exists for this Rayna option on
        # the same seller (but a DIFFERENT competitor option), keep whichever
        # has higher confidence.
        conflicts = conn.execute(
            """SELECT m.id AS mapping_id,
                     m.competitor_option_id,
                     m.confidence,
                     m.is_manual,
                     c2.seller_domain
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
            (rayna_opt_id, competitor_opt_id, competitor_opt_id),
        ).fetchall()

        for row in conflicts:
            # Manual mappings win over auto ones regardless of confidence —
            # a human decision beats a model score.
            if row["is_manual"]:
                return
            if (row["confidence"] or 0) >= parsed.confidence:
                return
            conn.execute("DELETE FROM mappings WHERE id=?", (row["mapping_id"],))

        conn.execute(
            """INSERT OR REPLACE INTO mappings
                 (rayna_option_id, competitor_option_id, verdict, confidence,
                  diff_notes, judge_model, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rayna_opt_id, competitor_opt_id, parsed.verdict, parsed.confidence,
             parsed.diff_notes, model, now),
        )


def _process_pair(client, anchor, rayna_opt, competitor_opt, tools, now):
    try:
        parsed, usage, model = adjudicate(
            client, anchor, rayna_opt, competitor_opt,
            competitor_opt["seller_domain"], tools,
        )
    except Exception as e:
        return None, None, None, f"{type(e).__name__}: {e}", anchor, rayna_opt, competitor_opt
    _save_mapping(rayna_opt["id"], competitor_opt["id"], parsed, model, now)
    return parsed, usage, model, None, anchor, rayna_opt, competitor_opt


def run() -> None:
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    db.init_db()
    tools = build_tools()
    now = datetime.now(timezone.utc).isoformat()

    conn = db.get_conn()
    products = {p["id"]: dict(p) for p in conn.execute("SELECT * FROM products")}

    pairs = []
    for pid, anchor in products.items():
        rayna_opts = list(
            conn.execute(
                "SELECT * FROM options WHERE source='rayna' AND rayna_product_id=?",
                (pid,),
            )
        )
        competitor_opts = list(
            conn.execute(
                """SELECT o.*, c.seller_domain
                   FROM options o
                   JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
                   JOIN competitors c ON c.id = cl.competitor_id
                   WHERE o.source='competitor' AND c.rayna_product_id=?""",
                (pid,),
            )
        )
        for r in rayna_opts:
            for c in competitor_opts:
                pairs.append((anchor, dict(r), dict(c)))
    conn.close()

    pending = [p for p in pairs if not _already_mapped(p[1]["id"], p[2]["id"])]
    skipped = len(pairs) - len(pending)
    print(
        f"Adjudicating {len(pending)} option pair(s) "
        f"({skipped} already mapped, skipped) using {PARALLEL_WORKERS} workers\n"
    )

    totals = {"input": 0, "cache_read": 0, "cache_create": 0, "output": 0}
    by_verdict: dict[str, int] = {}
    done = 0

    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
        futures = [
            pool.submit(_process_pair, client, anchor, r, c, tools, now)
            for (anchor, r, c) in pending
        ]
        for fut in as_completed(futures):
            parsed, usage, model, err, anchor, rayna_opt, competitor_opt = fut.result()
            done += 1
            if err:
                print(f"  [{done:>3}/{len(pending)}] ! FAILED {competitor_opt['seller_domain']}: {err}")
                continue

            totals["input"] += usage.input_tokens
            totals["output"] += usage.output_tokens
            totals["cache_create"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
            totals["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0
            by_verdict[parsed.verdict] = by_verdict.get(parsed.verdict, 0) + 1

            basis_flag = " ⚠basis" if parsed.pricing_basis_mismatch else ""
            review_flag = " ◆review" if parsed.confidence < 0.7 else ""
            print(
                f"  [{done:>3}/{len(pending)}] {anchor['name'][:20]:<20} | "
                f"{competitor_opt['seller_domain'][:22]:<22} | "
                f"{parsed.verdict:<9} {parsed.confidence:.2f}{basis_flag}{review_flag}"
            )

    print(
        f"\nDone. By verdict: {dict(sorted(by_verdict.items()))}\n"
        f"Tokens — input:{totals['input']}  cache_create:{totals['cache_create']}  "
        f"cache_read:{totals['cache_read']}  output:{totals['output']}"
    )


if __name__ == "__main__":
    run()
