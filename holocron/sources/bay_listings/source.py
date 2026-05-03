from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from holocron.contracts import BronzeTable, SourceSpec

BAY_LISTINGS_SOURCE_NAME = "bay_listings"
BAY_PROVIDER = "bayut"
BAYUT_BASE_URL = "https://uae-real-estate2.p.rapidapi.com"
BAYUT_DUBAI_LOCATION_ID = 2
LISTING_PURPOSES = ("for-sale", "for-rent")


class BayutListingsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = ""
    base_url: str = BAYUT_BASE_URL
    locations_ids: tuple[int, ...] = (BAYUT_DUBAI_LOCATION_ID,)
    purposes: tuple[str, ...] = LISTING_PURPOSES
    categories: tuple[str, ...] = ("residential",)
    langs: str = "en,ar"
    index: str = "latest"
    max_pages: int = Field(default=2, ge=1)
    rent_frequency: str = "yearly"
    request_pause_seconds: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_config(self) -> "BayutListingsConfig":
        invalid_purposes = sorted(set(self.purposes) - set(LISTING_PURPOSES))
        if invalid_purposes:
            raise ValueError(f"unsupported listing purposes: {', '.join(invalid_purposes)}")
        if not self.locations_ids:
            raise ValueError("locations_ids must include at least one Bayut location id")
        return self


def extract_release(*args, **kwargs):
    from holocron.sources.bay_listings.extract import extract_release as run_extract_release

    return run_extract_release(*args, **kwargs)


def load_bronze(*args, **kwargs):
    from holocron.sources.bay_listings.bronze import load_release_to_clickhouse

    return load_release_to_clickhouse(*args, **kwargs)


SOURCE = SourceSpec(
    name=BAY_LISTINGS_SOURCE_NAME,
    provider=BAY_PROVIDER,
    extractor=extract_release,
    bronze_loader=load_bronze,
    bronze_tables=(BronzeTable(name="bay_listings_bronze"),),
    checkpoint_strategy="latest_pages",
    cadence="daily",
    description="Daily Dubai Bayut listing search snapshots from the unofficial RapidAPI API.",
)
