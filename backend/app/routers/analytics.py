"""Analytics API endpoints for pre-computed analytics data."""

from fastapi import APIRouter, Query, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.db.session import get_db_session
from backend.app.routers.dependencies import require_auth
from backend.app.schemas.analytics import (
    AnalyticsResponse,
    RentalAnalyticsResponse,
    AnalyticsSummary,
    RentalSummary,
    AnalyticsTrend,
    AreaBreakdown,
    RentalTrend,
    RentalAreaBreakdown,
)
from backend.app.services.analytics_service import (
    fetch_sales_analytics,
    fetch_rental_analytics,
    # Legacy functions
    fetch_sales_summary,
    fetch_sales_trends,
    fetch_sales_by_area,
    fetch_rentals_summary,
    fetch_rentals_trends,
    fetch_rentals_by_area,
)

router = APIRouter(
    prefix="/api/v1/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_auth)],
)


# =============================================================================
# NEW UNIFIED ENDPOINTS
# =============================================================================


@router.get("/sales", response_model=AnalyticsResponse)
async def get_sales_analytics(
    property_usage: str = Query(default="Residential"),
    timeframe_days: int = Query(default=30),
    master_project: str = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
):
    """Get complete sales analytics for dashboard.

    Returns summary KPIs, trends, and breakdowns by property_type, rooms, reg_type, and master_project.

    Timeframes: 7 (week), 30 (month), 90 (3 months), 180 (6 months), 365 (year)
    """
    return await fetch_sales_analytics(
        session=session,
        property_usage=property_usage,
        timeframe_days=timeframe_days,
        master_project=master_project,
    )


@router.get("/rentals", response_model=RentalAnalyticsResponse)
async def get_rental_analytics(
    property_usage: str = Query(default="Residential"),
    timeframe_days: int = Query(default=30),
    session: AsyncSession = Depends(get_db_session),
):
    """Get complete rental analytics for dashboard.

    Returns summary KPIs, trends, and breakdowns by property_type and master_project.

    Timeframes: 7 (week), 30 (month), 90 (3 months), 180 (6 months), 365 (year)
    """
    return await fetch_rental_analytics(
        session=session,
        property_usage=property_usage,
        timeframe_days=timeframe_days,
    )


# =============================================================================
# LEGACY ENDPOINTS (for backwards compatibility)
# =============================================================================


@router.get("/sales/summary", response_model=AnalyticsSummary)
async def get_sales_summary(
    property_usage: str = Query(default="Residential"),
    timeframe_days: int = Query(default=30, ge=7, le=365),
    session: AsyncSession = Depends(get_db_session),
):
    """Get summary KPI statistics for sales analytics."""
    return await fetch_sales_summary(
        session=session,
        timeframe_days=timeframe_days,
        property_usage=property_usage,
    )


@router.get("/sales/trends", response_model=list[AnalyticsTrend])
async def get_sales_trends(
    property_usage: str = Query(default="Residential"),
    timeframe_days: int = Query(default=30, ge=7, le=365),
    session: AsyncSession = Depends(get_db_session),
):
    """Get daily trend data for sales analytics charts."""
    return await fetch_sales_trends(
        session=session,
        timeframe_days=timeframe_days,
        property_usage=property_usage,
    )


@router.get("/sales/by-area", response_model=list[AreaBreakdown])
async def get_sales_by_area(
    property_usage: str = Query(default="Residential"),
    timeframe_days: int = Query(default=30, ge=7, le=365),
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
):
    """Get sales breakdown by master project (area)."""
    return await fetch_sales_by_area(
        session=session,
        timeframe_days=timeframe_days,
        limit=limit,
        property_usage=property_usage,
    )


@router.get("/rentals/summary", response_model=RentalSummary)
async def get_rentals_summary(
    property_usage: str = Query(default="Residential"),
    timeframe_days: int = Query(default=30, ge=7, le=365),
    session: AsyncSession = Depends(get_db_session),
):
    """Get summary KPI statistics for rental analytics."""
    return await fetch_rentals_summary(
        session=session,
        timeframe_days=timeframe_days,
        property_usage=property_usage,
    )


@router.get("/rentals/trends", response_model=list[RentalTrend])
async def get_rentals_trends(
    property_usage: str = Query(default="Residential"),
    timeframe_days: int = Query(default=30, ge=7, le=365),
    session: AsyncSession = Depends(get_db_session),
):
    """Get daily trend data for rental analytics charts."""
    return await fetch_rentals_trends(
        session=session,
        timeframe_days=timeframe_days,
        property_usage=property_usage,
    )


@router.get("/rentals/by-area", response_model=list[RentalAreaBreakdown])
async def get_rentals_by_area(
    property_usage: str = Query(default="Residential"),
    timeframe_days: int = Query(default=30, ge=7, le=365),
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
):
    """Get rental breakdown by master project (area)."""
    return await fetch_rentals_by_area(
        session=session,
        timeframe_days=timeframe_days,
        limit=limit,
        property_usage=property_usage,
    )
