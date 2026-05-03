from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from holocron.contracts import BronzeTable, SourceSpec

BAY_LOCATIONS_SOURCE_NAME = "bay_locations"
BAY_PROVIDER = "bayut"
BAYUT_BASE_URL = "https://uae-real-estate2.p.rapidapi.com"
BAYUT_DUBAI_LOCATION_ID = 2
DEFAULT_DUBAI_LOCATION_QUERIES = (
    "dubai",
    "al",
    "city",
    "dubai marina",
    "jumeirah",
    "business bay",
    "downtown dubai",
    "jvc",
    "dubai hills",
    "palm jumeirah",
    "emirates",
    "meydan",
    "creek",
    "jebel",
    "nad",
    "warsan",
    "mirdif",
    "arabian",
    "damac",
    "springs",
    "meadows",
    "lakes",
    "village",
    "triangle",
    "ranches",
)


class BayutLocationsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = ""
    base_url: str = BAYUT_BASE_URL
    queries: tuple[str, ...] = DEFAULT_DUBAI_LOCATION_QUERIES
    langs: str = "en,ar"
    max_pages: int = Field(default=1, ge=1)
    only_dubai: bool = True
    include_ancestors: bool = True
    stop_after_pages_without_new: int = Field(default=1, ge=0)
    request_pause_seconds: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_config(self) -> "BayutLocationsConfig":
        if not tuple(query.strip() for query in self.queries if query.strip()):
            raise ValueError("queries must include at least one non-empty search term")
        return self


def extract_release(*args, **kwargs):
    from holocron.sources.bay_locations.extract import extract_release as run_extract_release

    return run_extract_release(*args, **kwargs)


def load_bronze(*args, **kwargs):
    from holocron.sources.bay_locations.bronze import load_release_to_clickhouse

    return load_release_to_clickhouse(*args, **kwargs)


SOURCE = SourceSpec(
    name=BAY_LOCATIONS_SOURCE_NAME,
    provider=BAY_PROVIDER,
    extractor=extract_release,
    bronze_loader=load_bronze,
    bronze_tables=(BronzeTable(name="bay_locations_bronze"),),
    checkpoint_strategy="full_refresh",
    cadence="0 6 * * 1",
    description="Weekly Dubai Bayut location discovery for transaction/listing filters.",
)
