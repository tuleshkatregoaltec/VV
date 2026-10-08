"""Query-parameter dependencies shared by the Transactions and filter-option endpoints."""

from typing import Optional

from fastapi import Query

from app.transaction.models import RentalFilters, SalesFilters


def sales_filters(
    property_usage: Optional[str] = Query(
        default=None, description="Residential or Commercial (grouped from DXBI property types)"
    ),
    property_type: Optional[str] = Query(default=None, description="DXBI property type"),
    bedrooms: Optional[str] = Query(default=None, description="'Studio', '1 Bed', '2 Beds', ..."),
    status: Optional[str] = Query(default=None, description="Off-Plan or Ready"),
    location: Optional[str] = Query(default=None, description="DXBI location (community)"),
    building: Optional[str] = Query(default=None, description="DXBI building name"),
    timeframe_days: Optional[int] = Query(
        default=None, ge=1, description="Last N calendar days, today included"
    ),
    size_min: Optional[float] = Query(default=None, description="Minimum size (sq ft), inclusive"),
    size_max: Optional[float] = Query(default=None, description="Maximum size (sq ft), exclusive"),
    price_min: Optional[float] = Query(default=None, description="Minimum price (AED), inclusive"),
    price_max: Optional[float] = Query(default=None, description="Maximum price (AED), exclusive"),
    price_per_sqft_min: Optional[float] = Query(
        default=None, description="Minimum price per sq ft (AED), inclusive"
    ),
    price_per_sqft_max: Optional[float] = Query(
        default=None, description="Maximum price per sq ft (AED), exclusive"
    ),
) -> SalesFilters:
    return SalesFilters(
        property_usage=property_usage,
        property_type=property_type,
        bedrooms=bedrooms,
        status=status,
        location=location,
        building=building,
        timeframe_days=timeframe_days,
        size_min=size_min,
        size_max=size_max,
        price_min=price_min,
        price_max=price_max,
        price_per_sqft_min=price_per_sqft_min,
        price_per_sqft_max=price_per_sqft_max,
    )


def rental_filters(
    property_usage: Optional[str] = Query(
        default=None, description="Residential or Commercial (grouped from DXBI property types)"
    ),
    property_type: Optional[str] = Query(default=None, description="DXBI property type"),
    bedrooms: Optional[str] = Query(default=None, description="'Studio', '1 Bed', '2 Beds', ..."),
    contract_type: Optional[str] = Query(default=None, description="New or Renewed"),
    location: Optional[str] = Query(default=None, description="DXBI location (community)"),
    building: Optional[str] = Query(default=None, description="DXBI building name"),
    timeframe_days: Optional[int] = Query(
        default=None,
        ge=1,
        description="Leases starting in the last N calendar days, today included",
    ),
    size_min: Optional[float] = Query(default=None, description="Minimum size (sq ft), inclusive"),
    size_max: Optional[float] = Query(default=None, description="Maximum size (sq ft), exclusive"),
    rent_min: Optional[float] = Query(
        default=None, description="Minimum annual rent (AED), inclusive"
    ),
    rent_max: Optional[float] = Query(
        default=None, description="Maximum annual rent (AED), exclusive"
    ),
) -> RentalFilters:
    return RentalFilters(
        property_usage=property_usage,
        property_type=property_type,
        bedrooms=bedrooms,
        contract_type=contract_type,
        location=location,
        building=building,
        timeframe_days=timeframe_days,
        size_min=size_min,
        size_max=size_max,
        rent_min=rent_min,
        rent_max=rent_max,
    )
