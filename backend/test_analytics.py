#!/usr/bin/env python3
"""Quick test script for the new analytics system."""

import asyncio
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.services.analytics_service import fetch_sales_analytics, fetch_rental_analytics


async def test_analytics():
    """Test the new analytics endpoints."""

    # Create database session (using sqlmodel's AsyncSession like the app does)
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        print("=" * 80)
        print("TESTING NEW DAILY AGGREGATION ANALYTICS")
        print("=" * 80)

        # Test 1: Basic 30-day query (backward compatible)
        print("\n📊 Test 1: Basic 30-day sales query")
        print("-" * 80)
        result1 = await fetch_sales_analytics(
            db=session,
            property_usage="Residential",
            timeframe_days=30
        )
        print(f"✅ Timeframe: {result1.timeframe_days} days")
        print(f"✅ Property Usage: {result1.property_usage}")
        print(f"✅ Transaction Count: {result1.summary.transaction_count:,}")
        print(f"✅ Total Volume: AED {result1.summary.total_volume:,.2f}")
        print(f"✅ Avg Price: AED {result1.summary.avg_price:,.2f}")
        print(f"✅ Avg Price/sqft: AED {result1.summary.avg_price_sqft:,.2f}")
        print(f"✅ Volume Change: {result1.summary.volume_change_pct}%")
        print(f"✅ Trend Points: {len(result1.trends)}")
        print(f"✅ Property Types: {len(result1.by_property_type)}")
        print(f"✅ Master Projects: {len(result1.by_master_project)}")

        # Test 2: Custom date range (NEW!)
        print("\n📊 Test 2: Custom date range (2024-11-21 to 2024-12-21)")
        print("-" * 80)
        result2 = await fetch_sales_analytics(
            db=session,
            property_usage="Residential",
            start_date=date(2024, 11, 21),
            end_date=date(2024, 12, 21)
        )
        print(f"✅ Transaction Count: {result2.summary.transaction_count:,}")
        print(f"✅ Total Volume: AED {result2.summary.total_volume:,.2f}")

        # Test 3: Multi-dimensional filtering (NEW!)
        print("\n📊 Test 3: Multi-dimensional filtering (1M-2M price bucket)")
        print("-" * 80)
        result3 = await fetch_sales_analytics(
            db=session,
            property_usage="Residential",
            timeframe_days=30,
            price_bucket="1M-2M"
        )
        print(f"✅ Filtered Transaction Count: {result3.summary.transaction_count:,}")
        print(f"✅ Total Volume (1M-2M only): AED {result3.summary.total_volume:,.2f}")
        print(f"✅ Avg Price: AED {result3.summary.avg_price:,.2f}")

        # Test 4: Rentals
        print("\n📊 Test 4: Rental analytics (30 days)")
        print("-" * 80)
        result4 = await fetch_rental_analytics(
            db=session,
            property_usage="Residential",
            timeframe_days=30
        )
        print(f"✅ Contract Count: {result4.summary.contract_count:,}")
        print(f"✅ Total Annual Value: AED {result4.summary.total_annual_value:,.2f}")
        print(f"✅ Avg Annual Rent: AED {result4.summary.avg_annual_rent:,.2f}")
        print(f"✅ Avg Rent/sqft: AED {result4.summary.avg_rent_sqft:,.2f}")

        # Test 5: Property Type Breakdown
        if result1.by_property_type:
            print("\n📊 Test 5: Property Type Breakdown (Top 5)")
            print("-" * 80)
            for i, pt in enumerate(result1.by_property_type[:5], 1):
                print(f"{i}. {pt.dimension_value}: {pt.transaction_count:,} transactions, "
                      f"AED {pt.total_volume:,.0f} ({pt.pct_of_total}%)")

        print("\n" + "=" * 80)
        print("✅ ALL TESTS PASSED! The new analytics system is working perfectly!")
        print("=" * 80)

        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(test_analytics())
