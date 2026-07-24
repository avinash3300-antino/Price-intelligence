"""Claude Haiku adjudicator for Rayna ↔ Headout apple-to-apple matching.

Given one Rayna product and a small batch of Headout candidates (already
fuzzy-shortlisted), returns a per-candidate ``same_product`` verdict. Only
YES verdicts flow through to the ingest.

The prompt is deliberately strict:

* SAME = both entries book the SAME real-world experience (venue, activity,
  duration class). Different transfer / tier / date is still SAME.
* DIFFERENT = venue changes, activity changes, or one is a combo/bundle that
  wraps the other with additional inclusions.

Prompt caching is used on the system message so subsequent calls in the same
process are cheaper.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from anthropic import Anthropic

from src import config

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 1500
_CLIENT: Anthropic | None = None

# Max candidates in a single Claude call. Larger prompts risk truncation and
# make the model less consistent, so we chunk large shortlists.
_BATCH_SIZE = 10

_SYSTEM = """You are matching tour products from two online travel agencies (OTAs).
Your job: decide, for each candidate, whether it books the SAME real-world experience as the anchor product — apple-to-apple.

SAME (return true):
- Same venue / same activity / same category
- Different transfer type, tier, or date window is fine — those are variants of the same product

DIFFERENT (return false):
- Different venue (e.g., Burj Khalifa vs. Burj Al Arab)
- Different activity type (e.g., Desert Safari vs. City Tour, Fishing vs. Sea Lion Experience)
- One is a COMBO or BUNDLE that includes the anchor plus additional attractions
- Peripheral overlap only (e.g., "Dinner in Desert" vs. "Dinner in the Sky" — both dinners but different venues)

Return STRICT JSON only, no prose, matching this schema exactly:

{
  "matches": [
    {"headout_id": "<the id you were given>", "same_product": true|false, "confidence": 0.0-1.0, "reason": "one short sentence"}
  ]
}

Preserve the order and the exact headout_id strings you were given."""


def _client() -> Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _CLIENT


def _short(s: str | None, n: int = 300) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _rayna_block(rayna: dict[str, Any]) -> str:
    raw = json.loads(rayna.get("raw_json") or "{}") if isinstance(rayna.get("raw_json"), str) else (rayna.get("raw_json") or {})
    return (
        f"Rayna product:\n"
        f"- Name: {rayna.get('name')}\n"
        f"- City: {rayna.get('city')}\n"
        f"- Country: {rayna.get('country')}\n"
        f"- Type: {rayna.get('type')}\n"
        f"- Description: {_short(raw.get('description_text') or raw.get('content_overview'))}"
    )


def _candidate_block(hp: dict[str, Any]) -> str:
    cat = (hp.get("primaryCategory") or {}).get("name")
    subcat = (hp.get("primarySubCategory") or {}).get("name")
    summary = (hp.get("content") or {}).get("shortSummary")
    return (
        f"- Headout id={hp.get('id')}:\n"
        f"    Name: {hp.get('name')}\n"
        f"    Category: {cat}{f' / {subcat}' if subcat else ''}\n"
        f"    Summary: {_short(summary, 240)}"
    )


def adjudicate_batch(
    rayna: dict[str, Any],
    candidates: list[dict[str, Any]],
    max_retries: int = 2,
) -> list[dict[str, Any]]:
    """Return one decision dict per candidate, in the same order.

    Large candidate lists are split into chunks of ``_BATCH_SIZE`` and the
    results concatenated. Each dict: {headout_id, same_product, confidence,
    reason}. On failure, falls back to "false" for that chunk so the pipeline
    can proceed (missed matches beat false matches).
    """
    if not candidates:
        return []
    if len(candidates) > _BATCH_SIZE:
        out: list[dict[str, Any]] = []
        for i in range(0, len(candidates), _BATCH_SIZE):
            out.extend(_adjudicate_chunk(rayna, candidates[i : i + _BATCH_SIZE], max_retries))
        return out
    return _adjudicate_chunk(rayna, candidates, max_retries)


def _adjudicate_chunk(
    rayna: dict[str, Any],
    candidates: list[dict[str, Any]],
    max_retries: int,
) -> list[dict[str, Any]]:
    user_msg = (
        _rayna_block(rayna)
        + "\n\nCandidates:\n"
        + "\n".join(_candidate_block(hp) for hp in candidates)
        + "\n\nReturn JSON now. No prose."
    )

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = _client().messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": _SYSTEM,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_msg}],
            )
            text = "".join(
                b.text for b in resp.content if getattr(b, "type", None) == "text"
            ).strip()
            # strip ```json fences if present
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
            data = json.loads(text)
            matches = data.get("matches") or []
            by_id = {str(m.get("headout_id")): m for m in matches}
            out: list[dict[str, Any]] = []
            for hp in candidates:
                hid = str(hp.get("id"))
                m = by_id.get(hid, {})
                out.append(
                    {
                        "headout_id": hid,
                        "same_product": bool(m.get("same_product")),
                        "confidence": float(m.get("confidence") or 0.0),
                        "reason": (m.get("reason") or "").strip(),
                    }
                )
            return out
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(0.8 * (attempt + 1))
    # give up: return NO for everything so we don't accidentally accept junk
    print(f"    ! Claude adjudication failed after retries: {last_err}")
    return [
        {"headout_id": str(hp.get("id")), "same_product": False,
         "confidence": 0.0, "reason": f"claude error: {type(last_err).__name__ if last_err else 'unknown'}"}
        for hp in candidates
    ]
