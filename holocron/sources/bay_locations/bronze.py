from __future__ import annotations

import json
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
from holocron.sources.bay_locations.source import BAY_LOCATIONS_SOURCE_NAME

_TABLE_NAME = "bay_locations_bronze"
_TABLE_COLUMNS = (
    "location_id",
    "name",
    "level",
    "completion_status",
    "query",
    "page",
    "scraped_at",
    "extract_date",
    "country_id",
    "country_name",
    "city_id",
    "city_name",
    "community_id",
    "community_name",
    "sub_community_id",
    "sub_community_name",
    "cluster_id",
    "cluster_name",
    "lat",
    "lng",
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


def _nullable_float(value: Any) -> float | None:
    parsed = _string(value)
    if not parsed:
        return None
    return float(parsed.replace(",", ""))


def _date(value: Any, *, field_name: str) -> date:
    parsed = _string(value)
    if not parsed:
        raise ValueError(f"Bayut locations row is missing required date field: {field_name}")
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


def _row_tuple(raw_row: dict[str, Any], *, fallback_run_id: str, extract_date: date) -> tuple:
    raw = raw_row.get("raw")
    if not isinstance(raw, dict):
        raise ValueError("Bayut locations raw row is missing raw location object")

    full = _dict(raw.get("full"))
    country = _dict(full.get("country"))
    city = _dict(full.get("city"))
    community = _dict(full.get("community"))
    sub_community = _dict(full.get("sub_community"))
    cluster = _dict(full.get("cluster"))
    coordinates = _dict(raw.get("coordinates"))
    return (
        _int(raw.get("id")),
        _string(raw.get("name")),
        _string(raw.get("level")),
        _string(raw.get("completion_status")),
        _string(raw_row.get("query")),
        max(_int(raw_row.get("page")), 0),
        _string(raw_row.get("scraped_at")),
        extract_date,
        _nullable_int(country.get("id")),
        _string(country.get("name")),
        _nullable_int(city.get("id")),
        _string(city.get("name")),
        _nullable_int(community.get("id")),
        _string(community.get("name")),
        _nullable_int(sub_community.get("id")),
        _string(sub_community.get("name")),
        _nullable_int(cluster.get("id")),
        _string(cluster.get("name")),
        _nullable_float(coordinates.get("lat")),
        _nullable_float(coordinates.get("lng")),
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
    if source_name != BAY_LOCATIONS_SOURCE_NAME:
        raise ValueError(
            f"Expected raw_release.source={BAY_LOCATIONS_SOURCE_NAME}, got {source_name!r}"
        )

    run_id = _string(raw_release.get("run_id"))
    if not run_id:
        raise ValueError("raw_release.run_id is required")
    extract_date = _date(raw_release.get("extract_date"), field_name="extract_date")

    files_by_name = manifest_files_by_name(raw_release)
    jsonl_file_names = sorted(name for name in files_by_name if name.endswith(".jsonl"))
    if not jsonl_file_names:
        raise ValueError("Bayut locations raw_release has no jsonl files")

    table_rows: list[tuple] = []
    with TemporaryDirectory(prefix=f"holocron-bay-locations-bronze-{run_id}-") as scratch:
        scratch_path = Path(scratch)
        for file_name in jsonl_file_names:
            file_entry = files_by_name[file_name]
            local_path = download_manifest_file(
                file_name=file_name,
                file_entry=file_entry,
                s3=s3,
                scratch_path=scratch_path,
                source_label="Bayut locations",
            )
            for raw_row in read_jsonl_manifest_rows(
                path=local_path,
                file_entry=file_entry,
                source_label="Bayut locations",
            ):
                table_rows.append(
                    _row_tuple(raw_row, fallback_run_id=run_id, extract_date=extract_date)
                )

    if not table_rows:
        raise ValueError("Bayut locations parsed zero rows; refusing to replace bronze table")

    ensure_schema(clickhouse=clickhouse)
    clickhouse.replace_table_rows(
        table=_TABLE_NAME,
        rows=table_rows,
        column_names=_TABLE_COLUMNS,
        staging_suffix=run_id,
    )

    table_row_counts = {_TABLE_NAME: len(table_rows)}
    return {
        "source": source_name,
        "run_id": run_id,
        "table_row_counts": table_row_counts,
        "table_count": len(table_row_counts),
        "total_rows": sum(table_row_counts.values()),
    }
