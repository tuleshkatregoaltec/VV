#!/usr/bin/env python3
"""
Analytics Computation Script

Computes pre-aggregated analytics from raw transaction and rental data.
Run this after your daily ETL to populate the analytics tables.

Usage:
    # Compute all analytics (default - runs full refresh)
    python -m backend.scripts.compute_analytics

    # Compute only sales
    python -m backend.scripts.compute_analytics --sales-only

    # Compute only rentals
    python -m backend.scripts.compute_analytics --rentals-only
"""

import argparse
import asyncio
from datetime import datetime, timezone

from sqlalchemy import text, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.app.config import settings
from backend.app.db.models.analytics import (
    AnalyticsSalesSummary,
    AnalyticsRentalsSummary,
    AnalyticsTrend,
    ANALYTICS_TIMEFRAMES,
)


async def get_session() -> AsyncSession:
    """Create an async database session"""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return async_session()


# =============================================================================
# SALES ANALYTICS
# =============================================================================


async def compute_sales_summary(session: AsyncSession) -> int:
    """Compute sales summary for all timeframes and dimensions."""
    print("Computing sales summary analytics...")

    # Clear existing data
    await session.execute(delete(AnalyticsSalesSummary))

    rows_inserted = 0

    for timeframe in ANALYTICS_TIMEFRAMES:
        print(f"  Timeframe: {timeframe} days...")

        # Use make_interval to avoid type ambiguity with parameter binding
        # Base aggregation (no dimension breakdown)
        base_query = text(f"""
            INSERT INTO analytics_sales_summary (
                timeframe_days, property_usage, dimension, dimension_value,
                transaction_count, total_volume, total_area, avg_price, avg_price_sqft,
                min_price, max_price, prev_transaction_count, prev_total_volume, computed_at
            )
            SELECT
                {timeframe} as timeframe_days,
                property_usage,
                NULL as dimension,
                NULL as dimension_value,
                COUNT(*) as transaction_count,
                COALESCE(SUM(actual_worth), 0) as total_volume,
                COALESCE(SUM(procedure_area), 0) as total_area,
                COALESCE(AVG(actual_worth), 0) as avg_price,
                CASE WHEN SUM(procedure_area) > 0
                     THEN SUM(actual_worth) / SUM(procedure_area)
                     ELSE 0 END as avg_price_sqft,
                COALESCE(MIN(actual_worth), 0) as min_price,
                COALESCE(MAX(actual_worth), 0) as max_price,
                0 as prev_transaction_count,
                0 as prev_total_volume,
                NOW() as computed_at
            FROM transactions
            WHERE instance_date >= CURRENT_DATE - INTERVAL '{timeframe} days'
              AND instance_date < CURRENT_DATE
              AND property_usage IS NOT NULL
              AND trans_group = 'Sales'
            GROUP BY property_usage
        """)
        result = await session.execute(base_query)
        rows_inserted += result.rowcount

        # Update with previous period data
        prev_update = text(f"""
            UPDATE analytics_sales_summary s
            SET
                prev_transaction_count = sub.cnt,
                prev_total_volume = sub.vol
            FROM (
                SELECT
                    property_usage,
                    COUNT(*) as cnt,
                    COALESCE(SUM(actual_worth), 0) as vol
                FROM transactions
                WHERE instance_date >= CURRENT_DATE - INTERVAL '{timeframe * 2} days'
                  AND instance_date < CURRENT_DATE - INTERVAL '{timeframe} days'
                  AND property_usage IS NOT NULL
                  AND trans_group = 'Sales'
                GROUP BY property_usage
            ) sub
            WHERE s.timeframe_days = {timeframe}
              AND s.dimension IS NULL
              AND s.property_usage = sub.property_usage
        """)
        await session.execute(prev_update)

        # Dimension breakdowns
        dimensions = [
            ("property_type", "property_type"),
            ("rooms", "rooms_description"),
            ("reg_type", "reg_type"),
            ("master_project", "master_project"),
        ]

        for dim_name, dim_column in dimensions:
            dim_query = text(f"""
                INSERT INTO analytics_sales_summary (
                    timeframe_days, property_usage, dimension, dimension_value,
                    transaction_count, total_volume, total_area, avg_price, avg_price_sqft,
                    min_price, max_price, prev_transaction_count, prev_total_volume, computed_at
                )
                SELECT
                    {timeframe} as timeframe_days,
                    property_usage,
                    '{dim_name}' as dimension,
                    {dim_column} as dimension_value,
                    COUNT(*) as transaction_count,
                    COALESCE(SUM(actual_worth), 0) as total_volume,
                    COALESCE(SUM(procedure_area), 0) as total_area,
                    COALESCE(AVG(actual_worth), 0) as avg_price,
                    CASE WHEN SUM(procedure_area) > 0
                         THEN SUM(actual_worth) / SUM(procedure_area)
                         ELSE 0 END as avg_price_sqft,
                    COALESCE(MIN(actual_worth), 0) as min_price,
                    COALESCE(MAX(actual_worth), 0) as max_price,
                    0 as prev_transaction_count,
                    0 as prev_total_volume,
                    NOW() as computed_at
                FROM transactions
                WHERE instance_date >= CURRENT_DATE - INTERVAL '{timeframe} days'
                  AND instance_date < CURRENT_DATE
                  AND property_usage IS NOT NULL
                  AND {dim_column} IS NOT NULL
                  AND {dim_column} != ''
                  AND trans_group = 'Sales'
                GROUP BY property_usage, {dim_column}
            """)
            result = await session.execute(dim_query)
            rows_inserted += result.rowcount

    await session.commit()
    print(f"  Inserted {rows_inserted} sales summary rows")
    return rows_inserted


async def compute_sales_trends(session: AsyncSession) -> int:
    """Compute daily trend data for sales."""
    print("Computing sales trend analytics...")

    # Clear existing sales trends
    await session.execute(
        delete(AnalyticsTrend).where(AnalyticsTrend.trend_type == "sales")
    )

    # Compute trends for last 365 days
    trend_query = text("""
        INSERT INTO analytics_trends (
            trend_date, property_usage, trend_type,
            count, total_value, avg_value, avg_sqft, computed_at
        )
        SELECT
            instance_date as trend_date,
            property_usage,
            'sales' as trend_type,
            COUNT(*) as count,
            COALESCE(SUM(actual_worth), 0) as total_value,
            COALESCE(AVG(actual_worth), 0) as avg_value,
            CASE WHEN SUM(procedure_area) > 0
                 THEN SUM(actual_worth) / SUM(procedure_area)
                 ELSE 0 END as avg_sqft,
            NOW() as computed_at
        FROM transactions
        WHERE instance_date >= CURRENT_DATE - INTERVAL '365 days'
          AND instance_date < CURRENT_DATE
          AND property_usage IS NOT NULL
          AND trans_group = 'Sales'
        GROUP BY instance_date, property_usage
        ORDER BY instance_date
    """)

    result = await session.execute(trend_query)
    await session.commit()
    print(f"  Inserted {result.rowcount} sales trend rows")
    return result.rowcount


# =============================================================================
# RENTAL ANALYTICS
# =============================================================================


async def compute_rentals_summary(session: AsyncSession) -> int:
    """Compute rental summary for all timeframes and dimensions."""
    print("Computing rental summary analytics...")

    # Clear existing data
    await session.execute(delete(AnalyticsRentalsSummary))

    rows_inserted = 0

    for timeframe in ANALYTICS_TIMEFRAMES:
        print(f"  Timeframe: {timeframe} days...")

        # Base aggregation
        base_query = text(f"""
            INSERT INTO analytics_rentals_summary (
                timeframe_days, property_usage, dimension, dimension_value,
                contract_count, total_annual_value, total_area, avg_annual_rent, avg_rent_sqft,
                min_annual_rent, max_annual_rent, prev_contract_count, prev_total_annual_value, computed_at
            )
            SELECT
                {timeframe} as timeframe_days,
                property_usage,
                NULL as dimension,
                NULL as dimension_value,
                COUNT(*) as contract_count,
                COALESCE(SUM(annual_amount), 0) as total_annual_value,
                COALESCE(SUM(actual_area), 0) as total_area,
                COALESCE(AVG(annual_amount), 0) as avg_annual_rent,
                CASE WHEN SUM(actual_area) > 0
                     THEN SUM(annual_amount) / SUM(actual_area)
                     ELSE 0 END as avg_rent_sqft,
                COALESCE(MIN(annual_amount), 0) as min_annual_rent,
                COALESCE(MAX(annual_amount), 0) as max_annual_rent,
                0 as prev_contract_count,
                0 as prev_total_annual_value,
                NOW() as computed_at
            FROM rent_contracts
            WHERE contract_start_date >= CURRENT_DATE - INTERVAL '{timeframe} days'
              AND contract_start_date < CURRENT_DATE
              AND property_usage IS NOT NULL
            GROUP BY property_usage
        """)
        result = await session.execute(base_query)
        rows_inserted += result.rowcount

        # Update with previous period data
        prev_update = text(f"""
            UPDATE analytics_rentals_summary s
            SET
                prev_contract_count = sub.cnt,
                prev_total_annual_value = sub.vol
            FROM (
                SELECT
                    property_usage,
                    COUNT(*) as cnt,
                    COALESCE(SUM(annual_amount), 0) as vol
                FROM rent_contracts
                WHERE contract_start_date >= CURRENT_DATE - INTERVAL '{timeframe * 2} days'
                  AND contract_start_date < CURRENT_DATE - INTERVAL '{timeframe} days'
                  AND property_usage IS NOT NULL
                GROUP BY property_usage
            ) sub
            WHERE s.timeframe_days = {timeframe}
              AND s.dimension IS NULL
              AND s.property_usage = sub.property_usage
        """)
        await session.execute(prev_update)

        # Dimension breakdowns
        dimensions = [
            ("property_type", "ejari_property_type"),
            ("master_project", "master_project"),
        ]

        for dim_name, dim_column in dimensions:
            dim_query = text(f"""
                INSERT INTO analytics_rentals_summary (
                    timeframe_days, property_usage, dimension, dimension_value,
                    contract_count, total_annual_value, total_area, avg_annual_rent, avg_rent_sqft,
                    min_annual_rent, max_annual_rent, prev_contract_count, prev_total_annual_value, computed_at
                )
                SELECT
                    {timeframe} as timeframe_days,
                    property_usage,
                    '{dim_name}' as dimension,
                    {dim_column} as dimension_value,
                    COUNT(*) as contract_count,
                    COALESCE(SUM(annual_amount), 0) as total_annual_value,
                    COALESCE(SUM(actual_area), 0) as total_area,
                    COALESCE(AVG(annual_amount), 0) as avg_annual_rent,
                    CASE WHEN SUM(actual_area) > 0
                         THEN SUM(annual_amount) / SUM(actual_area)
                         ELSE 0 END as avg_rent_sqft,
                    COALESCE(MIN(annual_amount), 0) as min_annual_rent,
                    COALESCE(MAX(annual_amount), 0) as max_annual_rent,
                    0 as prev_contract_count,
                    0 as prev_total_annual_value,
                    NOW() as computed_at
                FROM rent_contracts
                WHERE contract_start_date >= CURRENT_DATE - INTERVAL '{timeframe} days'
                  AND contract_start_date < CURRENT_DATE
                  AND property_usage IS NOT NULL
                  AND {dim_column} IS NOT NULL
                  AND {dim_column} != ''
                GROUP BY property_usage, {dim_column}
            """)
            result = await session.execute(dim_query)
            rows_inserted += result.rowcount

    await session.commit()
    print(f"  Inserted {rows_inserted} rental summary rows")
    return rows_inserted


async def compute_rentals_trends(session: AsyncSession) -> int:
    """Compute daily trend data for rentals."""
    print("Computing rental trend analytics...")

    # Clear existing rental trends
    await session.execute(
        delete(AnalyticsTrend).where(AnalyticsTrend.trend_type == "rentals")
    )

    # Compute trends for last 365 days
    trend_query = text("""
        INSERT INTO analytics_trends (
            trend_date, property_usage, trend_type,
            count, total_value, avg_value, avg_sqft, computed_at
        )
        SELECT
            contract_start_date as trend_date,
            property_usage,
            'rentals' as trend_type,
            COUNT(*) as count,
            COALESCE(SUM(annual_amount), 0) as total_value,
            COALESCE(AVG(annual_amount), 0) as avg_value,
            CASE WHEN SUM(actual_area) > 0
                 THEN SUM(annual_amount) / SUM(actual_area)
                 ELSE 0 END as avg_sqft,
            NOW() as computed_at
        FROM rent_contracts
        WHERE contract_start_date >= CURRENT_DATE - INTERVAL '365 days'
          AND contract_start_date < CURRENT_DATE
          AND property_usage IS NOT NULL
        GROUP BY contract_start_date, property_usage
        ORDER BY contract_start_date
    """)

    result = await session.execute(trend_query)
    await session.commit()
    print(f"  Inserted {result.rowcount} rental trend rows")
    return result.rowcount


# =============================================================================
# MAIN
# =============================================================================


async def compute_all(session: AsyncSession) -> None:
    """Compute all analytics."""
    start = datetime.now(timezone.utc)

    await compute_sales_summary(session)
    await compute_sales_trends(session)
    await compute_rentals_summary(session)
    await compute_rentals_trends(session)

    elapsed = datetime.now(timezone.utc) - start
    print(f"\nCompleted in {elapsed.total_seconds():.1f}s")


async def main():
    parser = argparse.ArgumentParser(description="Compute pre-aggregated analytics")
    parser.add_argument(
        "--sales-only", action="store_true", help="Only compute sales analytics"
    )
    parser.add_argument(
        "--rentals-only", action="store_true", help="Only compute rental analytics"
    )

    args = parser.parse_args()

    session = await get_session()

    try:
        if args.sales_only:
            await compute_sales_summary(session)
            await compute_sales_trends(session)
        elif args.rentals_only:
            await compute_rentals_summary(session)
            await compute_rentals_trends(session)
        else:
            await compute_all(session)
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
