from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field

ListingMode = Literal["sale", "rent"]


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


class ListingPartyResponse(BaseModel):
    id: str | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    image_url: str | None = None
    logo_url: str | None = None
    address: str | None = None
    slug: str | None = None
    is_super_agent: bool | None = None
    languages: list[str] = Field(default_factory=list)


class ListingFiltersResponse(BaseModel):
    modes: list[ListingMode] = Field(default_factory=list)
    areas: list[str] = Field(default_factory=list)
    property_types: list[str] = Field(default_factory=list)
    bedrooms: list[str] = Field(default_factory=list)
    price_min: int | None = None
    price_max: int | None = None


class ListingCardResponse(BaseModel):
    listing_id: str
    listing_mode: ListingMode
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
    agent_name: str | None = None
    agent_image_url: str | None = None
    broker_name: str | None = None
    broker_logo_url: str | None = None
    listed_date: AwareDatetime | None = None
    is_available: bool | None = None
    is_verified: bool | None = None
    is_featured: bool | None = None
    is_premium: bool | None = None
    share_url: str | None = None


class ListingDetailResponse(ListingCardResponse):
    description: str | None = None
    amenities: list[str] = Field(default_factory=list)
    images: list[ListingImageResponse] = Field(default_factory=list)
    floorplans: list[ListingFloorPlanResponse] = Field(default_factory=list)
    agent: ListingPartyResponse | None = None
    broker: ListingPartyResponse | None = None
    client: ListingPartyResponse | None = None
    furnished: str | None = None
    completion_status: str | None = None
    rera: str | None = None
    number_of_cheques: int | None = None
    payment_method: list[str] = Field(default_factory=list)
    video_url: str | None = None
    view_360_url: str | None = None
    source_run_id: str | None = None
    source_manifest_key: str | None = None
    scraped_at: AwareDatetime | None = None
    demo_metadata: dict[str, Any] = Field(default_factory=dict)


class ListingListResponse(BaseModel):
    listings: list[ListingCardResponse]
    total: int
    limit: int
    offset: int
    filters: ListingFiltersResponse = Field(default_factory=ListingFiltersResponse)
