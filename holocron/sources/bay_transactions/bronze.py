from __future__ import annotations

import json
import hashlib
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from holocron.platform.clickhouse import ClickHouseClient
from holocron.platform.raw_files import (
    download_manifest_file,
    manifest_files_by_name,
    read_jsonl_manifest_rows,
    string_value,
)
from holocron.platform.s3 import S3Client
from holocron.sources.bay_transactions.source import BAY_TRANSACTIONS_SOURCE_NAME

_TABLE_NAME = "bay_transactions_bronze"
_TABLE_COLUMNS = (
    "transaction_key",
    "purpose",
    "category",
    "locations_ids_json",
    "page",
    "scraped_at",
    "window_start_date",
    "window_end_date",
    "transaction_date",
    "amount_aed",
    "transaction_category",
    "property_type",
    "beds",
    "builtup_area_sqft",
    "plot_area_sqft",
    "occupancy_status",
    "location_id",
    "location_name",
    "full_location",
    "lat",
    "lng",
    "agent_id",
    "status",
    "contract_type",
    "duration_months",
    "monthly_amount_aed",
    "raw_json",
    "run_id",
)


def _string(value: Any) -> str:
    return string_value(value)


def _int(value: Any) -> int:
    parsed = _string(value)
    if not parsed:
        return 0
    try:
        return int(parsed)
    except ValueError:
        return int(float(parsed))


def _nullable_int(value: Any) -> int | None:
    parsed = _string(value)
    if not parsed:
        return None
    try:
        return int(parsed)
    except ValueError:
        return int(float(parsed))


def _float(value: Any) -> float:
    parsed = _string(value)
    if not parsed:
        return 0.0
    return float(parsed.replace(",", ""))


def _nullable_float(value: Any) -> float | None:
    parsed = _string(value)
    if not parsed:
        return None
    return float(parsed.replace(",", ""))


def _date(value: Any, *, field_name: str) -> date:
    parsed = _string(value)
    if not parsed:
        raise ValueError(f"Bayut transactions row is missing required date field: {field_name}")
    return date.fromisoformat(parsed)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parents[2] / "lib" / "sql" / "clickhouse_schema.sql"


def _iter_sql_statements(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def ensure_schema(*, clickhouse: ClickHouseClient) -> None:
    sql_path = _schema_sql_path()
    if not sql_path.exists():
        raise FileNotFoundError(f"Missing ClickHouse schema file: {sql_path}")
    for statement in _iter_sql_statements(sql_path.read_text(encoding="utf-8")):
        clickhouse.command(statement)


def _raw_json(raw_row: dict[str, Any]) -> str:
    return json.dumps(raw_row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _date_window_delete_predicate(table_rows: list[tuple]) -> str:
    windows = sorted({(row[6], row[7]) for row in table_rows})
    return " OR ".join(
        "("
        f"transaction_date >= toDate('{start_date.isoformat()}') "
        f"AND transaction_date <= toDate('{end_date.isoformat()}')"
        ")"
        for start_date, end_date in windows
    )


def _row_tuple(raw_row: dict[str, Any], *, fallback_run_id: str) -> tuple:
    raw = raw_row.get("raw")
    if not isinstance(raw, dict):
        raise ValueError("Bayut transactions raw row is missing raw transaction object")

    property_data = _dict(raw.get("property"))
    builtup_area = _dict(property_data.get("builtup_area"))
    plot_area = _dict(property_data.get("plot_area"))
    location = _dict(raw.get("location"))
    coordinates = _dict(location.get("coordinates"))
    contract = _dict(raw.get("contract"))
    transaction_date = _date(raw.get("date"), field_name="raw.date")
    locations_ids = raw_row.get("locations_ids")
    locations_ids_json = json.dumps(locations_ids if isinstance(locations_ids, list) else [])
    stable_key_parts = [
        _string(raw.get("date")),
        _string(raw.get("amount")),
        _string(location.get("id")),
        _string(location.get("full_location") or location.get("location")),
        _string(property_data.get("type")),
        _string(property_data.get("floor")),
        _string(property_data.get("beds")),
        _string(raw.get("agent_id")),
    ]
    transaction_key = hashlib.sha1(
        "|".join(stable_key_parts).encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()

    return (
        transaction_key,
        _string(raw_row.get("purpose")),
        _string(raw_row.get("category")),
        locations_ids_json,
        max(_int(raw_row.get("page")), 0),
        _string(raw_row.get("scraped_at")),
        _date(raw_row.get("start_date"), field_name="start_date"),
        _date(raw_row.get("end_date"), field_name="end_date"),
        transaction_date,
        _float(raw.get("amount")),
        _string(raw.get("category")),
        _string(property_data.get("type")),
        _nullable_int(property_data.get("beds")),
        _nullable_float(builtup_area.get("sqft")),
        _nullable_float(plot_area.get("sqft")),
        _string(property_data.get("occupancy_status")),
        _nullable_int(location.get("id")),
        _string(location.get("location")),
        _string(location.get("full_location")),
        _nullable_float(coordinates.get("latitude")),
        _nullable_float(coordinates.get("longitude")),
        _nullable_int(raw.get("agent_id")),
        _string(raw.get("status")),
        _string(contract.get("contract_type")),
        _nullable_int(contract.get("duration_months")),
        _nullable_float(contract.get("monthly_amount")),
        _raw_json(raw_row),
        fallback_run_id,
    )


def load_release_to_clickhouse(
    *,
    raw_release: dict[str, Any],
    s3: S3Client,
    clickhouse: ClickHouseClient,
) -> dict[str, Any]:
    source_name = _string(raw_release.get("source"))
    if source_name != BAY_TRANSACTIONS_SOURCE_NAME:
        raise ValueError(
            f"Expected raw_release.source={BAY_TRANSACTIONS_SOURCE_NAME}, got {source_name!r}"
        )

    run_id = _string(raw_release.get("run_id"))
    if not run_id:
        raise ValueError("raw_release.run_id is required")

    files_by_name = manifest_files_by_name(raw_release)
    jsonl_file_names = sorted(name for name in files_by_name if name.endswith(".jsonl"))
    if not jsonl_file_names:
        raise ValueError("Bayut transactions raw_release has no jsonl files")

    table_rows: list[tuple] = []
    with TemporaryDirectory(prefix=f"holocron-bay-transactions-bronze-{run_id}-") as scratch:
        scratch_path = Path(scratch)
        for file_name in jsonl_file_names:
            file_entry = files_by_name[file_name]
            local_path = download_manifest_file(
                file_name=file_name,
                file_entry=file_entry,
                s3=s3,
                scratch_path=scratch_path,
                source_label="Bayut transactions",
            )
            for raw_row in read_jsonl_manifest_rows(
                path=local_path,
                file_entry=file_entry,
                source_label="Bayut transactions",
            ):
                table_rows.append(_row_tuple(raw_row, fallback_run_id=run_id))

    ensure_schema(clickhouse=clickhouse)
    if table_rows:
        delete_predicate = _date_window_delete_predicate(table_rows)
        clickhouse.command(
            "ALTER TABLE bay_transactions_bronze "
            f"DELETE WHERE {delete_predicate} "
            "SETTINGS mutations_sync = 1"
        )
        clickhouse.insert_rows(
            table=_TABLE_NAME,
            rows=table_rows,
            column_names=_TABLE_COLUMNS,
        )

    table_row_counts = {_TABLE_NAME: len(table_rows)}
    return {
        "source": source_name,
        "run_id": run_id,
        "table_row_counts": table_row_counts,
        "table_count": len(table_row_counts),
        "total_rows": sum(table_row_counts.values()),
    }
