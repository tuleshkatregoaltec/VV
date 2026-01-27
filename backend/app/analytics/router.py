"""Analytics API endpoints with flexible filtering from daily aggregates."""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query

from app.core.dependencies import require_active_subscription, AuthContext
from app.analytics.models import (
    AnalyticsResponse,
    RentalAnalyticsResponse,
    AnalyticsSummary,
    RentalSummary,
)
from app.clickhouse.client import query
from app.clickhouse.queries import sales_summary, rentals_summary
from app.clickhouse.types import (
    SalesSummary as CHSalesSummary,
    RentalSummary as CHRentalSummary,
)

router = APIRouter(
    prefix="/api/v1/analytics",
    tags=["analytics"],
)


@router.get("/sales", response_model=AnalyticsResponse)
async def get_sales_analytics(
    context: AuthContext = Depends(require_active_subscription),
    property_usage: str = Query(
        default="Residential", description="Residential or Commercial"
    ),
    timeframe_days: Optional[int] = Query(
        default=None,
        description="Number of days to look back (overrides start_date if provided)",
    ),
    start_date: Optional[date] = Query(
        default=None, description="Explicit start date (YYYY-MM-DD)"
    ),
    end_date: Optional[date] = Query(
        default=None, description="Explicit end date (YYYY-MM-DD), defaults to today"
    ),
    master_project: Optional[str] = Query(
        default=None, description="Filter by master project name"
    ),
    property_type: Optional[str] = Query(
        default=None, description="Filter by property type"
    ),
    rooms: Optional[str] = Query(default=None, description="Filter by room count"),
    reg_type: Optional[str] = Query(
        default=None, description="Filter by registration type"
    ),
    price_bucket: Optional[str] = Query(
        default=None, description="Filter by price bucket (e.g., '1M-2M')"
    ),
    area_bucket: Optional[str] = Query(
        default=None, description="Filter by area bucket (e.g., '1K-2K')"
    ),
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
    # Calculate date range
    if timeframe_days:
        from datetime import timedelta

        end_date = date.today()
        start_date = end_date - timedelta(days=timeframe_days)
    else:
        if not start_date:
            from datetime import timedelta

            start_date = date.today() - timedelta(days=30)  # Default 30 days
        if not end_date:
            end_date = date.today()

    # Execute ClickHouse query
    try:
        sql = sales_summary(
            property_usage=property_usage,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            master_project=master_project,
            property_type=property_type,
            rooms=rooms,
            reg_type=reg_type,
            price_bucket=price_bucket,
            area_bucket=area_bucket,
        )

        parameters = {
            "property_usage": property_usage,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }

        # Add optional parameters
        if master_project:
            parameters["master_project"] = master_project
        if property_type:
            parameters["property_type"] = property_type
        if rooms:
            parameters["rooms"] = rooms
        if reg_type:
            parameters["reg_type"] = reg_type
        if price_bucket:
            parameters["price_bucket"] = price_bucket
        if area_bucket:
            parameters["area_bucket"] = area_bucket

        result = await query(sql, parameters)

    except Exception as e:
        # Log error and return empty response instead of crashing
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Error executing sales analytics query: {str(e)}")
        result = []

    if not result:
        # Return empty analytics response
        summary = AnalyticsSummary(
            transaction_count=0,
            total_volume=0.0,
            avg_price=0.0,
            avg_price_sqft=0.0,
            min_price=0.0,
            max_price=0.0,
        )
        return AnalyticsResponse(
            timeframe_days=timeframe_days or (end_date - start_date).days,
            property_usage=property_usage,
            summary=summary,
            trends=[],
            by_property_type=[],
            by_rooms=[],
            by_reg_type=[],
            by_master_project=[],
        )

    # Convert result to summary
    row = result[0]
    summary = AnalyticsSummary(
        transaction_count=row["transaction_count"],
        total_volume=float(row["total_volume"]),
        avg_price=float(row["avg_price"]),
        avg_price_sqft=float(row.get("median_price_per_sqm", 0)),  # Use available field
        min_price=float(row.get("median_price", 0)),  # Use median as approximation
        max_price=float(row.get("avg_price", 0)),  # Use avg as approximation
    )

    # For now, return basic response with just summary
    # TODO: Add trends and breakdowns queries
    return AnalyticsResponse(
        timeframe_days=timeframe_days or (end_date - start_date).days,
        property_usage=property_usage,
        summary=summary,
        trends=[],  # TODO: Implement trends query
        by_property_type=[],  # TODO: Implement breakdowns
        by_rooms=[],
        by_reg_type=[],
        by_master_project=[],
    )


@router.get("/rentals", response_model=RentalAnalyticsResponse)
async def get_rental_analytics(
    context: AuthContext = Depends(require_active_subscription),
    property_usage: str = Query(
        default="Residential", description="Residential or Commercial"
    ),
    timeframe_days: Optional[int] = Query(
        default=None,
        description="Number of days to look back (overrides start_date if provided)",
    ),
    start_date: Optional[date] = Query(
        default=None, description="Explicit start date (YYYY-MM-DD)"
    ),
    end_date: Optional[date] = Query(
        default=None, description="Explicit end date (YYYY-MM-DD), defaults to today"
    ),
    master_project: Optional[str] = Query(
        default=None, description="Filter by master project name"
    ),
    property_type: Optional[str] = Query(
        default=None, description="Filter by property type"
    ),
    rent_bucket: Optional[str] = Query(
        default=None, description="Filter by rent bucket (e.g., '100K-200K')"
    ),
    area_bucket: Optional[str] = Query(
        default=None, description="Filter by area bucket (e.g., '1K-2K')"
    ),
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
    # Calculate date range
    if timeframe_days:
        from datetime import timedelta

        end_date = date.today()
        start_date = end_date - timedelta(days=timeframe_days)
    else:
        if not start_date:
            from datetime import timedelta

            start_date = date.today() - timedelta(
                days=90
            )  # Default 90 days for rentals
        if not end_date:
            end_date = date.today()

    # Execute ClickHouse query
    sql = rentals_summary(
        property_usage=property_usage,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        master_project=master_project,
        property_type=property_type,
    )

    parameters = {
        "property_usage": property_usage,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }

    # Add optional parameters
    if master_project:
        parameters["master_project"] = master_project
    if property_type:
        parameters["property_type"] = property_type

    result = await query(sql, parameters)

    if not result:
        # Return empty rental analytics response
        summary = RentalSummary(
            contract_count=0,
            total_annual_value=0.0,
            avg_annual_rent=0.0,
            avg_rent_sqft=0.0,
            min_annual_rent=0.0,
            max_annual_rent=0.0,
        )
        return RentalAnalyticsResponse(
            timeframe_days=timeframe_days or (end_date - start_date).days,
            property_usage=property_usage,
            summary=summary,
            trends=[],
            by_property_type=[],
            by_master_project=[],
        )

    # Convert result to summary
    row = result[0]
    summary = RentalSummary(
        contract_count=row["contract_count"],
        total_annual_value=float(row["total_annual_value"]),
        avg_annual_rent=float(row["avg_rent"]),
        avg_rent_sqft=float(row.get("median_rent_per_sqm", 0)),
        min_annual_rent=float(row.get("median_rent", 0)),  # Use median as approximation
        max_annual_rent=float(row.get("avg_rent", 0)),  # Use avg as approximation
    )

    # For now, return basic response with just summary
    # TODO: Add trends and breakdowns queries
    return RentalAnalyticsResponse(
        timeframe_days=timeframe_days or (end_date - start_date).days,
        property_usage=property_usage,
        summary=summary,
        trends=[],  # TODO: Implement trends query
        by_property_type=[],  # TODO: Implement breakdowns
        by_master_project=[],
    )
