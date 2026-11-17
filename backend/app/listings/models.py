from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

ListingMode = Literal["sale", "rent"]
ListingAssetClass = Literal["residential", "commercial"]
ListingMarketPosition = Literal["below_market", "near_market", "above_market", "insufficient_data"]
ListingBenchmarkLevel = Literal["building_layout", "project_layout", "insufficient_data"]
ListingUrgencySignal = Literal["explicit_urgency", "value_language", "none"]
# dld_sales: estimated from DLD sales of similar homes (app.listings.valuation, 11 Nov 2026).
# asking_peers: compared with the asking prices of peer listings (rent, commercial, off-plan).
ListingValuationMethod = Literal["dld_sales", "asking_peers"]


class ListingImageResponse(BaseModel):
    small_url: str | None = None
    medium_url: str | None = None
    original_url: str | None = None
    url: str | None = None
    label: str | None = None


class ListingFloorPlanResponse(BaseModel):
    title: str | None = None
    image_url: str | None = None
    area_sqft: float | None = None
    floor_number: int | None = None
    unit_number: str | None = None
    dimension: str | None = None


class ListingFiltersResponse(BaseModel):
    modes: list[ListingMode] = Field(default_factory=list)
    asset_classes: list[ListingAssetClass] = Field(default_factory=list)
    areas: list[str] = Field(default_factory=list)
    property_types: list[str] = Field(default_factory=list)
    bedrooms: list[str] = Field(default_factory=list)
    price_min: int | None = None
    price_max: int | None = None


class ListingCardResponse(BaseModel):
    listing_id: str
    listing_mode: ListingMode
    asset_class: ListingAssetClass
    title: str
    reference: str | None = None
    property_type: str | None = None
    price_value: int | None = None
    price_currency: str | None = None
    price_period: str | None = None
    size_value: float | None = None
    size_unit: str | None = None
    bedrooms: str | None = None
    bathrooms: str | None = None
    city_name: str | None = None
    area_name: str | None = None
    subcommunity_name: str | None = None
    tower_name: str | None = None
    location_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    primary_image_url: str | None = None
    image_count: int = 0
    floorplan_count: int = 0
    broker_name: str | None = None
    broker_logo_url: str | None = None
    captured_at: AwareDatetime | None = None
    listed_date: AwareDatetime | None = None
    listing_age_days: int | None = None
    price_per_sqft_aed: float | None = None
    market_median_price_per_sqft_aed: float | None = None
    market_estimate_aed: float | None = None
    market_delta_pct: float | None = None
    market_position: ListingMarketPosition = "insufficient_data"
    comparable_count: int = 0
    benchmark_level: ListingBenchmarkLevel = "insufficient_data"
    urgency_signal: ListingUrgencySignal = "none"
    urgency_terms: list[str] = Field(default_factory=list)
    valuation_method: ListingValuationMethod = "asking_peers"
    estimated_value_aed: float | None = None
    estimated_value_low_aed: float | None = None
    estimated_value_high_aed: float | None = None
    valuation_confidence: Literal["high", "medium", "low"] | None = None
    # Asking price / estimated value - 1: -0.12 means asking 12% below the estimate.
    value_gap_pct: float | None = None
    is_off_plan: bool = False
    # When the estimate was made; its evidence is the 12 months of sales before this date.
    valued_at: date | None = None
    is_available: bool | None = None
    is_verified: bool | None = None
    is_featured: bool | None = None
    is_premium: bool | None = None
    share_url: str | None = None


class ListingComparableSale(BaseModel):
    """A DLD sale behind a listing's estimate: same building, type and bedrooms, closest size."""

    date: date
    unit: str | None = None
    size_sqft: float
    price_aed: int
    psf: float


class ListingDetailResponse(ListingCardResponse):
    description: str | None = None
    amenities: list[str] = Field(default_factory=list)
    images: list[ListingImageResponse] = Field(default_factory=list)
    floorplans: list[ListingFloorPlanResponse] = Field(default_factory=list)
    furnished: str | None = None
    completion_status: str | None = None
    rera: str | None = None
    number_of_cheques: int | None = None
    payment_method: list[str] = Field(default_factory=list)
    video_url: str | None = None
    view_360_url: str | None = None
    valuation_comparables: list[ListingComparableSale] = Field(default_factory=list)


class ListingListResponse(BaseModel):
    listings: list[ListingCardResponse]
    total: int
    limit: int
    offset: int
    filters: ListingFiltersResponse = Field(default_factory=ListingFiltersResponse)
    # When the listing data was last collected; listings may have sold or changed since.
    data_as_of: AwareDatetime | None = None


class ListingTrendPoint(BaseModel):
    period: str
    average_asking_price_aed: float | None = None
    median_asking_price_aed: float | None = None
    median_price_per_sqft_aed: float | None = None
    listing_count: int = 0
    median_achieved_price_per_sqft_aed: float | None = None
    achieved_transaction_count: int = 0


class ListingAnalyticsResponse(BaseModel):
    total: int = 0
    average_price_aed: float | None = None
    median_price_aed: float | None = None
    median_price_per_sqft_aed: float | None = None
    average_listing_age_days: float | None = None
    median_listing_age_days: float | None = None
    newly_listed_30d: int = 0
    below_market_count: int = 0
    near_market_count: int = 0
    above_market_count: int = 0
    benchmarked_count: int = 0
    verified_count: int = 0
    area_count: int = 0
    snapshot_at: AwareDatetime | None = None
    data_as_of: AwareDatetime | None = None
    trend: list[ListingTrendPoint] = Field(default_factory=list)
