"""Bounded public inputs for listing evidence (never account or database selectors)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.analytics.models import MarketBedrooms, MarketPeriodRequest


class ListingEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["sale", "rent"] = "sale"
    location: str | None = Field(default=None, max_length=120)
    building: str | None = Field(default=None, max_length=160)
    bedrooms: MarketBedrooms | None = None
    property_type: Literal["Apartment", "Villa", "Townhouse", "Office", "Shop"] = "Apartment"
    price_max: int | None = Field(default=None, gt=0, le=1_000_000_000)
    limit: int = Field(default=10, ge=1, le=20)


class ListingAgeRequest(ListingEvidenceRequest):
    mode: Literal["sale"] = "sale"
    older_than_days: int = Field(default=90, ge=1, le=3660)


class ListingRentRequest(ListingEvidenceRequest):
    mode: Literal["sale"] = "sale"
    bedrooms: MarketBedrooms
    location: str = Field(min_length=1, max_length=120)
    limit: int = Field(default=5, ge=1, le=8)
    period: MarketPeriodRequest = Field(
        default_factory=lambda: MarketPeriodRequest(type="rolling_days", days=90)
    )
