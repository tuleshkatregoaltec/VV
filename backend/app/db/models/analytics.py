"""Pre-computed analytics models for fast filtered queries.

Analytics are pre-computed for fixed timeframes (7d, 30d, 90d, 180d, 365d)
and dimension combinations for instant dashboard queries.
"""

from typing import Optional, LiteralString
from decimal import Decimal
from datetime import datetime, timezone, date
from sqlmodel import SQLModel, Field, Index
from sqlalchemy import Column, DateTime, text


# Bucket definitions for daily aggregates
# Format: (min_value, max_value, label)

SALES_PRICE_BUCKETS = [
    (0, 500000, '<500K'),
    (500000, 1000000, '500K-1M'),
    (1000000, 2000000, '1M-2M'),
    (2000000, 5000000, '2M-5M'),
    (5000000, 10000000, '5M-10M'),
    (10000000, 25000000, '10M-25M'),
    (25000000, float('inf'), '>25M')
]

RENTAL_PRICE_BUCKETS = [
    (0, 50000, '<50K'),
    (50000, 100000, '50K-100K'),
    (100000, 200000, '100K-200K'),
    (200000, 500000, '200K-500K'),
    (500000, 1000000, '500K-1M'),
    (1000000, float('inf'), '>1M')
]

AREA_BUCKETS = [
    (0, 500, '<500'),
    (500, 1000, '500-1K'),
    (1000, 2000, '1K-2K'),
    (2000, 3000, '2K-3K'),
    (3000, 5000, '3K-5K'),
    (5000, float('inf'), '>5K')
]

PRICE_SQFT_BUCKETS = [
    (0, 500, '<500'),
    (500, 1000, '500-1K'),
    (1000, 1500, '1K-1.5K'),
    (1500, 2000, '1.5K-2K'),
    (2000, 3000, '2K-3K'),
    (3000, float('inf'), '>3K')
]

RENT_SQFT_BUCKETS = [
    (0, 50, '<50'),
    (50, 100, '50-100'),
    (100, 150, '100-150'),
    (150, 200, '150-200'),
    (200, 300, '200-300'),
    (300, float('inf'), '>300')
]


class AnalyticsTrend(SQLModel, table=True):
    """Daily trend data for charts. Computed for each property_usage."""

    __tablename__: LiteralString = "analytics_trends"

    __table_args__ = (
        Index("idx_trends_lookup", "property_usage", "trend_type", "trend_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    trend_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    property_usage: str = Field(max_length=50)
    trend_type: str = Field(max_length=10)  # 'sales' or 'rentals'

    # Metrics
    count: int = Field(default=0)
    total_value: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    avg_value: Decimal = Field(default=0, max_digits=15, decimal_places=2)
    avg_sqft: Decimal = Field(default=0, max_digits=12, decimal_places=2)

    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AnalyticsDailySalesAgg(SQLModel, table=True):
    """Daily aggregated sales data with all dimensions and buckets.

    Enables flexible query-time filtering and re-aggregation across custom date ranges.
    All dimensions are denormalized for fast filtering without joins.
    """

    __tablename__: LiteralString = "analytics_daily_sales_agg"

    __table_args__ = (
        Index(
            "idx_daily_sales_agg_date_usage",
            "agg_date",
            "property_usage",
            postgresql_ops={'agg_date': 'DESC'}
        ),
        Index(
            "idx_daily_sales_agg_master_project",
            "master_project",
            "agg_date",
            postgresql_where=text("master_project IS NOT NULL"),
            postgresql_ops={'agg_date': 'DESC'}
        ),
        Index(
            "idx_daily_sales_agg_property_type",
            "property_type",
            "property_usage",
            "agg_date",
            postgresql_where=text("property_type IS NOT NULL"),
            postgresql_ops={'agg_date': 'DESC'}
        ),
        Index(
            "idx_daily_sales_agg_rooms",
            "rooms",
            "property_usage",
            "agg_date",
            postgresql_where=text("rooms IS NOT NULL"),
            postgresql_ops={'agg_date': 'DESC'}
        ),
        Index(
            "idx_daily_sales_agg_price_bucket",
            "price_bucket",
            "property_usage",
            "agg_date",
            postgresql_where=text("price_bucket IS NOT NULL"),
            postgresql_ops={'agg_date': 'DESC'}
        ),
        Index(
            "idx_daily_sales_agg_area_bucket",
            "area_bucket",
            "property_usage",
            "agg_date",
            postgresql_where=text("area_bucket IS NOT NULL"),
            postgresql_ops={'agg_date': 'DESC'}
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Date dimension (the aggregation key)
    agg_date: date = Field(index=True)

    # Core dimensions (denormalized for fast filtering)
    property_usage: str = Field(max_length=50)
    property_type: Optional[str] = Field(default=None, max_length=255)
    rooms: Optional[str] = Field(default=None, max_length=100)
    reg_type: Optional[str] = Field(default=None, max_length=255)
    master_project: Optional[str] = Field(default=None, max_length=255)
    area_name: Optional[str] = Field(default=None, max_length=255)

    # Bucketed continuous variables
    price_bucket: Optional[str] = Field(default=None, max_length=50)
    area_bucket: Optional[str] = Field(default=None, max_length=50)
    price_sqft_bucket: Optional[str] = Field(default=None, max_length=50)

    # Aggregated metrics
    transaction_count: int = Field(default=0)
    total_volume: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    total_area: Decimal = Field(default=0, max_digits=20, decimal_places=2)

    # For weighted average calculations at query time
    sum_price: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    sum_area: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    sum_price_x_area: Decimal = Field(default=0, max_digits=25, decimal_places=2)

    # Min/Max tracking
    min_price: Optional[Decimal] = Field(default=None, max_digits=15, decimal_places=2)
    max_price: Optional[Decimal] = Field(default=None, max_digits=15, decimal_places=2)
    min_area: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    max_area: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)

    # Metadata
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AnalyticsDailyRentalsAgg(SQLModel, table=True):
    """Daily aggregated rental data with all dimensions and buckets.

    Enables flexible query-time filtering and re-aggregation across custom date ranges.
    All dimensions are denormalized for fast filtering without joins.
    """

    __tablename__: LiteralString = "analytics_daily_rentals_agg"

    __table_args__ = (
        Index(
            "idx_daily_rentals_agg_date_usage",
            "agg_date",
            "property_usage",
            postgresql_ops={'agg_date': 'DESC'}
        ),
        Index(
            "idx_daily_rentals_agg_master_project",
            "master_project",
            "agg_date",
            postgresql_where=text("master_project IS NOT NULL"),
            postgresql_ops={'agg_date': 'DESC'}
        ),
        Index(
            "idx_daily_rentals_agg_property_type",
            "property_type",
            "property_usage",
            "agg_date",
            postgresql_where=text("property_type IS NOT NULL"),
            postgresql_ops={'agg_date': 'DESC'}
        ),
        Index(
            "idx_daily_rentals_agg_rent_bucket",
            "rent_bucket",
            "property_usage",
            "agg_date",
            postgresql_where=text("rent_bucket IS NOT NULL"),
            postgresql_ops={'agg_date': 'DESC'}
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Date dimension
    agg_date: date = Field(index=True)

    # Core dimensions
    property_usage: str = Field(max_length=50)
    property_type: Optional[str] = Field(default=None, max_length=100)
    master_project: Optional[str] = Field(default=None, max_length=255)
    area_name: Optional[str] = Field(default=None, max_length=255)
    contract_reg_type: Optional[str] = Field(default=None, max_length=100)
    tenant_type: Optional[str] = Field(default=None, max_length=100)

    # Bucketed dimensions
    rent_bucket: Optional[str] = Field(default=None, max_length=50)
    area_bucket: Optional[str] = Field(default=None, max_length=50)
    rent_sqft_bucket: Optional[str] = Field(default=None, max_length=50)

    # Metrics
    contract_count: int = Field(default=0)
    total_annual_value: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    total_area: Decimal = Field(default=0, max_digits=20, decimal_places=2)

    # For weighted averages
    sum_rent: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    sum_area: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    sum_rent_x_area: Decimal = Field(default=0, max_digits=25, decimal_places=2)

    # Min/Max
    min_annual_rent: Optional[Decimal] = Field(default=None, max_digits=15, decimal_places=2)
    max_annual_rent: Optional[Decimal] = Field(default=None, max_digits=15, decimal_places=2)
    min_area: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    max_area: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)

    # Metadata
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


