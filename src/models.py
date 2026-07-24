"""Pydantic models for option fingerprints. This is the unit of comparison."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

PricingBasis = Literal[
    "per_adult",
    "per_child",
    "private_group",
    "per_vehicle",
    "per_boat",
    "per_yacht",
    "unknown",
]


class OptionFingerprint(BaseModel):
    """Structured fingerprint of a single bookable option.

    Brief's Idea 1: the unit of comparison is the option, not the product.
    Brief's Idea 2: matching runs on these structured fields, not on prose.
    """

    venue: Optional[str] = Field(
        default=None,
        description="Anchor venue (e.g. 'Burj Khalifa') or operator name. None for purely operator-led tours without a single venue.",
    )
    activity_category: Optional[str] = Field(
        default=None,
        description="Coarse category, e.g. 'observation_deck', 'desert_safari', 'fishing_charter', 'city_tour', 'theme_park'.",
    )

    duration_minutes: Optional[int] = Field(
        default=None, description="Total duration in minutes if known."
    )
    duration_label: Optional[str] = Field(
        default=None,
        description="Original duration string when not cleanly numeric, e.g. 'half day', '08:30 am - 02:30 pm'.",
    )

    tier: Optional[str] = Field(
        default=None,
        description="Option tier within the product, e.g. 'standard', 'prime_hours', 'sky_148', 'premium', 'vip'.",
    )

    pricing_basis: PricingBasis = Field(
        default="unknown",
        description="What unit the price applies to. Brief mandates per_adult for comparison; other bases must be flagged.",
    )
    group_min: Optional[int] = None
    group_max: Optional[int] = None

    highlights: list[str] = Field(
        default_factory=list,
        description="Marketing highlights — short bullets a seller uses to promote the option (e.g. 'Skip the line', 'Sunset views', 'Free hotel pickup'). Distinct from inclusions/exclusions.",
    )
    inclusions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)

    transfer_included: Optional[bool] = None
    transfer_type: Optional[Literal["sic", "private", "self_drive"]] = None

    meal_included: Optional[bool] = None
    meal_type: Optional[str] = Field(
        default=None,
        description="e.g. 'breakfast', 'bbq_dinner', 'three_course', 'snacks_only'.",
    )

    languages: list[str] = Field(default_factory=list)
    cancellation_window_hours: Optional[int] = None

    notes: Optional[str] = Field(
        default=None, description="Free text for anything material that didn't fit the schema."
    )


class ExtractedOption(BaseModel):
    """One option extracted from a product page or competitor listing."""

    name: str = Field(description="Short label, e.g. 'Standard, non-prime, no transfer'.")
    price: Optional[float] = Field(
        default=None, description="Price in the option's stated currency, if known."
    )
    currency: Optional[str] = None
    fingerprint: OptionFingerprint
    source_evidence: str = Field(
        description="Direct quote from the source text that supports this option."
    )


class ExtractionResult(BaseModel):
    """Top-level response from the option extractor.

    Source linkage (rayna_product_id / competitor_listing_id) is injected by the
    caller after extraction — Claude does not need to know either.
    """

    options: list[ExtractedOption]
    extraction_notes: Optional[str] = Field(
        default=None,
        description="Anything the extractor flagged as ambiguous, missing, or needing human review. Use this for things you noticed but couldn't put in any single option.",
    )
