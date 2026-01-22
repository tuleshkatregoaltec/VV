"""Analytics service functions for query-time aggregation from daily aggregates."""

from sqlmodel import select, func, and_, col
from sqlmodel.ext.asyncio.session import AsyncSession
from datetime import date, datetime, timedelta
from typing import List, Optional
from decimal import Decimal


from app.postgres.models.analytics import (
    AnalyticsDailySalesAgg,
    AnalyticsDailyRentalsAgg,
)
from app.schemas.analytics import (
    AnalyticsSummary,
    RentalSummary,
    DimensionBreakdown,
    RentalDimensionBreakdown,
    TrendPoint,
    AnalyticsResponse,
    RentalAnalyticsResponse,
)


def _safe_float(decimal_value: Optional[Decimal]) -> float:
    """Convert Decimal to float, handling None."""
    return float(decimal_value) if decimal_value else 0.0


def _calc_change_pct(current: float, previous: float) -> Optional[float]:
    """Calculate percentage change between periods."""
    if previous > 0:
        return round(((current - previous) / previous) * 100, 2)
    return None


# =============================================================================
# SALES ANALYTICS
# =============================================================================


async def fetch_sales_analytics(
    db: AsyncSession,
    property_usage: str = "Residential",
    timeframe_days: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    master_project: Optional[str] = None,
    property_type: Optional[str] = None,
    rooms: Optional[str] = None,
    reg_type: Optional[str] = None,
    price_bucket: Optional[str] = None,
    area_bucket: Optional[str] = None,
) -> AnalyticsResponse:
    """Fetch complete sales analytics with flexible filtering from daily aggregates.

    Args:
        db: Database session
        property_usage: Residential or Commercial
        timeframe_days: Number of days to look back (if provided, overrides start_date)
        start_date: Explicit start date
        end_date: Explicit end date (defaults to today)
        master_project: Filter by master project
        property_type: Filter by property type
        rooms: Filter by room count
        reg_type: Filter by registration type
        price_bucket: Filter by price bucket
        area_bucket: Filter by area bucket

    Returns:
        Complete analytics response with summary, trends, and breakdowns
    """
    # Determine date range
    if not end_date:
        end_date = date.today()
    if timeframe_days:
        start_date = end_date - timedelta(days=timeframe_days)
    elif not start_date:
        # Default to 30 days if no date parameters provided
        timeframe_days = 30
        start_date = end_date - timedelta(days=30)
    else:
        # Calculate timeframe from provided dates
        timeframe_days = (end_date - start_date).days

    # Build base filter
    filters = [
        AnalyticsDailySalesAgg.agg_date >= start_date,
        AnalyticsDailySalesAgg.agg_date < end_date,
        AnalyticsDailySalesAgg.property_usage == property_usage,
    ]

    # Add optional filters for multi-dimensional filtering
    if master_project:
        filters.append(AnalyticsDailySalesAgg.master_project == master_project)
    if property_type:
        filters.append(AnalyticsDailySalesAgg.property_type == property_type)
    if rooms:
        filters.append(AnalyticsDailySalesAgg.rooms == rooms)
    if reg_type:
        filters.append(AnalyticsDailySalesAgg.reg_type == reg_type)
    if price_bucket:
        filters.append(AnalyticsDailySalesAgg.price_bucket == price_bucket)
    if area_bucket:
        filters.append(AnalyticsDailySalesAgg.area_bucket == area_bucket)

    # Aggregate across filtered daily rows
    summary_query = select(
        func.sum(AnalyticsDailySalesAgg.transaction_count).label("transaction_count"),
        func.sum(AnalyticsDailySalesAgg.total_volume).label("total_volume"),
        func.sum(AnalyticsDailySalesAgg.sum_price).label("sum_price"),
        func.sum(AnalyticsDailySalesAgg.sum_area).label("sum_area"),
        func.sum(AnalyticsDailySalesAgg.sum_price_x_area).label("sum_price_x_area"),
        func.min(AnalyticsDailySalesAgg.min_price).label("min_price"),
        func.max(AnalyticsDailySalesAgg.max_price).label("max_price"),
    ).where(and_(*filters))

    result = await db.exec(summary_query)
    row = result.first()

    if row and row.transaction_count:
        # Calculate weighted average price per sqft
        avg_price_sqft = (
            _safe_float(row.sum_price_x_area) / _safe_float(row.sum_area)
            if row.sum_area and _safe_float(row.sum_area) > 0
            else 0
        )

        summary = AnalyticsSummary(
            transaction_count=row.transaction_count,
            total_volume=_safe_float(row.total_volume),
            avg_price=_safe_float(row.sum_price) / row.transaction_count
            if row.transaction_count > 0
            else 0,
            avg_price_sqft=avg_price_sqft,
            min_price=_safe_float(row.min_price),
            max_price=_safe_float(row.max_price),
        )

        # Calculate period-over-period change
        prev_start = start_date - timedelta(days=(end_date - start_date).days)
        prev_end = start_date
        prev_summary = await _fetch_period_summary(db, filters, prev_start, prev_end)

        if prev_summary["total_volume"] > 0:
            summary.volume_change_pct = _calc_change_pct(
                summary.total_volume, prev_summary["total_volume"]
            )
        if prev_summary["transaction_count"] > 0:
            summary.count_change_pct = _calc_change_pct(
                summary.transaction_count, prev_summary["transaction_count"]
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
    trends = await _fetch_sales_trends(db, filters, start_date, end_date)

    # Fetch dimension breakdowns
    # Only fetch breakdowns for dimensions not currently being filtered
    by_property_type = (
        []
        if property_type
        else await _fetch_sales_breakdown(
            db, filters, start_date, end_date, "property_type"
        )
    )
    by_rooms = (
        []
        if rooms
        else await _fetch_sales_breakdown(db, filters, start_date, end_date, "rooms")
    )
    by_reg_type = (
        []
        if reg_type
        else await _fetch_sales_breakdown(db, filters, start_date, end_date, "reg_type")
    )
    by_master_project = (
        []
        if master_project
        else await _fetch_sales_breakdown(
            db, filters, start_date, end_date, "master_project", limit=20
        )
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


async def _fetch_period_summary(
    db: AsyncSession,
    base_filters: list,
    start_date: date,
    end_date: date,
) -> dict:
    """Fetch summary for a previous period for comparison.

    Args:
        db: Database session
        base_filters: Base filters to apply (excluding date filters)
        start_date: Period start date
        end_date: Period end date

    Returns:
        Dictionary with transaction_count and total_volume
    """
    # Replace date filter in base_filters
    period_filters = [
        f
        for f in base_filters
        if not (
            hasattr(f, "left") and hasattr(f.left, "key") and f.left.key == "agg_date"
        )
    ]
    period_filters.extend(
        [
            AnalyticsDailySalesAgg.agg_date >= start_date,
            AnalyticsDailySalesAgg.agg_date < end_date,
        ]
    )

    query = select(
        func.sum(AnalyticsDailySalesAgg.transaction_count).label("transaction_count"),
        func.sum(AnalyticsDailySalesAgg.total_volume).label("total_volume"),
    ).where(and_(*period_filters))

    result = await db.exec(query)
    row = result.first()

    return {
        "transaction_count": row.transaction_count or 0 if row else 0,
        "total_volume": _safe_float(row.total_volume) if row else 0,
    }


async def _fetch_sales_trends(
    db: AsyncSession,
    base_filters: list,
    start_date: date,
    end_date: date,
) -> List[TrendPoint]:
    """Fetch daily trend data from daily aggregates.

    Args:
        db: Database session
        base_filters: Base filters to apply
        start_date: Start date
        end_date: End date

    Returns:
        List of trend points with daily metrics
    """
    query = (
        select(
            AnalyticsDailySalesAgg.agg_date,
            func.sum(AnalyticsDailySalesAgg.transaction_count).label("count"),
            func.sum(AnalyticsDailySalesAgg.total_volume).label("total_value"),
            func.sum(AnalyticsDailySalesAgg.sum_price).label("sum_price"),
            func.sum(AnalyticsDailySalesAgg.sum_price_x_area).label("sum_price_x_area"),
            func.sum(AnalyticsDailySalesAgg.sum_area).label("sum_area"),
        )
        .where(and_(*base_filters))
        .group_by(AnalyticsDailySalesAgg.agg_date)
        .order_by(AnalyticsDailySalesAgg.agg_date)
    )

    result = await db.exec(query)
    rows = result.all()

    trends = []
    for row in rows:
        avg_value = _safe_float(row.sum_price) / row.count if row.count > 0 else 0
        avg_sqft = (
            _safe_float(row.sum_price_x_area) / _safe_float(row.sum_area)
            if row.sum_area and _safe_float(row.sum_area) > 0
            else 0
        )

        trends.append(
            TrendPoint(
                date=row.agg_date,
                count=row.count,
                total_value=_safe_float(row.total_value),
                avg_value=avg_value,
                avg_sqft=avg_sqft,
            )
        )

    return trends


async def _fetch_sales_breakdown(
    db: AsyncSession,
    base_filters: list,
    start_date: date,
    end_date: date,
    dimension: str,
    limit: int = 10,
) -> List[DimensionBreakdown]:
    """Fetch breakdown by a specific dimension from daily aggregates.

    Args:
        db: Database session
        base_filters: Base filters to apply
        start_date: Start date
        end_date: End date
        dimension: Dimension column to group by (property_type, rooms, etc.)
        limit: Maximum number of results

    Returns:
        List of dimension breakdowns
    """
    dim_column = getattr(AnalyticsDailySalesAgg, dimension)

    # Aggregate by dimension
    query = (
        select(
            dim_column.label("dimension_value"),
            func.sum(AnalyticsDailySalesAgg.transaction_count).label(
                "transaction_count"
            ),
            func.sum(AnalyticsDailySalesAgg.total_volume).label("total_volume"),
            func.sum(AnalyticsDailySalesAgg.sum_price_x_area).label("sum_price_x_area"),
            func.sum(AnalyticsDailySalesAgg.sum_area).label("sum_area"),
        )
        .where(
            and_(*base_filters),
            dim_column.is_not(None),
        )
        .group_by(dim_column)
        .order_by(func.sum(AnalyticsDailySalesAgg.total_volume).desc())
        .limit(limit)
    )

    result = await db.exec(query)
    rows = result.all()

    # Calculate total for percentages
    total_volume = sum(_safe_float(r.total_volume) for r in rows)

    breakdowns = []
    for row in rows:
        avg_price_sqft = (
            _safe_float(row.sum_price_x_area) / _safe_float(row.sum_area)
            if row.sum_area and _safe_float(row.sum_area) > 0
            else 0
        )

        breakdowns.append(
            DimensionBreakdown(
                dimension_value=row.dimension_value or "",
                transaction_count=row.transaction_count,
                total_volume=_safe_float(row.total_volume),
                avg_price_sqft=avg_price_sqft,
                pct_of_total=round(
                    (_safe_float(row.total_volume) / total_volume) * 100, 1
                )
                if total_volume > 0
                else None,
            )
        )

    return breakdowns


# =============================================================================
# RENTAL ANALYTICS
# =============================================================================


async def fetch_rental_analytics(
    db: AsyncSession,
    property_usage: str = "Residential",
    timeframe_days: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    master_project: Optional[str] = None,
    property_type: Optional[str] = None,
    rent_bucket: Optional[str] = None,
    area_bucket: Optional[str] = None,
) -> RentalAnalyticsResponse:
    """Fetch complete rental analytics with flexible filtering from daily aggregates.

    Args:
        db: Database session
        property_usage: Residential or Commercial
        timeframe_days: Number of days to look back (if provided, overrides start_date)
        start_date: Explicit start date
        end_date: Explicit end date (defaults to today)
        master_project: Filter by master project
        property_type: Filter by property type
        rent_bucket: Filter by rent bucket
        area_bucket: Filter by area bucket

    Returns:
        Complete rental analytics response
    """
    # Determine date range
    if not end_date:
        end_date = date.today()
    if timeframe_days:
        start_date = end_date - timedelta(days=timeframe_days)
    elif not start_date:
        # Default to 30 days
        timeframe_days = 30
        start_date = end_date - timedelta(days=30)
    else:
        timeframe_days = (end_date - start_date).days

    # Build base filter
    filters = [
        AnalyticsDailyRentalsAgg.agg_date >= start_date,
        AnalyticsDailyRentalsAgg.agg_date < end_date,
        AnalyticsDailyRentalsAgg.property_usage == property_usage,
    ]

    # Add optional filters
    if master_project:
        filters.append(AnalyticsDailyRentalsAgg.master_project == master_project)
    if property_type:
        filters.append(AnalyticsDailyRentalsAgg.property_type == property_type)
    if rent_bucket:
        filters.append(AnalyticsDailyRentalsAgg.rent_bucket == rent_bucket)
    if area_bucket:
        filters.append(AnalyticsDailyRentalsAgg.area_bucket == area_bucket)

    # Aggregate across filtered daily rows
    summary_query = select(
        func.sum(AnalyticsDailyRentalsAgg.contract_count).label("contract_count"),
        func.sum(AnalyticsDailyRentalsAgg.total_annual_value).label(
            "total_annual_value"
        ),
        func.sum(AnalyticsDailyRentalsAgg.sum_rent).label("sum_rent"),
        func.sum(AnalyticsDailyRentalsAgg.sum_area).label("sum_area"),
        func.sum(AnalyticsDailyRentalsAgg.sum_rent_x_area).label("sum_rent_x_area"),
        func.min(AnalyticsDailyRentalsAgg.min_annual_rent).label("min_annual_rent"),
        func.max(AnalyticsDailyRentalsAgg.max_annual_rent).label("max_annual_rent"),
    ).where(and_(*filters))

    result = await db.exec(summary_query)
    row = result.first()

    if row and row.contract_count:
        # Calculate weighted average rent per sqft
        avg_rent_sqft = (
            _safe_float(row.sum_rent_x_area) / _safe_float(row.sum_area)
            if row.sum_area and _safe_float(row.sum_area) > 0
            else 0
        )

        summary = RentalSummary(
            contract_count=row.contract_count,
            total_annual_value=_safe_float(row.total_annual_value),
            avg_annual_rent=_safe_float(row.sum_rent) / row.contract_count
            if row.contract_count > 0
            else 0,
            avg_rent_sqft=avg_rent_sqft,
            min_annual_rent=_safe_float(row.min_annual_rent),
            max_annual_rent=_safe_float(row.max_annual_rent),
        )

        # Calculate period-over-period change
        prev_start = start_date - timedelta(days=(end_date - start_date).days)
        prev_end = start_date
        prev_summary = await _fetch_rental_period_summary(
            db, filters, prev_start, prev_end
        )

        if prev_summary["total_annual_value"] > 0:
            summary.value_change_pct = _calc_change_pct(
                summary.total_annual_value, prev_summary["total_annual_value"]
            )
        if prev_summary["contract_count"] > 0:
            summary.count_change_pct = _calc_change_pct(
                summary.contract_count, prev_summary["contract_count"]
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
    trends = await _fetch_rental_trends(db, filters, start_date, end_date)

    # Fetch dimension breakdowns (only for dimensions not being filtered)
    by_property_type = (
        []
        if property_type
        else await _fetch_rental_breakdown(
            db, filters, start_date, end_date, "property_type"
        )
    )
    by_master_project = (
        []
        if master_project
        else await _fetch_rental_breakdown(
            db, filters, start_date, end_date, "master_project", limit=20
        )
    )

    return RentalAnalyticsResponse(
        timeframe_days=timeframe_days,
        property_usage=property_usage,
        summary=summary,
        trends=trends,
        by_property_type=by_property_type,
        by_master_project=by_master_project,
    )


async def _fetch_rental_period_summary(
    db: AsyncSession,
    base_filters: list,
    start_date: date,
    end_date: date,
) -> dict:
    """Fetch rental summary for a previous period for comparison."""
    # Replace date filter in base_filters
    period_filters = [
        f
        for f in base_filters
        if not (
            hasattr(f, "left") and hasattr(f.left, "key") and f.left.key == "agg_date"
        )
    ]
    period_filters.extend(
        [
            AnalyticsDailyRentalsAgg.agg_date >= start_date,
            AnalyticsDailyRentalsAgg.agg_date < end_date,
        ]
    )

    query = select(
        func.sum(AnalyticsDailyRentalsAgg.contract_count).label("contract_count"),
        func.sum(AnalyticsDailyRentalsAgg.total_annual_value).label(
            "total_annual_value"
        ),
    ).where(and_(*period_filters))

    result = await db.exec(query)
    row = result.first()

    return {
        "contract_count": row.contract_count or 0 if row else 0,
        "total_annual_value": _safe_float(row.total_annual_value) if row else 0,
    }


async def _fetch_rental_trends(
    db: AsyncSession,
    base_filters: list,
    start_date: date,
    end_date: date,
) -> List[TrendPoint]:
    """Fetch daily rental trend data from daily aggregates."""
    query = (
        select(
            AnalyticsDailyRentalsAgg.agg_date,
            func.sum(AnalyticsDailyRentalsAgg.contract_count).label("count"),
            func.sum(AnalyticsDailyRentalsAgg.total_annual_value).label("total_value"),
            func.sum(AnalyticsDailyRentalsAgg.sum_rent).label("sum_rent"),
            func.sum(AnalyticsDailyRentalsAgg.sum_rent_x_area).label("sum_rent_x_area"),
            func.sum(AnalyticsDailyRentalsAgg.sum_area).label("sum_area"),
        )
        .where(and_(*base_filters))
        .group_by(AnalyticsDailyRentalsAgg.agg_date)
        .order_by(AnalyticsDailyRentalsAgg.agg_date)
    )

    result = await db.exec(query)
    rows = result.all()

    trends = []
    for row in rows:
        avg_value = _safe_float(row.sum_rent) / row.count if row.count > 0 else 0
        avg_sqft = (
            _safe_float(row.sum_rent_x_area) / _safe_float(row.sum_area)
            if row.sum_area and _safe_float(row.sum_area) > 0
            else 0
        )

        trends.append(
            TrendPoint(
                date=row.agg_date,
                count=row.count,
                total_value=_safe_float(row.total_value),
                avg_value=avg_value,
                avg_sqft=avg_sqft,
            )
        )

    return trends


async def _fetch_rental_breakdown(
    db: AsyncSession,
    base_filters: list,
    start_date: date,
    end_date: date,
    dimension: str,
    limit: int = 10,
) -> List[RentalDimensionBreakdown]:
    """Fetch rental breakdown by a specific dimension from daily aggregates."""
    dim_column = getattr(AnalyticsDailyRentalsAgg, dimension)

    # Aggregate by dimension
    query = (
        select(
            dim_column.label("dimension_value"),
            func.sum(AnalyticsDailyRentalsAgg.contract_count).label("contract_count"),
            func.sum(AnalyticsDailyRentalsAgg.total_annual_value).label(
                "total_annual_value"
            ),
            func.sum(AnalyticsDailyRentalsAgg.sum_rent_x_area).label("sum_rent_x_area"),
            func.sum(AnalyticsDailyRentalsAgg.sum_area).label("sum_area"),
        )
        .where(
            and_(*base_filters),
            dim_column.is_not(None),
        )
        .group_by(dim_column)
        .order_by(func.sum(AnalyticsDailyRentalsAgg.total_annual_value).desc())
        .limit(limit)
    )

    result = await db.exec(query)
    rows = result.all()

    # Calculate total for percentages
    total_value = sum(_safe_float(r.total_annual_value) for r in rows)

    breakdowns = []
    for row in rows:
        avg_rent_sqft = (
            _safe_float(row.sum_rent_x_area) / _safe_float(row.sum_area)
            if row.sum_area and _safe_float(row.sum_area) > 0
            else 0
        )

        breakdowns.append(
            RentalDimensionBreakdown(
                dimension_value=row.dimension_value or "",
                contract_count=row.contract_count,
                total_annual_value=_safe_float(row.total_annual_value),
                avg_rent_sqft=avg_rent_sqft,
                pct_of_total=round(
                    (_safe_float(row.total_annual_value) / total_value) * 100, 1
                )
                if total_value > 0
                else None,
            )
        )

    return breakdowns
