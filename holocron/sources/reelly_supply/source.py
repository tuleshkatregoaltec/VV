from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from holocron.contracts import SourceSpec

REELLY_SUPPLY_SOURCE_NAME = "reelly_supply"
REELLY_PROVIDER = "reelly"
REELLY_API_BASE_URL = "https://api.reelly.io/api:sk5LT7jx"
REELLY_DOCUMENTS_BASE_URL = "https://xdil-qda0-zofk.m2.xano.io/api:sk5LT7jx"
REELLY_AVAILABILITY_BASE_URL = "https://xdil-qda0-zofk.m2.xano.io/api:ukkgO6DN"
REELLY_DEFAULT_REGION = "2"
REELLY_DEFAULT_SALE_STATUSES = ("start_of_sales", "on_sale", "out_of_stock")
REELLY_DEFAULT_ALLOWED_DOCUMENT_HOSTS = (
    "api.reelly.io",
    "drive.google.com",
    "drive.usercontent.google.com",
    ".googleusercontent.com",
    "storage.googleapis.com",
    "xdil-qda0-zofk.m2.xano.io",
)


class ReellySupplyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = ""
    password: str = ""
    base_url: str = REELLY_API_BASE_URL
    documents_base_url: str = REELLY_DOCUMENTS_BASE_URL
    availability_base_url: str = REELLY_AVAILABILITY_BASE_URL
    region: str = REELLY_DEFAULT_REGION
    sale_statuses: tuple[str, ...] = REELLY_DEFAULT_SALE_STATUSES
    pages_per_run: int = Field(default=5, ge=1)
    start_page: int = Field(default=1, ge=1)
    page_cursor: int | None = Field(default=None, ge=1)
    max_pages: int | None = Field(default=None, ge=1)
    download_documents: bool = True
    download_all_project_docs: bool = True
    max_document_mb: int = Field(default=100, ge=1)
    allowed_document_hosts: tuple[str, ...] = REELLY_DEFAULT_ALLOWED_DOCUMENT_HOSTS
    try_matrix_availability: bool = True
    matrix_endpoints: tuple[str, ...] = ("floors", "bedrooms")
    request_pause_seconds: float = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=60, ge=1)

    @field_validator("sale_statuses", mode="before")
    @classmethod
    def coerce_sale_statuses(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(status.strip() for status in value.split(",") if status.strip())
        return value

    @field_validator("allowed_document_hosts", mode="before")
    @classmethod
    def coerce_allowed_document_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(host.strip() for host in value.split(",") if host.strip())
        return value

    @model_validator(mode="after")
    def validate_config(self) -> "ReellySupplyConfig":
        if not self.sale_statuses:
            raise ValueError("sale_statuses must include at least one status")
        if not self.region.strip():
            raise ValueError("region must not be blank")
        if not self.base_url.strip():
            raise ValueError("base_url must not be blank")
        if not self.documents_base_url.strip():
            raise ValueError("documents_base_url must not be blank")
        if not self.availability_base_url.strip():
            raise ValueError("availability_base_url must not be blank")
        if not self.matrix_endpoints:
            raise ValueError("matrix_endpoints must include at least one endpoint")
        if not self.allowed_document_hosts:
            raise ValueError("allowed_document_hosts must include at least one host")
        if any(not host.strip() for host in self.allowed_document_hosts):
            raise ValueError("allowed_document_hosts must not include blank hosts")
        return self

    @property
    def resolved_start_page(self) -> int:
        return self.page_cursor or self.start_page


def extract_release(*args, **kwargs):
    from holocron.sources.reelly_supply.extract import extract_release as run_extract_release

    return run_extract_release(*args, **kwargs)


SOURCE = SourceSpec(
    name=REELLY_SUPPLY_SOURCE_NAME,
    provider=REELLY_PROVIDER,
    extractor=extract_release,
    checkpoint_strategy="cursor_pages",
    cadence="daily",
    description="Bounded raw Reelly supply extraction with project details, documents, and availability probes.",
)
