"""Analytics schemas for API responses"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel

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


class MarketTrendPoint(BaseModel):
    """Single data point for the market trend chart"""

    date: date
    transaction_count: int
    avg_price: float
    avg_price_sqm: float


class MarketTrendResponse(BaseModel):
    """Response for the market trend chart endpoint"""

    data: list[MarketTrendPoint]
    total_transactions: int
    avg_price_change_pct: Optional[float] = None
    avg_price_sqm_change_pct: Optional[float] = None


# =============================================================================
# PROJECT ANALYTICS MODELS
# =============================================================================


class ProjectMeta(BaseModel):
    """Metadata from ch_projects + ch_developers"""

    project_name: str
    area_name: Optional[str] = None
    developer_name: Optional[str] = None
    project_status: Optional[str] = None
    completion_date: Optional[date] = None
    percent_completed: Optional[float] = None
    no_of_units: Optional[int] = None
    no_of_buildings: Optional[int] = None


class ProjectSalesSummary(BaseModel):
    transaction_count: int
    total_volume: float
    avg_price: float
    avg_price_sqm: float
    median_price: float


class ProjectRentalSummary(BaseModel):
    contract_count: int
    total_annual_value: float
    median_annual_rent: float
    median_rent_sqm: float


class RoomAnalytics(BaseModel):
    """Combined sales + rental + yield metrics per bedroom count"""

    rooms: str
    sale_count: int
    avg_sale_price: float
    avg_sale_price_sqm: float
    rental_count: int
    median_annual_rent: float
    median_rent_sqm: float
    gross_yield_pct: Optional[float] = None


class PropertyTypeBreakdown(BaseModel):
    property_type: str
    count: int
    avg_price: float
    pct_of_total: float


class RegTypeBreakdown(BaseModel):
    reg_type: str
    count: int
    avg_price: float
    pct_of_total: float


class AnalyticsUnitComposition(BaseModel):
    rooms: str
    count: int
    pct_of_total: float


class ProjectAnalyticsResponse(BaseModel):
    """Full analytics response for a single project"""

    project: Optional[ProjectMeta] = None
    sales: ProjectSalesSummary
    rentals: ProjectRentalSummary
    overall_gross_yield_pct: Optional[float] = None
    by_rooms: list[RoomAnalytics]
    by_property_type: list[PropertyTypeBreakdown]
    by_reg_type: list[RegTypeBreakdown]
    unit_composition: list[AnalyticsUnitComposition]


class ProjectTrendPoint(BaseModel):
    date: date
    transaction_count: int
    avg_price: float
    avg_price_sqm: float


class ProjectTrendsResponse(BaseModel):
    data: list[ProjectTrendPoint]


class ProjectSearchItem(BaseModel):
    name: str
    filter_type: str  # "master" | "virtual_master" | "project"


class ProjectSearchResponse(BaseModel):
    projects: list[ProjectSearchItem]


class SubProjectItem(BaseModel):
    name: str
    transaction_count: int


class SubProjectsResponse(BaseModel):
    sub_projects: list[SubProjectItem]
