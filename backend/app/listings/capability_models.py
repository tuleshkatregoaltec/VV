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
    price_min: float | None = Field(default=None, ge=0, le=1_000_000_000, allow_inf_nan=False)
    price_max: float | None = Field(default=None, gt=0, le=1_000_000_000, allow_inf_nan=False)
    price_min_inclusive: bool = True
    price_max_inclusive: bool = True
    limit: int = Field(default=10, ge=1, le=20)


class ListingAgeRequest(ListingEvidenceRequest):
    mode: Literal["sale"] = "sale"
    older_than_days: int = Field(default=90, ge=1, le=3660)


class ListingRentRequest(ListingEvidenceRequest):
    property_type: Literal["Apartment", "Villa", "Office", "Shop"] = "Apartment"
    mode: Literal["sale"] = "sale"
    bedrooms: MarketBedrooms
    location: str = Field(min_length=1, max_length=120)
    limit: int = Field(default=5, ge=1, le=8)
    period: MarketPeriodRequest = Field(
        default_factory=lambda: MarketPeriodRequest(type="rolling_days", days=90)
    )
