from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

# Request bounds (the query dependencies and these models share them). The warehouse binds
# offsets and day counts as Int32; DXBI's records start in 2014, so 10,000 days covers them all.
MAX_PAGE_SIZE = 1000
MAX_OFFSET = 1_000_000
MAX_TIMEFRAME_DAYS = 10_000
MAX_NAME_LENGTH = 200
MAX_SIZE_SQFT = 100_000_000.0
MAX_AMOUNT_AED = 1_000_000_000_000.0
MAX_PRICE_PER_SQFT_AED = 10_000_000.0
MAX_SELECTED_EXPORT_IDS = 1000


def _band(maximum: float):
    return Field(default=None, ge=0, le=maximum, allow_inf_nan=False)


class SalesFilters(BaseModel):
    """Filters of the DXBI sales page. Range bounds are half-open: min inclusive, max exclusive."""

    model_config = ConfigDict(frozen=True)

    property_usage: Optional[str] = Field(
        default=None, description="Residential or Commercial (grouped from DXBI property types)"
    )
    property_type: Optional[str] = Field(default=None, description="DXBI property type")
    bedrooms: Optional[str] = Field(default=None, description="'Studio', '1 Bed', '2 Beds', ...")
    status: Optional[str] = Field(default=None, description="Off-Plan or Ready")
    location: Optional[str] = Field(
        default=None, description="DXBI area or community: every record its DXBI area page counts"
    )
    location_search: Optional[str] = Field(
        default=None, max_length=200, description="Keywords across DXBI building, project and area"
    )
    building: Optional[str] = Field(default=None, description="DXBI building name")
    project: Optional[str] = Field(default=None, description="DXBI project name")
    timeframe_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=MAX_TIMEFRAME_DAYS,
        description="Last N calendar days in Dubai, today included",
    )
    size_min: Optional[float] = _band(MAX_SIZE_SQFT)
    size_max: Optional[float] = _band(MAX_SIZE_SQFT)
    price_min: Optional[float] = _band(MAX_AMOUNT_AED)
    price_max: Optional[float] = _band(MAX_AMOUNT_AED)
    price_per_sqft_min: Optional[float] = _band(MAX_PRICE_PER_SQFT_AED)
    price_per_sqft_max: Optional[float] = _band(MAX_PRICE_PER_SQFT_AED)


class RentalFilters(BaseModel):
    """Filters of the DXBI rentals page. Range bounds are half-open: min inclusive, max exclusive."""

    model_config = ConfigDict(frozen=True)

    property_usage: Optional[str] = Field(
        default=None, description="Residential or Commercial (grouped from DXBI property types)"
    )
    property_type: Optional[str] = Field(default=None, description="DXBI property type")
    bedrooms: Optional[str] = Field(default=None, description="'Studio', '1 Bed', '2 Beds', ...")
    contract_type: Optional[str] = Field(default=None, description="New or Renewed")
    location: Optional[str] = Field(
        default=None, description="DXBI area or community: every record its DXBI area page counts"
    )
    location_search: Optional[str] = Field(
        default=None, max_length=200, description="Keywords across DXBI building, project and area"
    )
    building: Optional[str] = Field(default=None, description="DXBI building name")
    project: Optional[str] = Field(default=None, description="DXBI project name")
    timeframe_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=MAX_TIMEFRAME_DAYS,
        description="Leases starting in the last N calendar days in Dubai, today included",
    )
    size_min: Optional[float] = _band(MAX_SIZE_SQFT)
    size_max: Optional[float] = _band(MAX_SIZE_SQFT)
    rent_min: Optional[float] = _band(MAX_AMOUNT_AED)
    rent_max: Optional[float] = _band(MAX_AMOUNT_AED)


class TransactionResponse(BaseModel):
    """One DXBI sale (dxbi_sales_unit_events): sizes in sq ft, prices in AED."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    transaction_id: str
    transaction_date: Optional[date] = None
    unit_number: Optional[str] = None
    building_name: Optional[str] = None
    project_name: Optional[str] = None
    master_project: Optional[str] = Field(
        default=None, description="DLD master project (filled from the matched DLD record)"
    )
    dld_area: Optional[str] = Field(default=None, description="DLD's official area name")
    location: Optional[str] = Field(
        default=None, description="Unit, building, project, master project and area in one line"
    )
    map_url: Optional[str] = Field(default=None, description="Google Maps link to the location")
    location_name: Optional[str] = None
    property_type: Optional[str] = None
    bedrooms: Optional[str] = None
    status: Optional[str] = None
    size_sqft: Optional[float] = None
    price_aed: Optional[int] = None
    price_per_sqft_aed: Optional[int] = None


class TransactionListResponse(BaseModel):
    transactions: List[TransactionResponse]
    total: int
    limit: int
    offset: int


class RentalContractResponse(BaseModel):
    """One DXBI lease of one unit (dxbi_rental_events): sizes in sq ft, amounts in AED."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    contract_id: str
    lease_start: Optional[date] = None
    lease_end: Optional[date] = None
    unit_number: Optional[str] = None
    building_name: Optional[str] = None
    project_name: Optional[str] = None
    master_project: Optional[str] = Field(
        default=None, description="DLD master project (filled from the matched DLD record)"
    )
    dld_area: Optional[str] = Field(default=None, description="DLD's official area name")
    location: Optional[str] = Field(
        default=None, description="Unit, building, project, master project and area in one line"
    )
    map_url: Optional[str] = Field(default=None, description="Google Maps link to the location")
    location_name: Optional[str] = None
    property_type: Optional[str] = None
    bedrooms: Optional[str] = None
    size_sqft: Optional[float] = None
    annual_rent_aed: Optional[int] = None
    contract_amount_aed: Optional[int] = None
    term_months: Optional[float] = None
    contract_type: Optional[str] = None


class RentalContractListResponse(BaseModel):
    contracts: List[RentalContractResponse]
    total: int
    limit: int
    offset: int


class FilterOptionsResponse(BaseModel):
    """Filter options for the DXBI sales or rentals page, narrowed by the current filters."""

    locations: List[str] = []
    buildings: List[str] = []
    projects: List[str] = []
    property_types: List[str] = []
    bedrooms: List[str] = []
    statuses: List[str] = []  # Sales: Off-Plan / Ready
    contract_types: List[str] = []  # Rentals: New / Renewed
