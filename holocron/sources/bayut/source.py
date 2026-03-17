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


def _default_start_date() -> str:
    return (date.today() - timedelta(days=30)).isoformat()


def _default_end_date() -> str:
    return date.today().isoformat()


def extract(
    output_dir: Path,
    *,
    release_id: str,
    config: dict,
    http,
    context,
) -> list[Path]:
    results = bayut_download_all(
        dest_dir=output_dir,
        run_id=release_id,
        start_date=str(config.get("start_date") or _default_start_date()),
        end_date=str(config.get("end_date") or _default_end_date()),
        max_pages=int(config["max_pages"]) if config.get("max_pages") else None,
        chrome_path=str(config.get("chrome_path") or ""),
    )
    return [result.local_path for result in results]


SOURCE = SourceSpec(
    name="bayut",
    source="bayut.com",
    mode=REFERENCE_REPLACE,
    description=(
        "Fetch Bayut transaction list data through a browser-backed Humbucker bootstrap and "
        "append sale and rent transaction rows to ClickHouse."
    ),
    config_schema={
        "release_id": release_id_field(""),
        "start_date": optional_str(
            _default_start_date(),
            description="Inclusive UTC start date for the Bayut transaction window (YYYY-MM-DD).",
        ),
        "end_date": optional_str(
            _default_end_date(),
            description="Inclusive UTC end date for the Bayut transaction window (YYYY-MM-DD).",
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
        "start_date": _default_start_date(),
        "end_date": _default_end_date(),
        "max_pages": None,
        "chrome_path": "",
    },
    tables=(
        TableSpec(
            "sales.csv",
            "bayut_sale_transactions",
            load_strategy=APPEND,
            min_rows=0,
            non_empty_columns=("transaction_hash_id",),
        ),
        TableSpec(
            "rentals.csv",
            "bayut_rental_transactions",
            load_strategy=APPEND,
            min_rows=0,
            non_empty_columns=("transaction_hash_id",),
        ),
    ),
    extract_fn=extract,
)
