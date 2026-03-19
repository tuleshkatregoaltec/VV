"""Bayut source definition for Holocron."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from holocron.framework.models import (
    APPEND,
    REFERENCE_REPLACE,
    SourceSpec,
    TableSpec,
    optional_int,
    optional_str,
    release_id_field,
)
from holocron.sources.bayut.extract import download_all as bayut_download_all

DEFAULT_LOOKBACK_DAYS = 3


def _default_end_date() -> str:
    return date.today().isoformat()


def _resolve_window(config: dict) -> tuple[str, str]:
    start_date = str(config.get("start_date") or "").strip()
    end_date = str(config.get("end_date") or "").strip() or _default_end_date()
    if start_date:
        return start_date, end_date

    lookback_days = int(config.get("lookback_days") or DEFAULT_LOOKBACK_DAYS)
    resolved_end = date.fromisoformat(end_date)
    resolved_start = resolved_end - timedelta(days=max(lookback_days, 0))
    return resolved_start.isoformat(), end_date


def extract(
    output_dir: Path,
    *,
    release_id: str,
    config: dict,
    http,
    context,
) -> list[Path]:
    start_date, end_date = _resolve_window(config)
    results = bayut_download_all(
        dest_dir=output_dir,
        run_id=release_id,
        start_date=start_date,
        end_date=end_date,
        max_pages=int(config["max_pages"]) if config.get("max_pages") else None,
        chrome_path=str(config.get("chrome_path") or ""),
    )
    return [result.local_path for result in results]


SOURCE = SourceSpec(
    name="bay_transactions",
    provider="bayut",
    source="bayut.com",
    mode=REFERENCE_REPLACE,
    schedule="0 8 * * *",
    description=(
        "Fetch Bayut transaction list data through a browser-backed Humbucker bootstrap and "
        "append sale and rent transaction rows to ClickHouse."
    ),
    config_schema={
        "release_id": release_id_field(""),
        "start_date": optional_str(
            "",
            description=(
                "Inclusive UTC start date for the Bayut transaction window (YYYY-MM-DD). "
                "If omitted, Bayut uses a rolling lookback window ending today."
            ),
        ),
        "end_date": optional_str(
            "",
            description=(
                "Inclusive UTC end date for the Bayut transaction window (YYYY-MM-DD). "
                "If omitted, Bayut uses today in UTC."
            ),
        ),
        "lookback_days": optional_int(
            DEFAULT_LOOKBACK_DAYS,
            description=(
                "Rolling overlap window for scheduled or ad hoc incremental runs when "
                "start_date is omitted."
            ),
        ),
        "max_pages": optional_int(
            None,
            description="Optional page cap per purpose for bounded tests or chunked backfills.",
        ),
        "chrome_path": optional_str(
            "",
            description=(
                "Optional path to a Chrome/Chromium executable for Bayut browser bootstrap. "
                "If omitted, Holocron resolves a common local browser binary."
            ),
        ),
    },
    default_config={
        "release_id": "",
        "start_date": "",
        "end_date": "",
        "lookback_days": DEFAULT_LOOKBACK_DAYS,
        "max_pages": None,
        "chrome_path": "",
    },
    tables=(
        TableSpec(
            "sales.csv",
            "bay_sale_transactions",
            load_strategy=APPEND,
            min_rows=0,
            unique_key=("transaction_hash_id",),
            non_empty_columns=("transaction_hash_id",),
        ),
        TableSpec(
            "rentals.csv",
            "bay_rental_transactions",
            load_strategy=APPEND,
            min_rows=0,
            unique_key=("transaction_hash_id",),
            non_empty_columns=("transaction_hash_id",),
        ),
    ),
    extract_fn=extract,
)
