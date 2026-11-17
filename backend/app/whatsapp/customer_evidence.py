"""Bounded customer retrieval contracts and deterministic evidence rendering."""

import math
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.analytics.models import MarketMetricsResponse
from app.whatsapp.customer_models import ListingPropertyType, WhatsAppPublishedListing


class ListingSearch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    operation: Literal["published_listings"]
    location: str | None = Field(default=None, min_length=1, max_length=120)
    transaction: Literal["sale", "rent"] | None = None
    property_type: ListingPropertyType | None = None
    bedrooms: int | None = Field(default=None, ge=0, le=20)
    max_price_aed: float | None = Field(default=None, gt=0, le=1_000_000_000, allow_inf_nan=False)


class MarketSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    operation: Literal["market_summary"]
    dataset: Literal["sales", "rentals"]
    location: str | None = Field(default=None, min_length=1, max_length=120)
    period: Literal["previous_month", "previous_quarter"] = "previous_month"


CustomerRetrieval = Annotated[ListingSearch | MarketSummary, Field(discriminator="operation")]


class CustomerEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["listing", "market"]
    text: str = Field(min_length=1, max_length=3500)
    expires_at: AwareDatetime
    listing_id: str | None = None
    revision: int | None = None
    release_id: str | None = None


def listing_evidence(row: WhatsAppPublishedListing) -> CustomerEvidence:
    price = f"AED {row.price_aed:,.2f}" + (" per year" if row.transaction == "rent" else "")
    details = [
        f"{row.title} — {row.location}.",
        f"{row.property_type.title()} for {row.transaction}.",
    ]
    if row.bedrooms is not None:
        details.append("Studio." if row.bedrooms == 0 else f"Bedrooms: {row.bedrooms}.")
    if row.area_sqft is not None:
        details.append(f"Area: {row.area_sqft:,.2f} sq ft.")
    details.extend(
        [
            f"Broker-published asking price: {price}.",
            f"Availability: {row.availability.replace('_', ' ')}.",
            f"Broker-approved on {row.updated_at.isoformat()}; valid until {row.expires_at.isoformat()}.",
            "Broker verification is required before proceeding.",
        ]
    )
    return CustomerEvidence(
        id=f"listing:{row.id}:{row.revision}",
        kind="listing",
        text="\n".join(details),
        expires_at=row.expires_at,
        listing_id=row.id,
        revision=row.revision,
    )


def market_evidence(
    result: MarketMetricsResponse, *, expires_at: datetime, location: str | None
) -> CustomerEvidence | None:
    # Small groups can expose individual deal terms. Unverified coverage is not a total.
    if not result.release_id or (result.total.count or 0) < 10:
        return None
    if result.coverage.status not in {"complete", "partial", "unverified"}:
        return None
    if any("release changed" in note.lower() for note in result.limitations):
        return None
    median = result.total.values.get("median_aed")
    if median is None or not math.isfinite(median) or median <= 0:
        return None
    label = "sale price" if result.dataset == "sales" else "annual rent"
    lines = [
        f"{(location or 'Dubai')} market {result.dataset}: {result.period.start} to "
        f"{result.period.end} ({result.period.timezone}).",
        f"Observed eligible records: {result.total.count:,}; median {label}: AED {median:,.2f}.",
        f"Coverage: {result.coverage.status}. {result.coverage.note}",
        "Source: served canonical DLD/DXBI market records. "
        f"Data updated: {result.release_built_at or 'unknown'}.",
        "Only eligible stored records are included; these are not all market activity or a valuation.",
    ]
    lines.extend(result.limitations)
    text = "\n".join(dict.fromkeys(lines))
    if len(text) > 3500:
        return None  # Never truncate away coverage or source limitations.
    return CustomerEvidence(
        id=f"market:{result.dataset}",
        kind="market",
        text=text,
        expires_at=expires_at,
        release_id=result.release_id,
    )
