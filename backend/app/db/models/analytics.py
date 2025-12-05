"""Pre-computed analytics models for fast filtered queries.

Analytics are pre-computed for fixed timeframes (7d, 30d, 90d, 180d, 365d)
and dimension combinations for instant dashboard queries.
"""

from typing import Optional, LiteralString
from decimal import Decimal
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Index
from sqlalchemy import Column, DateTime


# Valid timeframe periods in days
ANALYTICS_TIMEFRAMES = [7, 30, 90, 180, 365]


class AnalyticsSalesSummary(SQLModel, table=True):
    """Pre-computed sales analytics for fixed timeframes.

    Each row represents aggregated metrics for a timeframe + dimension combination.
    Dimension columns store the breakdown type ('property_type', 'rooms', etc.)
    and value ('Villa', '2 B/R', etc.) for grouped analytics.
    """

    __tablename__: LiteralString = "analytics_sales_summary"

    __table_args__ = (
        Index(
            "idx_sales_summary_lookup",
            "property_usage",
            "timeframe_days",
            "dimension",
            "dimension_value",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Time period
    timeframe_days: int  # 7, 30, 90, 180, 365

    # Required filter
    property_usage: str = Field(max_length=50)  # Residential/Commercial

    # Dimension breakdown (NULL = base aggregation, no breakdown)
    dimension: Optional[str] = Field(
        default=None, max_length=50
    )  # 'property_type', 'rooms', 'reg_type', 'master_project'
    dimension_value: Optional[str] = Field(
        default=None, max_length=255
    )  # 'Villa', '2 B/R', 'Off-plan', 'Dubai Marina'

    # Metrics
    transaction_count: int = Field(default=0)
    total_volume: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    total_area: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    avg_price: Decimal = Field(default=0, max_digits=15, decimal_places=2)
    avg_price_sqft: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    min_price: Decimal = Field(default=0, max_digits=15, decimal_places=2)
    max_price: Decimal = Field(default=0, max_digits=15, decimal_places=2)

    # Period comparison
    prev_transaction_count: int = Field(default=0)
    prev_total_volume: Decimal = Field(default=0, max_digits=20, decimal_places=2)

    # Metadata
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AnalyticsRentalsSummary(SQLModel, table=True):
    """Pre-computed rental analytics for fixed timeframes."""

    __tablename__: LiteralString = "analytics_rentals_summary"

    __table_args__ = (
        Index(
            "idx_rentals_summary_lookup",
            "property_usage",
            "timeframe_days",
            "dimension",
            "dimension_value",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Time period
    timeframe_days: int  # 7, 30, 90, 180, 365

    # Required filter
    property_usage: str = Field(max_length=50)  # Residential/Commercial

    # Dimension breakdown
    dimension: Optional[str] = Field(default=None, max_length=50)
    dimension_value: Optional[str] = Field(default=None, max_length=255)

    # Metrics
    contract_count: int = Field(default=0)
    total_annual_value: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    total_area: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    avg_annual_rent: Decimal = Field(default=0, max_digits=15, decimal_places=2)
    avg_rent_sqft: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    min_annual_rent: Decimal = Field(default=0, max_digits=15, decimal_places=2)
    max_annual_rent: Decimal = Field(default=0, max_digits=15, decimal_places=2)

    # Period comparison
    prev_contract_count: int = Field(default=0)
    prev_total_annual_value: Decimal = Field(default=0, max_digits=20, decimal_places=2)

    # Metadata
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


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


# Keep old models for migration compatibility - will be dropped after migration
class AnalyticsDailySales(SQLModel, table=True):
    """DEPRECATED - Use AnalyticsSalesSummary instead."""

    __tablename__: LiteralString = "analytics_daily_sales"
    __table_args__ = (
        Index(
            "idx_analytics_sales_lookup",
            "property_usage",
            "analytics_date",
            "area_name",
            "project_name",
        ),
        Index("idx_analytics_sales_date", "analytics_date"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    analytics_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    property_usage: str = Field(max_length=50)
    area_name: Optional[str] = Field(default=None, max_length=255)
    master_project: Optional[str] = Field(default=None, max_length=255)
    project_name: Optional[str] = Field(default=None, max_length=255)
    property_type: Optional[str] = Field(default=None, max_length=255)
    rooms_description: Optional[str] = Field(default=None, max_length=100)
    property_sub_type: Optional[str] = Field(default=None, max_length=255)
    reg_type: Optional[str] = Field(default=None, max_length=255)
    transaction_count: int = Field(default=0)
    total_volume: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    total_area: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    avg_price: Decimal = Field(default=0, max_digits=15, decimal_places=2)
    avg_price_sqft: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    min_price: Decimal = Field(default=0, max_digits=15, decimal_places=2)
    max_price: Decimal = Field(default=0, max_digits=15, decimal_places=2)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AnalyticsDailyRentals(SQLModel, table=True):
    """DEPRECATED - Use AnalyticsRentalsSummary instead."""

    __tablename__: LiteralString = "analytics_daily_rentals"
    __table_args__ = (
        Index(
            "idx_analytics_rentals_lookup",
            "property_usage",
            "analytics_date",
            "area_name",
            "project_name",
        ),
        Index("idx_analytics_rentals_date", "analytics_date"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    analytics_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    property_usage: str = Field(max_length=50)
    area_name: Optional[str] = Field(default=None, max_length=255)
    master_project: Optional[str] = Field(default=None, max_length=255)
    project_name: Optional[str] = Field(default=None, max_length=255)
    ejari_property_type: Optional[str] = Field(default=None, max_length=100)
    ejari_property_sub_type: Optional[str] = Field(default=None, max_length=100)
    contract_reg_type: Optional[str] = Field(default=None, max_length=100)
    contract_count: int = Field(default=0)
    total_annual_value: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    total_area: Decimal = Field(default=0, max_digits=20, decimal_places=2)
    avg_annual_rent: Decimal = Field(default=0, max_digits=15, decimal_places=2)
    avg_rent_sqft: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    min_annual_rent: Decimal = Field(default=0, max_digits=15, decimal_places=2)
    max_annual_rent: Decimal = Field(default=0, max_digits=15, decimal_places=2)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
