"""Analytics service functions for pre-computed analytics queries."""

from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession
from datetime import timedelta
from typing import List, Optional
from decimal import Decimal

from backend.app.db.models.analytics import (
    AnalyticsSalesSummary,
    AnalyticsRentalsSummary,
    AnalyticsTrend,
    ANALYTICS_TIMEFRAMES,
)
from backend.app.schemas.analytics import (
    AnalyticsSummary,
    RentalSummary,
    DimensionBreakdown,
    RentalDimensionBreakdown,
    TrendPoint,
    AnalyticsResponse,
    RentalAnalyticsResponse,
)


def _safe_float(val: Optional[Decimal]) -> float:
    """Convert Decimal to float, handling None."""
    return float(val) if val else 0.0


def _calc_change_pct(current: float, previous: float) -> Optional[float]:
    """Calculate percentage change between periods."""
    if previous > 0:
        return round(((current - previous) / previous) * 100, 2)
    return None


def _validate_timeframe(timeframe_days: int) -> int:
    """Validate and normalize timeframe to allowed values."""
    if timeframe_days not in ANALYTICS_TIMEFRAMES:
        # Find closest valid timeframe
        return min(ANALYTICS_TIMEFRAMES, key=lambda x: abs(x - timeframe_days))
    return timeframe_days


# =============================================================================
# SALES ANALYTICS
# =============================================================================


async def fetch_sales_analytics(
    session: AsyncSession,
    property_usage: str = "Residential",
    timeframe_days: int = 30,
    master_project: Optional[str] = None,
) -> AnalyticsResponse:
    """Fetch complete sales analytics for dashboard."""

    timeframe_days = _validate_timeframe(timeframe_days)

    # If filtering by master_project, fetch from dimension breakdown
    if master_project:
        summary_stmt = select(AnalyticsSalesSummary).where(
            AnalyticsSalesSummary.property_usage == property_usage,
            AnalyticsSalesSummary.timeframe_days == timeframe_days,
            AnalyticsSalesSummary.dimension == "master_project",
            AnalyticsSalesSummary.dimension_value == master_project,
        )
    else:
        # Fetch summary (base aggregation where dimension is NULL)
        summary_stmt = select(AnalyticsSalesSummary).where(
            AnalyticsSalesSummary.property_usage == property_usage,
            AnalyticsSalesSummary.timeframe_days == timeframe_days,
            AnalyticsSalesSummary.dimension == None,  # noqa: E711
        )
    result = await session.exec(summary_stmt)
    summary_row = result.first()

    if summary_row:
        summary = AnalyticsSummary(
            transaction_count=summary_row.transaction_count,
            total_volume=_safe_float(summary_row.total_volume),
            avg_price=_safe_float(summary_row.avg_price),
            avg_price_sqft=_safe_float(summary_row.avg_price_sqft),
            min_price=_safe_float(summary_row.min_price),
            max_price=_safe_float(summary_row.max_price),
            volume_change_pct=_calc_change_pct(
                _safe_float(summary_row.total_volume),
                _safe_float(summary_row.prev_total_volume),
            ),
            count_change_pct=_calc_change_pct(
                summary_row.transaction_count,
                summary_row.prev_transaction_count,
            ),
        )
    else:
        summary = AnalyticsSummary(
            transaction_count=0,
            total_volume=0,
            avg_price=0,
            avg_price_sqft=0,
            min_price=0,
            max_price=0,
        )

    # Fetch trends
    trends = await _fetch_sales_trends(session, property_usage, timeframe_days)

    # Fetch dimension breakdowns
    # Note: When filtering by master_project, we can't break down further by property_type etc.
    # since we don't have cross-dimensional data. We return empty lists.
    if master_project:
        by_property_type = []
        by_rooms = []
        by_reg_type = []
        by_master_project = await _fetch_sales_breakdown(
            session,
            property_usage,
            timeframe_days,
            "master_project",
            filter_value=master_project,
        )
    else:
        by_property_type = await _fetch_sales_breakdown(
            session, property_usage, timeframe_days, "property_type"
        )
        by_rooms = await _fetch_sales_breakdown(
            session, property_usage, timeframe_days, "rooms"
        )
        by_reg_type = await _fetch_sales_breakdown(
            session, property_usage, timeframe_days, "reg_type"
        )
        by_master_project = await _fetch_sales_breakdown(
            session, property_usage, timeframe_days, "master_project"
        )

    return AnalyticsResponse(
        timeframe_days=timeframe_days,
        property_usage=property_usage,
        summary=summary,
        trends=trends,
        by_property_type=by_property_type,
        by_rooms=by_rooms,
        by_reg_type=by_reg_type,
        by_master_project=by_master_project,
    )


async def _fetch_sales_trends(
    session: AsyncSession,
    property_usage: str,
    timeframe_days: int,
) -> List[TrendPoint]:
    """Fetch daily trend data for sales."""
    from datetime import date, datetime

    end_date = date.today()
    start_date = end_date - timedelta(days=timeframe_days)

    stmt = (
        select(AnalyticsTrend)
        .where(
            AnalyticsTrend.property_usage == property_usage,
            AnalyticsTrend.trend_type == "sales",
            AnalyticsTrend.trend_date
            >= datetime.combine(start_date, datetime.min.time()),
            AnalyticsTrend.trend_date < datetime.combine(end_date, datetime.min.time()),
        )
        .order_by(AnalyticsTrend.trend_date)
    )

    result = await session.exec(stmt)
    rows = result.all()

    return [
        TrendPoint(
            date=row.trend_date.date()
            if hasattr(row.trend_date, "date")
            else row.trend_date,
            count=row.count,
            total_value=_safe_float(row.total_value),
            avg_value=_safe_float(row.avg_value),
            avg_sqft=_safe_float(row.avg_sqft),
        )
        for row in rows
    ]


async def _fetch_sales_breakdown(
    session: AsyncSession,
    property_usage: str,
    timeframe_days: int,
    dimension: str,
    limit: int = 10,
    filter_value: Optional[str] = None,
) -> List[DimensionBreakdown]:
    """Fetch breakdown by a specific dimension."""

    stmt = select(AnalyticsSalesSummary).where(
        AnalyticsSalesSummary.property_usage == property_usage,
        AnalyticsSalesSummary.timeframe_days == timeframe_days,
        AnalyticsSalesSummary.dimension == dimension,
    )

    if filter_value:
        stmt = stmt.where(AnalyticsSalesSummary.dimension_value == filter_value)

    stmt = stmt.order_by(col(AnalyticsSalesSummary.total_volume).desc()).limit(limit)

    result = await session.exec(stmt)
    rows = result.all()

    # Calculate total for percentage
    total_volume = sum(_safe_float(row.total_volume) for row in rows)

    return [
        DimensionBreakdown(
            dimension_value=row.dimension_value or "",
            transaction_count=row.transaction_count,
            total_volume=_safe_float(row.total_volume),
            avg_price_sqft=_safe_float(row.avg_price_sqft),
            pct_of_total=round((_safe_float(row.total_volume) / total_volume) * 100, 1)
            if total_volume > 0
            else None,
        )
        for row in rows
        if row.dimension_value
    ]


# =============================================================================
# RENTAL ANALYTICS
# =============================================================================


async def fetch_rental_analytics(
    session: AsyncSession,
    property_usage: str = "Residential",
    timeframe_days: int = 30,
) -> RentalAnalyticsResponse:
    """Fetch complete rental analytics for dashboard."""

    timeframe_days = _validate_timeframe(timeframe_days)

    # Fetch summary
    summary_stmt = select(AnalyticsRentalsSummary).where(
        AnalyticsRentalsSummary.property_usage == property_usage,
        AnalyticsRentalsSummary.timeframe_days == timeframe_days,
        AnalyticsRentalsSummary.dimension == None,  # noqa: E711
    )
    result = await session.exec(summary_stmt)
    summary_row = result.first()

    if summary_row:
        summary = RentalSummary(
            contract_count=summary_row.contract_count,
            total_annual_value=_safe_float(summary_row.total_annual_value),
            avg_annual_rent=_safe_float(summary_row.avg_annual_rent),
            avg_rent_sqft=_safe_float(summary_row.avg_rent_sqft),
            min_annual_rent=_safe_float(summary_row.min_annual_rent),
            max_annual_rent=_safe_float(summary_row.max_annual_rent),
            value_change_pct=_calc_change_pct(
                _safe_float(summary_row.total_annual_value),
                _safe_float(summary_row.prev_total_annual_value),
            ),
            count_change_pct=_calc_change_pct(
                summary_row.contract_count,
                summary_row.prev_contract_count,
            ),
        )
    else:
        summary = RentalSummary(
            contract_count=0,
            total_annual_value=0,
            avg_annual_rent=0,
            avg_rent_sqft=0,
            min_annual_rent=0,
            max_annual_rent=0,
        )

    # Fetch trends
    trends = await _fetch_rental_trends(session, property_usage, timeframe_days)

    # Fetch dimension breakdowns
    by_property_type = await _fetch_rental_breakdown(
        session, property_usage, timeframe_days, "property_type"
    )
    by_master_project = await _fetch_rental_breakdown(
        session, property_usage, timeframe_days, "master_project"
    )

    return RentalAnalyticsResponse(
        timeframe_days=timeframe_days,
        property_usage=property_usage,
        summary=summary,
        trends=trends,
        by_property_type=by_property_type,
        by_master_project=by_master_project,
    )


async def _fetch_rental_trends(
    session: AsyncSession,
    property_usage: str,
    timeframe_days: int,
) -> List[TrendPoint]:
    """Fetch daily trend data for rentals."""
    from datetime import date, datetime

    end_date = date.today()
    start_date = end_date - timedelta(days=timeframe_days)

    stmt = (
        select(AnalyticsTrend)
        .where(
            AnalyticsTrend.property_usage == property_usage,
            AnalyticsTrend.trend_type == "rentals",
            AnalyticsTrend.trend_date
            >= datetime.combine(start_date, datetime.min.time()),
            AnalyticsTrend.trend_date < datetime.combine(end_date, datetime.min.time()),
        )
        .order_by(AnalyticsTrend.trend_date)
    )

    result = await session.exec(stmt)
    rows = result.all()

    return [
        TrendPoint(
            date=row.trend_date.date()
            if hasattr(row.trend_date, "date")
            else row.trend_date,
            count=row.count,
            total_value=_safe_float(row.total_value),
            avg_value=_safe_float(row.avg_value),
            avg_sqft=_safe_float(row.avg_sqft),
        )
        for row in rows
    ]


async def _fetch_rental_breakdown(
    session: AsyncSession,
    property_usage: str,
    timeframe_days: int,
    dimension: str,
    limit: int = 10,
) -> List[RentalDimensionBreakdown]:
    """Fetch breakdown by a specific dimension."""

    stmt = (
        select(AnalyticsRentalsSummary)
        .where(
            AnalyticsRentalsSummary.property_usage == property_usage,
            AnalyticsRentalsSummary.timeframe_days == timeframe_days,
            AnalyticsRentalsSummary.dimension == dimension,
        )
        .order_by(col(AnalyticsRentalsSummary.total_annual_value).desc())
        .limit(limit)
    )

    result = await session.exec(stmt)
    rows = result.all()

    total_value = sum(_safe_float(row.total_annual_value) for row in rows)

    return [
        RentalDimensionBreakdown(
            dimension_value=row.dimension_value or "",
            contract_count=row.contract_count,
            total_annual_value=_safe_float(row.total_annual_value),
            avg_rent_sqft=_safe_float(row.avg_rent_sqft),
            pct_of_total=round(
                (_safe_float(row.total_annual_value) / total_value) * 100, 1
            )
            if total_value > 0
            else None,
        )
        for row in rows
        if row.dimension_value
    ]


# =============================================================================
# LEGACY FUNCTIONS (for backwards compatibility)
# =============================================================================

# Keep old imports working
from backend.app.schemas.analytics import (
    AnalyticsTrend as AnalyticsTrendSchema,
    AreaBreakdown,
    RentalTrend,
    RentalAreaBreakdown,
)


async def fetch_sales_summary(
    session: AsyncSession, timeframe_days: int = 30, **filters
) -> AnalyticsSummary:
    """Legacy function - use fetch_sales_analytics instead."""
    property_usage = filters.get("property_usage", "Residential")
    response = await fetch_sales_analytics(session, property_usage, timeframe_days)
    return response.summary


async def fetch_sales_trends(
    session: AsyncSession, timeframe_days: int = 30, **filters
) -> List[AnalyticsTrendSchema]:
    """Legacy function - use fetch_sales_analytics instead."""
    property_usage = filters.get("property_usage", "Residential")
    trends = await _fetch_sales_trends(session, property_usage, timeframe_days)
    return [
        AnalyticsTrendSchema(
            date=t.date,
            transaction_count=t.count,
            total_volume=t.total_value,
            avg_price=t.avg_value,
            avg_price_sqft=t.avg_sqft,
        )
        for t in trends
    ]


async def fetch_sales_by_area(
    session: AsyncSession, timeframe_days: int = 30, limit: int = 10, **filters
) -> List[AreaBreakdown]:
    """Legacy function - returns master_project breakdown as 'area'."""
    property_usage = filters.get("property_usage", "Residential")
    breakdown = await _fetch_sales_breakdown(
        session, property_usage, timeframe_days, "master_project", limit
    )
    return [
        AreaBreakdown(
            area_name=b.dimension_value,
            transaction_count=b.transaction_count,
            total_volume=b.total_volume,
            avg_price_sqft=b.avg_price_sqft,
            pct_of_total=b.pct_of_total,
        )
        for b in breakdown
    ]


async def fetch_rentals_summary(
    session: AsyncSession, timeframe_days: int = 30, **filters
) -> RentalSummary:
    """Legacy function - use fetch_rental_analytics instead."""
    property_usage = filters.get("property_usage", "Residential")
    response = await fetch_rental_analytics(session, property_usage, timeframe_days)
    return response.summary


async def fetch_rentals_trends(
    session: AsyncSession, timeframe_days: int = 30, **filters
) -> List[RentalTrend]:
    """Legacy function - use fetch_rental_analytics instead."""
    property_usage = filters.get("property_usage", "Residential")
    trends = await _fetch_rental_trends(session, property_usage, timeframe_days)
    return [
        RentalTrend(
            date=t.date,
            contract_count=t.count,
            total_annual_value=t.total_value,
            avg_annual_rent=t.avg_value,
            avg_rent_sqft=t.avg_sqft,
        )
        for t in trends
    ]


async def fetch_rentals_by_area(
    session: AsyncSession, timeframe_days: int = 30, limit: int = 10, **filters
) -> List[RentalAreaBreakdown]:
    """Legacy function - returns master_project breakdown as 'area'."""
    property_usage = filters.get("property_usage", "Residential")
    breakdown = await _fetch_rental_breakdown(
        session, property_usage, timeframe_days, "master_project", limit
    )
    return [
        RentalAreaBreakdown(
            area_name=b.dimension_value,
            contract_count=b.contract_count,
            total_annual_value=b.total_annual_value,
            avg_rent_sqft=b.avg_rent_sqft,
            pct_of_total=b.pct_of_total,
        )
        for b in breakdown
    ]
