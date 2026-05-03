from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

from holocron.contracts import BronzeTable, SourceSpec

DLD_SOURCE_NAME = "dld_transactions"
DLD_PROVIDER = "dld"
DLD_CONSUMER_ID = "gkb3WvEG0rY9eilwXC0P2pTz8UzvLj9F"
DATE_CHECKPOINT_STRATEGY = "daily"
TRANSACTION_KINDS = ("sales", "mortgage", "others")


@dataclass(frozen=True, slots=True)
class DailySlice:
    day: date

    @property
    def key(self) -> str:
        return self.day.isoformat()


class DldConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "incremental"
    start_date: date | None = None
    end_date: date | None = None
    lookback_days: int = Field(default=3, ge=0)
    transaction_kinds: tuple[str, ...] = TRANSACTION_KINDS
    data_mode: str = "Flat"
    include_daily_totals: bool = True
    consumer_id: str = DLD_CONSUMER_ID

    @model_validator(mode="after")
    def validate_config(self) -> "DldConfig":
        if self.mode not in {"incremental", "backfill"}:
            raise ValueError("mode must be 'incremental' or 'backfill'")
        if self.mode == "backfill" and (self.start_date is None or self.end_date is None):
            raise ValueError("backfill mode requires start_date and end_date")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        invalid_kinds = sorted(set(self.transaction_kinds) - set(TRANSACTION_KINDS))
        if invalid_kinds:
            raise ValueError(f"unsupported transaction kinds: {', '.join(invalid_kinds)}")
        if self.data_mode not in {"Flat", "Aggregated"}:
            raise ValueError("data_mode must be 'Flat' or 'Aggregated'")
        return self


def utc_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).date()


def resolve_date_window(config: DldConfig, *, today: date | None = None) -> tuple[date, date]:
    current_day = today or utc_today()
    if config.mode == "backfill":
        return config.start_date, config.end_date  # type: ignore[return-value]
    return current_day - timedelta(days=config.lookback_days), current_day


def build_daily_slices(config: DldConfig, *, today: date | None = None) -> tuple[DailySlice, ...]:
    start_date, end_date = resolve_date_window(config, today=today)
    days: list[DailySlice] = []
    current = start_date
    while current <= end_date:
        days.append(DailySlice(day=current))
        current += timedelta(days=1)
    return tuple(days)


def extract_release(*args, **kwargs):
    from holocron.sources.dld.extract import extract_release as run_extract_release

    return run_extract_release(*args, **kwargs)


def load_bronze(*args, **kwargs):
    from holocron.sources.dld.bronze import load_release_to_clickhouse

    return load_release_to_clickhouse(*args, **kwargs)


SOURCE = SourceSpec(
    name=DLD_SOURCE_NAME,
    provider=DLD_PROVIDER,
    extractor=extract_release,
    bronze_loader=load_bronze,
    bronze_tables=(BronzeTable(name="dld_transactions_bronze"),),
    checkpoint_strategy=DATE_CHECKPOINT_STRATEGY,
    cadence="daily",
    description="Dubai Land Department transaction JSON extraction into immutable raw releases.",
)
