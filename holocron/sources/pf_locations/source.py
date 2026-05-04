from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from holocron.contracts import SourceSpec

PF_LOCATIONS_SOURCE_NAME = "pf_locations"
PF_PROVIDER = "propertyfinder"
PF_BASE_URL = "https://www.propertyfinder.ae"
PF_STATIC_ASSETS_BASE_URL = "https://static-assets.propertyfinder.com"
PF_DUBAI_LOCATION_ID = "1"
PF_LISTING_CATEGORY_IDS = (1, 2, 3, 4)


class PropertyFinderLocationsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = PF_BASE_URL
    static_assets_base_url: str = PF_STATIC_ASSETS_BASE_URL
    locale: str = "en"
    country_code: str = "ae"
    categories: tuple[int, ...] = PF_LISTING_CATEGORY_IDS
    location_page_limit: int = Field(default=500, ge=1, le=500)
    max_location_pages: int = Field(default=40, ge=1)
    only_dubai: bool = True
    dubai_location_id: str = PF_DUBAI_LOCATION_ID
    request_pause_seconds: float = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=60, ge=1)

    @field_validator("categories", mode="before")
    @classmethod
    def coerce_categories(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(int(item.strip()) for item in value.split(",") if item.strip())
        return value

    @model_validator(mode="after")
    def validate_config(self) -> "PropertyFinderLocationsConfig":
        if not self.base_url.strip():
            raise ValueError("base_url must not be blank")
        if not self.static_assets_base_url.strip():
            raise ValueError("static_assets_base_url must not be blank")
        if not self.locale.strip():
            raise ValueError("locale must not be blank")
        if not self.country_code.strip():
            raise ValueError("country_code must not be blank")
        if not self.categories:
            raise ValueError("categories must include at least one Property Finder category id")
        if any(category <= 0 for category in self.categories):
            raise ValueError("categories must be positive integers")
        if not self.dubai_location_id.strip():
            raise ValueError("dubai_location_id must not be blank")
        return self


def extract_release(*args, **kwargs):
    from holocron.sources.pf_locations.extract import extract_release as run_extract_release

    return run_extract_release(*args, **kwargs)


SOURCE = SourceSpec(
    name=PF_LOCATIONS_SOURCE_NAME,
    provider=PF_PROVIDER,
    extractor=extract_release,
    checkpoint_strategy="full_refresh",
    cadence="manual",
    description=(
        "Property Finder Dubai location hierarchy and listing filter settings for "
        "scrape planning and future cross-source joins."
    ),
)
