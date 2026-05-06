from datetime import date
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class UpcomingProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    project_name: str
    developer_name: str
    developer_id: Optional[int] = None
    area_name: str
    project_start_date: Optional[date] = None
    project_end_date: Optional[date] = None
    percent_completed: int = 0
    no_of_buildings: Optional[int] = None
    no_of_units: Optional[int] = None


class UpcomingProjectsResponse(BaseModel):
    projects: List[UpcomingProjectResponse]
    total: int


class SupplyCatalogueAssetResponse(BaseModel):
    id: int
    asset_type: str
    name: str | None = None
    url: str
    download_url: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None


class SupplyCatalogueUnitResponse(BaseModel):
    label: str
    unit_type: str | None = None
    bedrooms: str | None = None
    price_from_aed: int | None = None
    price_to_aed: int | None = None
    area_from_sqft: float | None = None
    area_to_sqft: float | None = None
    units_amount: int | None = None


class SupplyCataloguePaymentStepResponse(BaseModel):
    label: str
    percent: str | None = None
    order: int | None = None


class SupplyCatalogueBuildingResponse(BaseModel):
    name: str
    description: str | None = None


class SupplyCatalogueNearbyPointResponse(BaseModel):
    name: str
    distance_km: float | None = None
    time_min: float | None = None


class SupplyCatalogueProjectCardResponse(BaseModel):
    project_id: int
    project_name: str
    developer_name: str
    developer_id: int | None = None
    area_name: str | None = None
    region: str | None = None
    status: str | None = None
    sale_status: str | None = None
    completion_date: str | None = None
    min_price_aed: int | None = None
    max_price_aed: int | None = None
    units_in_sale: int | None = None
    unit_types: list[str] = Field(default_factory=list)
    overview_excerpt: str | None = None
    cover_image_url: str | None = None
    developer_logo_url: str | None = None
    image_count: int = 0
    floorplan_count: int = 0
    brochure_count: int = 0


class SupplyCatalogueProjectsResponse(BaseModel):
    projects: list[SupplyCatalogueProjectCardResponse]
    total: int
    limit: int
    offset: int
    areas: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)


class SupplyCatalogueProjectDetailResponse(SupplyCatalogueProjectCardResponse):
    overview: str | None = None
    coordinates: dict[str, float] | None = None
    units: list[SupplyCatalogueUnitResponse] = Field(default_factory=list)
    payment_plan: list[SupplyCataloguePaymentStepResponse] = Field(default_factory=list)
    facilities: list[str] = Field(default_factory=list)
    buildings: list[SupplyCatalogueBuildingResponse] = Field(default_factory=list)
    nearby_points: list[SupplyCatalogueNearbyPointResponse] = Field(default_factory=list)
    gallery: list[SupplyCatalogueAssetResponse] = Field(default_factory=list)
    floorplans: list[SupplyCatalogueAssetResponse] = Field(default_factory=list)
    brochures: list[SupplyCatalogueAssetResponse] = Field(default_factory=list)
    master_plans: list[SupplyCatalogueAssetResponse] = Field(default_factory=list)
    demo_metadata: dict[str, Any] = Field(default_factory=dict)
