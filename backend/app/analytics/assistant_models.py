"""Bounded market evidence contracts for assistant research, without party identifiers."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analytics.models import MarketBedrooms, MarketPeriodRequest, MarketPropertyType


class ComparableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset: Literal["sales", "rentals"]
    period: MarketPeriodRequest
    location: str = Field(min_length=1, max_length=120)
    building: str | None = Field(default=None, min_length=1, max_length=160)
    property_type: MarketPropertyType = "apartment"
    bedrooms: MarketBedrooms
    target_size_sqft: float | None = Field(default=None, gt=0, le=100000)
    size_tolerance: float = Field(default=0.2, ge=0, le=0.5)
    asking_price_aed: float | None = Field(default=None, gt=0, le=100_000_000_000)
    contract_version: Literal["new", "renewed"] | None = None
    limit: int = Field(default=10, ge=1, le=20)
    reference_date: date | None = None

    @model_validator(mode="after")
    def dataset_filters(self):
        if self.dataset == "sales" and self.contract_version:
            raise ValueError("Contract version applies only to rentals")
        return self
