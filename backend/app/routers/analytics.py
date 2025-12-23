"""Analytics API endpoints with flexible filtering from daily aggregates."""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.db.session import get_db_session
from backend.app.routers.dependencies import require_auth
from backend.app.schemas.analytics import (
    AnalyticsResponse,
    RentalAnalyticsResponse,
)
from backend.app.services.analytics_service import (
    fetch_rental_analytics,
    fetch_sales_analytics,
)

router = APIRouter(
    prefix="/api/v1/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_auth)],
)


@router.get("/sales", response_model=AnalyticsResponse)
async def get_sales_analytics(
    property_usage: str = Query(default="Residential", description="Residential or Commercial"),
    timeframe_days: Optional[int] = Query(default=None, description="Number of days to look back (overrides start_date if provided)"),
    start_date: Optional[date] = Query(default=None, description="Explicit start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(default=None, description="Explicit end date (YYYY-MM-DD), defaults to today"),
    master_project: Optional[str] = Query(default=None, description="Filter by master project name"),
    property_type: Optional[str] = Query(default=None, description="Filter by property type"),
    rooms: Optional[str] = Query(default=None, description="Filter by room count"),
    reg_type: Optional[str] = Query(default=None, description="Filter by registration type"),
    price_bucket: Optional[str] = Query(default=None, description="Filter by price bucket (e.g., '1M-2M')"),
    area_bucket: Optional[str] = Query(default=None, description="Filter by area bucket (e.g., '1K-2K')"),
    db: AsyncSession = Depends(get_db_session),
):
    """Get sales analytics with flexible filtering and custom date ranges.

    Supports:
    - Custom date ranges (use start_date/end_date or timeframe_days)
    - Multi-dimensional filtering (combine property_type, rooms, location, price ranges)
    - Bucketed filtering (price ranges, area ranges)

    Examples:
    - Last 30 days: ?timeframe_days=30
    - Custom range: ?start_date=2024-01-01&end_date=2024-12-31
    - Filtered: ?timeframe_days=90&master_project=Dubai Marina&price_bucket=1M-2M
    """
    return await fetch_sales_analytics(
        db=db,
        property_usage=property_usage,
        timeframe_days=timeframe_days,
        start_date=start_date,
        end_date=end_date,
        master_project=master_project,
        property_type=property_type,
        rooms=rooms,
        reg_type=reg_type,
        price_bucket=price_bucket,
        area_bucket=area_bucket,
    )


@router.get("/rentals", response_model=RentalAnalyticsResponse)
async def get_rental_analytics(
    property_usage: str = Query(default="Residential", description="Residential or Commercial"),
    timeframe_days: Optional[int] = Query(default=None, description="Number of days to look back (overrides start_date if provided)"),
    start_date: Optional[date] = Query(default=None, description="Explicit start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(default=None, description="Explicit end date (YYYY-MM-DD), defaults to today"),
    master_project: Optional[str] = Query(default=None, description="Filter by master project name"),
    property_type: Optional[str] = Query(default=None, description="Filter by property type"),
    rent_bucket: Optional[str] = Query(default=None, description="Filter by rent bucket (e.g., '100K-200K')"),
    area_bucket: Optional[str] = Query(default=None, description="Filter by area bucket (e.g., '1K-2K')"),
    db: AsyncSession = Depends(get_db_session),
):
    """Get rental analytics with flexible filtering and custom date ranges.

    Supports:
    - Custom date ranges (use start_date/end_date or timeframe_days)
    - Multi-dimensional filtering (combine property_type, location, rent ranges)
    - Bucketed filtering (rent ranges, area ranges)

    Examples:
    - Last 90 days: ?timeframe_days=90
    - Custom range: ?start_date=2024-06-01&end_date=2024-08-31
    - Filtered: ?property_usage=Commercial&rent_bucket=200K-500K
    """
    return await fetch_rental_analytics(
        db=db,
        property_usage=property_usage,
        timeframe_days=timeframe_days,
        start_date=start_date,
        end_date=end_date,
        master_project=master_project,
        property_type=property_type,
        rent_bucket=rent_bucket,
        area_bucket=area_bucket,
    )
