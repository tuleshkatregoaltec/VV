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
from holocron.sources.bay_listings.source import BAY_LISTINGS_SOURCE_NAME

_TABLE_NAME = "bay_listings_bronze"
_TABLE_COLUMNS = (
    "listing_key",
    "listing_id",
    "purpose",
    "category",
    "location_id",
    "page",
    "scraped_at",
    "extract_date",
    "title",
    "reference_number",
    "property_type_main",
    "property_type_sub",
    "price_aed",
    "area_built_up_sqft",
    "area_plot_sqft",
    "bedrooms",
    "bathrooms",
    "completion_status",
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
    "agency_id",
    "agency_name",
    "agent_id",
    "agent_name",
    "permit_number",
    "dld_property_sk",
    "project_id",
    "project_title",
    "created_at",
    "updated_at",
    "url",
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
        raise ValueError(f"Bayut listings row is missing required date field: {field_name}")
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


def _entity(raw: dict[str, Any], *path: str) -> dict[str, Any]:
    current: Any = raw
    for key in path:
        current = _dict(current).get(key)
    return _dict(current)


def _row_tuple(raw_row: dict[str, Any], *, fallback_run_id: str, extract_date: date) -> tuple:
    raw = raw_row.get("raw")
    if not isinstance(raw, dict):
        raise ValueError("Bayut listings raw row is missing raw listing object")

    listing_id = _nullable_int(raw.get("id"))
    listing_key = (
        _string(listing_id)
        or hashlib.sha1(
            _raw_json(raw_row).encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()
    )
    area = _dict(raw.get("area"))
    details = _dict(raw.get("details"))
    location = _dict(raw.get("location"))
    coordinates = _dict(location.get("coordinates"))
    city = _entity(raw, "location", "city")
    community = _entity(raw, "location", "community")
    sub_community = _entity(raw, "location", "sub_community")
    cluster = _entity(raw, "location", "cluster")
    agency = _dict(raw.get("agency"))
    agent = _dict(raw.get("agent"))
    legal = _dict(raw.get("legal"))
    project = _dict(raw.get("project"))
    listing_type = _dict(raw.get("type"))
    meta = _dict(raw.get("meta"))

    return (
        listing_key,
        listing_id,
        _string(raw_row.get("purpose") or raw.get("purpose")),
        _string(raw_row.get("category")),
        _int(raw_row.get("location_id")),
        max(_int(raw_row.get("page")), 0),
        _string(raw_row.get("scraped_at")),
        extract_date,
        _string(raw.get("title")),
        _string(raw.get("reference_number")),
        _string(listing_type.get("main")),
        _string(listing_type.get("sub")),
        _float(raw.get("price")),
        _float(area.get("built_up")),
        _nullable_float(area.get("plot")),
        _nullable_int(details.get("bedrooms")),
        _nullable_int(details.get("bathrooms")),
        _string(details.get("completion_status") or project.get("completion_status")),
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
        _nullable_int(agency.get("id")),
        _string(agency.get("name")),
        _nullable_int(agent.get("id")),
        _string(agent.get("name")),
        _string(legal.get("permit_number")),
        _string(legal.get("dld_property_sk")),
        _nullable_int(project.get("id")),
        _string(project.get("title") or project.get("name")),
        _string(meta.get("created_at")),
        _string(meta.get("updated_at")),
        _string(meta.get("url")),
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
    if source_name != BAY_LISTINGS_SOURCE_NAME:
        raise ValueError(
            f"Expected raw_release.source={BAY_LISTINGS_SOURCE_NAME}, got {source_name!r}"
        )

    run_id = _string(raw_release.get("run_id"))
    if not run_id:
        raise ValueError("raw_release.run_id is required")
    extract_date = _date(raw_release.get("extract_date"), field_name="extract_date")

    files_by_name = manifest_files_by_name(raw_release)
    jsonl_file_names = sorted(name for name in files_by_name if name.endswith(".jsonl"))
    if not jsonl_file_names:
        raise ValueError("Bayut listings raw_release has no jsonl files")

    table_rows: list[tuple] = []
    with TemporaryDirectory(prefix=f"holocron-bay-listings-bronze-{run_id}-") as scratch:
        scratch_path = Path(scratch)
        for file_name in jsonl_file_names:
            file_entry = files_by_name[file_name]
            local_path = download_manifest_file(
                file_name=file_name,
                file_entry=file_entry,
                s3=s3,
                scratch_path=scratch_path,
                source_label="Bayut listings",
            )
            for raw_row in read_jsonl_manifest_rows(
                path=local_path,
                file_entry=file_entry,
                source_label="Bayut listings",
            ):
                table_rows.append(
                    _row_tuple(raw_row, fallback_run_id=run_id, extract_date=extract_date)
                )

    ensure_schema(clickhouse=clickhouse)
    if table_rows:
        clickhouse.command(
            "ALTER TABLE bay_listings_bronze "
            f"DELETE WHERE extract_date = toDate('{extract_date.isoformat()}') "
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
