"""Turn a Rayna product's feed content into OptionFingerprint fields.

The variant rows the feed returns carry only tier, transfer type, duration and
a cancellation string — eight fields. Competitor options, extracted by Claude,
carry eighteen. On the side-by-side comparison that left our own column
reading "not stated" against a fully populated competitor, which is the
opposite of what the page is for.

The missing detail already exists in the feed, just at product level rather
than per variant: content_highlights, content_inclusions, content_exclusions,
amenity_language and so on. This module reshapes those into the same field
names the competitor fingerprints use, so the two sides line up.

The scope difference is real and is recorded rather than hidden: every variant
of a product shares this content, so the fingerprint carries
`content_scope: "product"` and the UI says so. Option-level values always win
over product-level ones when both exist.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# The feed serves these lists as a single string with the items concatenated
# and no separator: "…selected programAccess to a marine mammal…". The join is
# detectable because a capital letter ends up directly against the previous
# item's last character with no space, which does not happen in ordinary prose
# where a capital always follows a space.
_JOIN = re.compile(r'(?<=[a-z0-9)\].,;:!?%"’])(?=[A-Z])')

# "Free Cancellation 72 hours Prior" -> 72
_CANCEL_HOURS = re.compile(r"(\d+)\s*hour", re.IGNORECASE)

_MAX_NOTES = 600


def split_items(value: Any) -> list[str]:
    """Recover a list from the feed's separator-less concatenation."""
    if not value or not isinstance(value, str):
        return []
    parts = (p.strip(" \t•-–—") for p in _JOIN.split(value))
    return [p for p in parts if len(p) > 2]


def cancellation_hours(*candidates: Any) -> Optional[int]:
    """First parseable "N hours" from the given strings."""
    for c in candidates:
        if isinstance(c, str):
            m = _CANCEL_HOURS.search(c)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    pass
    return None


def _languages(value: Any) -> list[str]:
    """'English / Arabic' -> ['English', 'Arabic']"""
    if not isinstance(value, str) or not value.strip():
        return []
    return [p.strip() for p in re.split(r"[/,]", value) if p.strip()]


def content_fingerprint(raw: dict[str, Any]) -> dict[str, Any]:
    """Fingerprint fields derived from one product's feed row.

    Only non-empty values are returned, so merging never overwrites a real
    option-level value with a blank product-level one.
    """
    out: dict[str, Any] = {}

    venue = raw.get("location_title") or raw.get("location_address")
    if isinstance(venue, str) and venue.strip():
        out["venue"] = venue.strip()

    for key, source in (
        ("highlights", "content_highlights"),
        ("inclusions", "content_inclusions"),
        ("exclusions", "content_exclusions"),
    ):
        items = split_items(raw.get(source))
        if items:
            out[key] = items

    langs = _languages(raw.get("amenity_language"))
    if langs:
        out["languages"] = langs

    duration = raw.get("amenity_duration")
    if isinstance(duration, str) and duration.strip():
        out["duration_label"] = duration.strip()

    meals = raw.get("amenity_meals")
    if isinstance(meals, str) and meals.strip():
        out["meal_included"] = True
        out["meal_type"] = meals.strip()

    hours = cancellation_hours(raw.get("amenity_cancellation"))
    if hours is not None:
        out["cancellation_window_hours"] = hours

    overview = raw.get("content_overview")
    if isinstance(overview, str) and overview.strip():
        text = overview.strip()
        out["notes"] = text[:_MAX_NOTES] + ("…" if len(text) > _MAX_NOTES else "")

    if out:
        # Tells the UI these describe the product, not this one variant, so it
        # can label them rather than implying per-option precision we do not
        # have.
        out["content_scope"] = "product"
    return out


def merge_into(option_fingerprint: dict[str, Any], product_raw: dict[str, Any]) -> dict[str, Any]:
    """Product content underneath, option-level values on top.

    The variant's own tier, transfer type, duration and cancellation text are
    specific to it and must never be replaced by the product-wide equivalents.
    """
    merged = dict(content_fingerprint(product_raw))
    merged.update(option_fingerprint)

    # cancellation_text is per variant and more precise than the product-level
    # amenity string, so derive the numeric window from it when present.
    hours = cancellation_hours(option_fingerprint.get("cancellation_text"))
    if hours is not None:
        merged["cancellation_window_hours"] = hours
    return merged
