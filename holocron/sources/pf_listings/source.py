from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from holocron.contracts import SourceSpec

PF_LISTINGS_SOURCE_NAME = "pf_listings"
PF_PROVIDER = "propertyfinder"
PF_BASE_URL = "https://www.propertyfinder.ae"
PF_STATIC_ASSETS_BASE_URL = "https://static-assets.propertyfinder.com"
PF_DUBAI_LOCATION_ID = "1"
PF_LISTING_CATEGORY_IDS = (1, 2, 3, 4)
PF_RESIDENTIAL_CATEGORY_IDS = (1, 2)
PF_BEDROOM_ELIGIBLE_PROPERTY_TYPE_IDS = (1, 18, 20, 22, 24, 29, 31, 35, 42, 45)
PF_DEFAULT_SEARCH_BOOTSTRAP_PATH = "/en/buy/dubai/properties-for-sale.html"
PF_DEFAULT_LISTING_SEARCH_SORT = "nd"
PF_MANIFEST_PREFIX = "raw/source=pf_listings/manifests/"


class PropertyFinderListingsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = PF_BASE_URL
    static_assets_base_url: str = PF_STATIC_ASSETS_BASE_URL
    locale: str = "en"
    country_code: str = "ae"
    mode: Literal["snapshot", "plan", "search", "details"] = "snapshot"
    categories: tuple[int, ...] = PF_LISTING_CATEGORY_IDS
    location_ids: tuple[str, ...] = (PF_DUBAI_LOCATION_ID,)
    sort: str = PF_DEFAULT_LISTING_SEARCH_SORT
    bootstrap_search_path: str = PF_DEFAULT_SEARCH_BOOTSTRAP_PATH
    max_pages_per_query: int = Field(default=50, ge=1, le=50)
    max_results_per_query: int = Field(default=1000, ge=1)
    max_planned_queries: int = Field(default=12000, ge=1)
    max_search_pages_per_run: int = Field(default=50000, ge=1)
    max_partition_depth: int = Field(default=8, ge=0)
    split_by_property_type: bool = True
    split_by_location: bool = True
    split_by_bedrooms: bool = True
    split_by_price: bool = True
    location_page_limit: int = Field(default=500, ge=1, le=500)
    max_location_pages: int = Field(default=40, ge=1)
    bedroom_values: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7, 8)
    bedroom_eligible_property_type_ids: tuple[int, ...] = PF_BEDROOM_ELIGIBLE_PROPERTY_TYPE_IDS
    fetch_details: bool = True
    max_details_per_run: int = Field(default=100000, ge=0)
    manifest_prefix: str = PF_MANIFEST_PREFIX
    plan_manifest_s3_key: str = ""
    search_query_cursor: int = Field(default=0, ge=0)
    search_page_cursor: int = Field(default=1, ge=1)
    detail_manifest_cursor: int = Field(default=0, ge=0)
    detail_row_cursor: int = Field(default=0, ge=0)
    request_pause_seconds: float = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=90, ge=1)
    headless: bool = True
    chrome_path: str = ""
    storage_state_path: str = ""
    block_media_requests: bool = True

    @field_validator(
        "categories",
        "location_ids",
        "bedroom_values",
        "bedroom_eligible_property_type_ids",
        mode="before",
    )
    @classmethod
    def coerce_csv_tuple(cls, value: object) -> object:
        if isinstance(value, str):
            parts = tuple(item.strip() for item in value.split(",") if item.strip())
            if all(part.lstrip("-").isdigit() for part in parts):
                return tuple(int(part) for part in parts)
            return parts
        return value

    @model_validator(mode="after")
    def validate_config(self) -> "PropertyFinderListingsConfig":
        if not self.base_url.strip():
            raise ValueError("base_url must not be blank")
        if not self.static_assets_base_url.strip():
            raise ValueError("static_assets_base_url must not be blank")
        if not self.locale.strip():
            raise ValueError("locale must not be blank")
        if not self.country_code.strip():
            raise ValueError("country_code must not be blank")
        if not self.manifest_prefix.strip():
            raise ValueError("manifest_prefix must not be blank")
        if self.mode == "search" and not self.plan_manifest_s3_key.strip():
            raise ValueError("plan_manifest_s3_key is required in search mode")
        if not self.categories:
            raise ValueError("categories must include at least one Property Finder category id")
        if any(category <= 0 for category in self.categories):
            raise ValueError("categories must be positive integers")
        if not self.location_ids:
            raise ValueError("location_ids must include at least one Property Finder location id")
        if any(not str(location_id).strip() for location_id in self.location_ids):
            raise ValueError("location_ids must not include blank values")
        if not self.sort.strip():
            raise ValueError("sort must not be blank")
        if not self.bootstrap_search_path.strip():
            raise ValueError("bootstrap_search_path must not be blank")
        if self.fetch_details and self.max_details_per_run <= 0:
            raise ValueError("max_details_per_run must be positive when fetch_details is true")
        if any(value < 0 for value in self.bedroom_values):
            raise ValueError("bedroom_values must be non-negative integers")
        return self


def extract_release(*args, **kwargs):
    from holocron.sources.pf_listings.extract import extract_release as run_extract_release

    return run_extract_release(*args, **kwargs)


SOURCE = SourceSpec(
    name=PF_LISTINGS_SOURCE_NAME,
    provider=PF_PROVIDER,
    extractor=extract_release,
    checkpoint_strategy="partitioned_chunks",
    cadence="manual",
    description=(
        "Property Finder Dubai listing search snapshots with adaptive query partitions, "
        "optional listing detail pages, and media-oriented raw context."
    ),
)
