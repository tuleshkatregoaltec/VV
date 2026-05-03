from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from holocron.contracts import BronzeTable, SourceSpec

BAY_TRANSACTIONS_SOURCE_NAME = "bay_transactions"
BAY_PROVIDER = "bayut"
BAYUT_BASE_URL = "https://uae-real-estate2.p.rapidapi.com"
TRANSACTION_PURPOSES = ("for-sale", "for-rent")
DEFAULT_DUBAI_TRANSACTION_COMMUNITY_IDS = (
    10,
    12,
    14,
    23,
    25,
    33,
    36,
    41,
    43,
    51,
    53,
    54,
    56,
    59,
    67,
    71,
    73,
    79,
    81,
    87,
    91,
    95,
    103,
    105,
    111,
    117,
    133,
    159,
    161,
    164,
    168,
    187,
    190,
    196,
    242,
    268,
    274,
    279,
    295,
    302,
    345,
    347,
    352,
    368,
    545,
    562,
    603,
    613,
    620,
    653,
    835,
    914,
    1045,
    1347,
    1375,
    1509,
    1519,
    1524,
    1621,
    1973,
    2848,
    3355,
    3512,
    5036,
    5099,
    5178,
    16296,
    16485,
    75266,
    76512,
    85082,
    87876,
    89404,
    89789,
)


@dataclass(frozen=True, slots=True)
class DateWindow:
    start_date: date
    end_date: date

    @property
    def key(self) -> str:
        return f"{self.start_date.isoformat()}_{self.end_date.isoformat()}"


class BayutTransactionsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = ""
    base_url: str = BAYUT_BASE_URL
    mode: str = "incremental"
    start_date: date | None = None
    end_date: date | None = None
    lookback_days: int = Field(default=7, ge=0)
    purposes: tuple[str, ...] = TRANSACTION_PURPOSES
    category: str = "residential"
    completion_status: str = "completed"
    contract_type: str = "All"
    sort_by: str = "date"
    order: str = "desc"
    time_frame: str = "12m"
    locations_ids: tuple[int, ...] = DEFAULT_DUBAI_TRANSACTION_COMMUNITY_IDS
    location_batch_size: int = Field(default=1, ge=1)
    max_pages: int = Field(default=1, ge=1)
    request_pause_seconds: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_config(self) -> "BayutTransactionsConfig":
        if self.mode not in {"incremental", "backfill"}:
            raise ValueError("mode must be 'incremental' or 'backfill'")
        if self.mode == "backfill" and (self.start_date is None or self.end_date is None):
            raise ValueError("backfill mode requires start_date and end_date")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        invalid_purposes = sorted(set(self.purposes) - set(TRANSACTION_PURPOSES))
        if invalid_purposes:
            raise ValueError(f"unsupported transaction purposes: {', '.join(invalid_purposes)}")
        return self


def utc_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).date()


def resolve_date_window(
    config: BayutTransactionsConfig,
    *,
    today: date | None = None,
) -> DateWindow:
    current_day = today or utc_today()
    if config.mode == "backfill":
        return DateWindow(config.start_date, config.end_date)  # type: ignore[arg-type]
    return DateWindow(current_day - timedelta(days=config.lookback_days), current_day)


def transaction_request_body(
    config: BayutTransactionsConfig,
    *,
    purpose: str,
    window: DateWindow,
    locations_ids: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "purpose": purpose,
        "category": config.category,
        "completion_status": config.completion_status,
        "contract_type": config.contract_type,
        "sort_by": config.sort_by,
        "order": config.order,
        "start_date": window.start_date.isoformat(),
        "end_date": window.end_date.isoformat(),
        "time_frame": config.time_frame,
    }
    resolved_locations_ids = config.locations_ids if locations_ids is None else locations_ids
    if resolved_locations_ids:
        body["locations_ids"] = list(resolved_locations_ids)
    return body


def extract_release(*args, **kwargs):
    from holocron.sources.bay_transactions.extract import extract_release as run_extract_release

    return run_extract_release(*args, **kwargs)


def load_bronze(*args, **kwargs):
    from holocron.sources.bay_transactions.bronze import load_release_to_clickhouse

    return load_release_to_clickhouse(*args, **kwargs)


SOURCE = SourceSpec(
    name=BAY_TRANSACTIONS_SOURCE_NAME,
    provider=BAY_PROVIDER,
    extractor=extract_release,
    bronze_loader=load_bronze,
    bronze_tables=(BronzeTable(name="bay_transactions_bronze"),),
    checkpoint_strategy="date_window",
    cadence="daily",
    description="Daily Dubai Bayut transaction snapshots from the unofficial RapidAPI API.",
)
