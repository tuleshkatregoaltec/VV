"""Contact-free, bounded listing evidence for conversational shortlists."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.listings import service
from app.listings.models import ListingMode
from app.market.reference import community_location


class ListingResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: ListingMode = "sale"
    location: str = Field(min_length=1, max_length=120)
    building: str | None = Field(default=None, min_length=1, max_length=160)
    bedrooms: str | None = Field(default=None, max_length=20)
    property_type: str = Field(default="Apartment", min_length=1, max_length=80)
    price_min: int | None = Field(default=None, ge=0)
    price_max: int | None = Field(default=None, gt=0, le=100_000_000_000)
    min_age_days: int | None = Field(default=None, ge=0, le=10000)
    max_age_days: int | None = Field(default=None, ge=0, le=10000)
    limit: int = Field(default=10, ge=1, le=20)
    offset: int = Field(default=0, ge=0, le=200)

    @model_validator(mode="after")
    def ordered_filters(self):
        for lower, upper in (
            (self.price_min, self.price_max),
            (self.min_age_days, self.max_age_days),
        ):
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("Minimum cannot exceed maximum")
        return self


async def research_listings(request: ListingResearchRequest) -> dict:
    filters = request.model_dump(exclude={"location"})
    result = await service.list_listings_from_clickhouse(
        **filters,
        area=community_location(request.location).name,
        include_filters=False,
        price_basis="annual" if request.mode == "rent" else "raw",
    )
    fields = {
        "title",
        "reference",
        "property_type",
        "price_value",
        "price_currency",
        "price_period",
        "size_value",
        "size_unit",
        "bedrooms",
        "area_name",
        "subcommunity_name",
        "tower_name",
        "location_name",
        "listed_date",
        "captured_at",
        "listing_age_days",
        "price_per_sqft_aed",
    }
    rows = [item.model_dump(mode="json", include=fields) for item in result.listings]
    for item, row in zip(result.listings, rows, strict=True):
        unit = (item.size_unit or "").lower()
        size = item.size_value if unit in {"sqft", "sq ft", "ft2", "ft²"} else None
        if unit in {"sqm", "sq m", "m2", "m²"} and item.size_value:
            size = item.size_value * 10.7639104167
        row.pop("size_value", None)
        row.pop("size_unit", None)
        row["size_sqft"] = size
        period = (item.price_period or "").lower()
        factor = {
            "year": 1,
            "yearly": 1,
            "annual": 1,
            "annually": 1,
            "month": 12,
            "monthly": 12,
            "week": 52,
            "weekly": 52,
            "day": 365,
            "daily": 365,
        }.get(period)
        amount = (
            item.price_value
            if request.mode == "sale"
            else item.price_value * factor
            if item.price_value and factor
            else None
        )
        row["asking_aed"] = amount
        row["asking_definition"] = (
            "Sale asking price" if request.mode == "sale" else "Annual asking rent"
        )
        row["price_per_sqft_aed"] = round(amount / size, 2) if amount and size else None
        if item.captured_at is None:
            row["listing_age_days"] = None
    return {
        "source": "Property Finder asking listings",
        "applied_filters": request.model_dump(mode="json"),
        "total": result.total,
        "returned_count": len(rows),
        "offset": result.offset,
        "records": rows,
        "limitations": [
            "Asking prices are not achieved transactions. Availability is only as captured; verify it before contacting a seller.",
            "Age is measured at the captured timestamp, never from today's date. Missing capture or listing dates mean unknown age.",
            "Counts cover all matching captured listings; the returned shortlist is a page, not an exhaustive ranking.",
            "Compare prices per sq ft only for similar building, bedroom, type and size; unobserved condition and views can differ.",
        ],
    }
