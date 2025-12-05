"""Analytics schemas for API responses"""

from pydantic import BaseModel
from typing import Optional, Literal
from datetime import date


# Valid timeframe options
TimeframeDays = Literal[7, 30, 90, 180, 365]


class AnalyticsSummary(BaseModel):
    """Summary KPI metrics for analytics dashboard"""

    transaction_count: int
    total_volume: float
    avg_price: float
    avg_price_sqft: float
    min_price: float
    max_price: float
    volume_change_pct: Optional[float] = None  # % change vs previous period
    count_change_pct: Optional[float] = None


class RentalSummary(BaseModel):
    """Summary KPI metrics for rental analytics"""

    contract_count: int
    total_annual_value: float
    avg_annual_rent: float
    avg_rent_sqft: float
    min_annual_rent: float
    max_annual_rent: float
    value_change_pct: Optional[float] = None
    count_change_pct: Optional[float] = None


class DimensionBreakdown(BaseModel):
    """Breakdown by a specific dimension (property_type, rooms, etc.)"""

    dimension_value: str
    transaction_count: int
    total_volume: float
    avg_price_sqft: float
    pct_of_total: Optional[float] = None


class RentalDimensionBreakdown(BaseModel):
    """Breakdown by a specific dimension for rentals"""

    dimension_value: str
    contract_count: int
    total_annual_value: float
    avg_rent_sqft: float
    pct_of_total: Optional[float] = None


class TrendPoint(BaseModel):
    """Single data point for trend charts"""

    date: date
    count: int
    total_value: float
    avg_value: float
    avg_sqft: float


class AnalyticsResponse(BaseModel):
    """Complete analytics response for dashboard"""

    timeframe_days: int
    property_usage: str
    summary: AnalyticsSummary
    trends: list[TrendPoint]
    by_property_type: list[DimensionBreakdown]
    by_rooms: list[DimensionBreakdown]
    by_reg_type: list[DimensionBreakdown]
    by_master_project: list[DimensionBreakdown]


class RentalAnalyticsResponse(BaseModel):
    """Complete rental analytics response for dashboard"""

    timeframe_days: int
    property_usage: str
    summary: RentalSummary
    trends: list[TrendPoint]
    by_property_type: list[RentalDimensionBreakdown]
    by_master_project: list[RentalDimensionBreakdown]


# Legacy schemas for backwards compatibility
class AnalyticsTrend(BaseModel):
    """Time series data point for trend charts"""

    date: date
    transaction_count: int
    total_volume: float
    avg_price: float
    avg_price_sqft: float


class AreaBreakdown(BaseModel):
    """Area-level breakdown for comparison tables/charts"""

    area_name: str
    transaction_count: int
    total_volume: float
    avg_price_sqft: float
    pct_of_total: Optional[float] = None


class RentalTrend(BaseModel):
    """Time series data point for rental trend charts"""

    date: date
    contract_count: int
    total_annual_value: float
    avg_annual_rent: float
    avg_rent_sqft: float


class RentalAreaBreakdown(BaseModel):
    """Area-level breakdown for rental comparison"""

    area_name: str
    contract_count: int
    total_annual_value: float
    avg_rent_sqft: float
    pct_of_total: Optional[float] = None
