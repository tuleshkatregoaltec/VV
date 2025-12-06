"""Analytics API endpoints for pre-computed analytics data."""

from fastapi import APIRouter, Query, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.db.session import get_db_session
from backend.app.routers.dependencies import require_auth
from backend.app.schemas.analytics import (
    AnalyticsResponse,
    RentalAnalyticsResponse,
)
from backend.app.services.analytics_service import (
    fetch_sales_analytics,
    fetch_rental_analytics,
)

router = APIRouter(
    prefix="/api/v1/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_auth)],
)


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
