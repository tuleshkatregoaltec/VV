#!/usr/bin/env python3
"""
Daily Analytics Aggregation Script

Incrementally updates daily aggregates from raw transaction data.
Run this after your daily ETL to update only the affected days.

Usage:
    # Update last 7 days (catches late-arriving data)
    python -m backend.scripts.compute_daily_analytics

    # Full historical rebuild
    python -m backend.scripts.compute_daily_analytics --full-rebuild

    # Update specific date range
    python -m backend.scripts.compute_daily_analytics --start-date 2024-01-01 --end-date 2024-01-31

    # Sales or rentals only
    python -m backend.scripts.compute_daily_analytics --sales-only
    python -m backend.scripts.compute_daily_analytics --rentals-only
"""

import argparse
import asyncio
from datetime import datetime, date, timedelta, timezone
from typing import Tuple

from sqlalchemy import text, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models.analytics import (
    AnalyticsDailySalesAgg,
    AnalyticsDailyRentalsAgg,
    SALES_PRICE_BUCKETS,
    RENTAL_PRICE_BUCKETS,
    AREA_BUCKETS,
    PRICE_SQFT_BUCKETS,
    RENT_SQFT_BUCKETS,
)


def _build_bucket_case(column: str, buckets: list) -> str:
    """Build a SQL CASE statement for bucketing.

    Args:
        column: Column name or expression to bucket
        buckets: List of (min_val, max_val, label) tuples

    Returns:
        SQL CASE statement string
    """
    cases = []
    for min_val, max_val, label in buckets[:-1]:  # All except last
        if max_val == float("inf"):
            # Last bucket
            cases.append(f"WHEN {column} >= {min_val} THEN '{label}'")
        else:
            cases.append(
                f"WHEN {column} >= {min_val} AND {column} < {max_val} THEN '{label}'"
            )

    # Last bucket (should handle infinity)
    last_min, _, last_label = buckets[-1]
    cases.append(f"WHEN {column} >= {last_min} THEN '{last_label}'")

    return f"CASE {' '.join(cases)} ELSE NULL END"


async def compute_daily_sales_aggregates(
    session: AsyncSession, start_date: date, end_date: date
) -> int:
    """Compute daily sales aggregates for a date range.

    Args:
        session: Database session
        start_date: Start date (inclusive)
        end_date: End date (inclusive)

    Returns:
        Number of rows inserted
    """
    print(f"Computing daily sales aggregates from {start_date} to {end_date}...")

    # Delete existing aggregates for this date range to allow recomputation
    await session.execute(
        delete(AnalyticsDailySalesAgg).where(
            AnalyticsDailySalesAgg.agg_date >= start_date,
            AnalyticsDailySalesAgg.agg_date <= end_date,
        )
    )
    await session.commit()

    # Build bucket CASE statements
    price_bucket_case = _build_bucket_case("actual_worth", SALES_PRICE_BUCKETS)
    area_bucket_case = _build_bucket_case("procedure_area", AREA_BUCKETS)
    price_sqft_bucket_case = _build_bucket_case("meter_sale_price", PRICE_SQFT_BUCKETS)

    # Aggregate query with all dimensions
    agg_query = text(f"""
        INSERT INTO analytics_daily_sales_agg (
            agg_date, property_usage, property_type, rooms, reg_type,
            master_project, area_name, price_bucket, area_bucket, price_sqft_bucket,
            transaction_count, total_volume, total_area,
            sum_price, sum_area, sum_price_x_area,
            min_price, max_price, min_area, max_area,
            computed_at
        )
        SELECT
            instance_date as agg_date,
            property_usage_en as property_usage,
            property_type_en as property_type,
            rooms_en as rooms,
            reg_type_en as reg_type,
            master_project_en as master_project,
            area_name_en as area_name,
            {price_bucket_case} as price_bucket,
            {area_bucket_case} as area_bucket,
            {price_sqft_bucket_case} as price_sqft_bucket,
            COUNT(*) as transaction_count,
            COALESCE(SUM(actual_worth), 0) as total_volume,
            COALESCE(SUM(procedure_area), 0) as total_area,
            COALESCE(SUM(actual_worth), 0) as sum_price,
            COALESCE(SUM(procedure_area * 10.764), 0) as sum_area,
            COALESCE(SUM(actual_worth), 0) as sum_price_x_area,
            MIN(actual_worth) as min_price,
            MAX(actual_worth) as max_price,
            MIN(procedure_area) as min_area,
            MAX(procedure_area) as max_area,
            NOW() as computed_at
        FROM transactions
        WHERE instance_date >= :start_date
          AND instance_date <= :end_date
          AND trans_group_en = 'Sales'
          AND property_usage_en IS NOT NULL
        GROUP BY
            instance_date,
            property_usage_en,
            property_type_en,
            rooms_en,
            reg_type_en,
            master_project_en,
            area_name_en,
            price_bucket,
            area_bucket,
            price_sqft_bucket
    """)

    result = await session.execute(
        agg_query, {"start_date": start_date, "end_date": end_date}
    )
    await session.commit()

    rows_inserted = result.rowcount
    print(f"  Inserted {rows_inserted} daily sales aggregate rows")
    return rows_inserted


async def compute_daily_rentals_aggregates(
    session: AsyncSession, start_date: date, end_date: date
) -> int:
    """Compute daily rentals aggregates for a date range.

    Args:
        session: Database session
        start_date: Start date (inclusive)
        end_date: End date (inclusive)

    Returns:
        Number of rows inserted
    """
    print(f"Computing daily rental aggregates from {start_date} to {end_date}...")

    # Delete existing aggregates for this date range
    await session.execute(
        delete(AnalyticsDailyRentalsAgg).where(
            AnalyticsDailyRentalsAgg.agg_date >= start_date,
            AnalyticsDailyRentalsAgg.agg_date <= end_date,
        )
    )
    await session.commit()

    # Build bucket cases
    rent_bucket_case = _build_bucket_case("annual_amount", RENTAL_PRICE_BUCKETS)
    area_bucket_case = _build_bucket_case("actual_area", AREA_BUCKETS)
    # For rent per sqft, we need to calculate it first
    rent_sqft_bucket_case = _build_bucket_case(
        "CASE WHEN actual_area > 0 THEN annual_amount / actual_area ELSE NULL END",
        RENT_SQFT_BUCKETS,
    )

    agg_query = text(f"""
        INSERT INTO analytics_daily_rentals_agg (
            agg_date, property_usage, property_type, master_project, area_name,
            contract_reg_type, tenant_type, rent_bucket, area_bucket, rent_sqft_bucket,
            contract_count, total_annual_value, total_area,
            sum_rent, sum_area, sum_rent_x_area,
            min_annual_rent, max_annual_rent, min_area, max_area,
            computed_at
        )
        SELECT
            contract_start_date as agg_date,
            property_usage_en as property_usage,
            ejari_property_type_en as property_type,
            master_project_en as master_project,
            area_name_en as area_name,
            contract_reg_type_en as contract_reg_type,
            tenant_type_en as tenant_type,
            {rent_bucket_case} as rent_bucket,
            {area_bucket_case} as area_bucket,
            {rent_sqft_bucket_case} as rent_sqft_bucket,
            COUNT(*) as contract_count,
            COALESCE(SUM(annual_amount), 0) as total_annual_value,
            COALESCE(SUM(actual_area), 0) as total_area,
            COALESCE(SUM(annual_amount), 0) as sum_rent,
            COALESCE(SUM(actual_area * 10.764), 0) as sum_area,
            COALESCE(SUM(annual_amount), 0) as sum_rent_x_area,
            MIN(annual_amount) as min_annual_rent,
            MAX(annual_amount) as max_annual_rent,
            MIN(actual_area) as min_area,
            MAX(actual_area) as max_area,
            NOW() as computed_at
        FROM rent_contracts
        WHERE contract_start_date >= :start_date
          AND contract_start_date <= :end_date
          AND property_usage_en IS NOT NULL
        GROUP BY
            contract_start_date,
            property_usage_en,
            ejari_property_type_en,
            master_project_en,
            area_name_en,
            contract_reg_type_en,
            tenant_type_en,
            rent_bucket,
            area_bucket,
            rent_sqft_bucket
    """)

    result = await session.execute(
        agg_query, {"start_date": start_date, "end_date": end_date}
    )
    await session.commit()

    rows_inserted = result.rowcount
    print(f"  Inserted {rows_inserted} daily rental aggregate rows")
    return rows_inserted


async def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description="Compute daily analytics aggregates")
    parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Rebuild all historical data (warning: slow)",
    )
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=7,
        help="Number of days to look back for incremental update (default: 7)",
    )
    parser.add_argument(
        "--sales-only", action="store_true", help="Compute only sales aggregates"
    )
    parser.add_argument(
        "--rentals-only", action="store_true", help="Compute only rentals aggregates"
    )

    args = parser.parse_args()

    # Determine date range
    if args.full_rebuild:
        # Rebuild last 5 years (covers vast majority of data as per user feedback)
        start_date = date.today() - timedelta(days=5 * 365)
        end_date = date.today()
        print("Full rebuild mode - computing last 5 years of data")
        print("WARNING: This may take 1-2 hours!")
    elif args.start_date and args.end_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    else:
        # Default: incremental update (last N days to catch late arrivals)
        end_date = date.today()
        start_date = end_date - timedelta(days=args.lookback_days)
        print(f"Incremental update mode: last {args.lookback_days} days")

    print(f"Date range: {start_date} to {end_date}")

    # Create session
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        try:
            start_time = datetime.now(timezone.utc)
            total_rows = 0

            # Compute sales unless rentals-only flag is set
            if not args.rentals_only:
                sales_rows = await compute_daily_sales_aggregates(
                    session, start_date, end_date
                )
                total_rows += sales_rows

            # Compute rentals unless sales-only flag is set
            if not args.sales_only:
                rentals_rows = await compute_daily_rentals_aggregates(
                    session, start_date, end_date
                )
                total_rows += rentals_rows

            elapsed = datetime.now(timezone.utc) - start_time
            print(f"\n✓ Completed in {elapsed.total_seconds():.1f}s")
            print(f"Total rows inserted: {total_rows:,}")

        except Exception as e:
            print(f"\n✗ Error: {e}")
            raise
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
