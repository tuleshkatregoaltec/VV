from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    building: Optional[str] = Field(default=None, description="DXBI building name")
    project: Optional[str] = Field(default=None, description="DXBI project name")
    timeframe_days: Optional[int] = Field(
        default=None, ge=1, description="Last N calendar days, today included"
    )
    size_min: Optional[float] = None
    size_max: Optional[float] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    price_per_sqft_min: Optional[float] = None
    price_per_sqft_max: Optional[float] = None


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
    building: Optional[str] = Field(default=None, description="DXBI building name")
    project: Optional[str] = Field(default=None, description="DXBI project name")
    timeframe_days: Optional[int] = Field(
        default=None,
        ge=1,
        description="Leases starting in the last N calendar days, today included",
    )
    size_min: Optional[float] = None
    size_max: Optional[float] = None
    rent_min: Optional[float] = None
    rent_max: Optional[float] = None


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
