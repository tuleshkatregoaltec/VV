"""Query-parameter dependencies shared by the Transactions and filter-option endpoints.

Every value has explicit bounds, so a request the warehouse cannot answer is a 422: an Int32
overflow used to be a bare 500 or a silent total of 0, and NaN or infinite bands were accepted.
"""

from typing import Optional

from fastapi import Query

from app.transaction.models import (
    MAX_AMOUNT_AED,
    MAX_NAME_LENGTH,
    MAX_PRICE_PER_SQFT_AED,
    MAX_SIZE_SQFT,
    MAX_TIMEFRAME_DAYS,
    RentalFilters,
    SalesFilters,
)


def _name(description: str):
    return Query(default=None, max_length=MAX_NAME_LENGTH, description=description)


def _band(maximum: float, description: str):
    return Query(default=None, ge=0, le=maximum, allow_inf_nan=False, description=description)


def _timeframe(description: str):
    return Query(default=None, ge=1, le=MAX_TIMEFRAME_DAYS, description=description)


def sales_filters(
    property_usage: Optional[str] = _name(
        "Residential or Commercial (grouped from DXBI property types)"
    ),
    property_type: Optional[str] = _name("DXBI property type"),
    bedrooms: Optional[str] = _name("'Studio', '1 Bed', '2 Beds', ..."),
    status: Optional[str] = _name("Off-Plan or Ready"),
    location: Optional[str] = _name(
        "DXBI area or community: every record its DXBI area page counts"
    ),
    location_search: Optional[str] = _name("Keywords across DXBI building, project and area"),
    building: Optional[str] = _name("DXBI building name"),
    project: Optional[str] = _name("DXBI project name"),
    timeframe_days: Optional[int] = _timeframe("Last N calendar days in Dubai, today included"),
    size_min: Optional[float] = _band(MAX_SIZE_SQFT, "Minimum size (sq ft), inclusive"),
    size_max: Optional[float] = _band(MAX_SIZE_SQFT, "Maximum size (sq ft), exclusive"),
    price_min: Optional[float] = _band(MAX_AMOUNT_AED, "Minimum price (AED), inclusive"),
    price_max: Optional[float] = _band(MAX_AMOUNT_AED, "Maximum price (AED), exclusive"),
    price_per_sqft_min: Optional[float] = _band(
        MAX_PRICE_PER_SQFT_AED, "Minimum price per sq ft (AED), inclusive"
    ),
    price_per_sqft_max: Optional[float] = _band(
        MAX_PRICE_PER_SQFT_AED, "Maximum price per sq ft (AED), exclusive"
    ),
) -> SalesFilters:
    return SalesFilters(
        property_usage=property_usage,
        property_type=property_type,
        bedrooms=bedrooms,
        status=status,
        location=location,
        location_search=location_search,
        building=building,
        project=project,
        timeframe_days=timeframe_days,
        size_min=size_min,
        size_max=size_max,
        price_min=price_min,
        price_max=price_max,
        price_per_sqft_min=price_per_sqft_min,
        price_per_sqft_max=price_per_sqft_max,
    )


def rental_filters(
    property_usage: Optional[str] = _name(
        "Residential or Commercial (grouped from DXBI property types)"
    ),
    property_type: Optional[str] = _name("DXBI property type"),
    bedrooms: Optional[str] = _name("'Studio', '1 Bed', '2 Beds', ..."),
    contract_type: Optional[str] = _name("New or Renewed"),
    location: Optional[str] = _name(
        "DXBI area or community: every record its DXBI area page counts"
    ),
    location_search: Optional[str] = _name("Keywords across DXBI building, project and area"),
    building: Optional[str] = _name("DXBI building name"),
    project: Optional[str] = _name("DXBI project name"),
    timeframe_days: Optional[int] = _timeframe(
        "Leases starting in the last N calendar days in Dubai, today included"
    ),
    size_min: Optional[float] = _band(MAX_SIZE_SQFT, "Minimum size (sq ft), inclusive"),
    size_max: Optional[float] = _band(MAX_SIZE_SQFT, "Maximum size (sq ft), exclusive"),
    rent_min: Optional[float] = _band(MAX_AMOUNT_AED, "Minimum annual rent (AED), inclusive"),
    rent_max: Optional[float] = _band(MAX_AMOUNT_AED, "Maximum annual rent (AED), exclusive"),
) -> RentalFilters:
    return RentalFilters(
        property_usage=property_usage,
        property_type=property_type,
        bedrooms=bedrooms,
        contract_type=contract_type,
        location=location,
        location_search=location_search,
        building=building,
        project=project,
        timeframe_days=timeframe_days,
        size_min=size_min,
        size_max=size_max,
        rent_min=rent_min,
        rent_max=rent_max,
    )
