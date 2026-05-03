from __future__ import annotations

import hashlib
import json
import re
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
from holocron.sources.dld.source import DLD_SOURCE_NAME

_TABLE_NAME = "dld_transactions_bronze"
_DETAIL_FILE_RE = re.compile(
    r"^dld_transactions_(?P<kind>[a-z]+)_(?P<day>\d{4}-\d{2}-\d{2})\.jsonl$"
)
_TABLE_COLUMNS = (
    "transaction_key",
    "transaction_kind",
    "transaction_date",
    "data_mode",
    "property_type_id",
    "property_type_name_en",
    "property_type_name_ar",
    "community_id",
    "community_name_en",
    "community_name_ar",
    "project_id",
    "project_name_en",
    "project_name_ar",
    "building_id",
    "building_name_en",
    "building_name_ar",
    "usage_id",
    "usage_name_en",
    "usage_name_ar",
    "property_status_id",
    "property_status_name_en",
    "property_status_name_ar",
    "property_sub_type_id",
    "property_sub_type_name_en",
    "property_sub_type_name_ar",
    "sale_type_id",
    "sale_type_name_en",
    "sale_type_name_ar",
    "value_aed",
    "area_sqm",
    "per_sqm_aed",
    "transaction_count",
    "raw_json",
    "run_id",
)


def _string(value: Any) -> str:
    return string_value(value)


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


def _date(value: Any, *, field_name: str) -> date:
    parsed = _string(value)
    if not parsed:
        raise ValueError(f"DLD row is missing required date field: {field_name}")
    return date.fromisoformat(parsed)


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


def _transaction_file_names(files_by_name: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(
        name
        for name in files_by_name
        if name.startswith("dld_transactions_") and name.endswith(".jsonl")
    )


def _file_key(file_name: str) -> tuple[str, date]:
    match = _DETAIL_FILE_RE.match(file_name)
    if match is None:
        raise ValueError(f"Unexpected DLD transaction file name: {file_name}")
    return match.group("kind"), date.fromisoformat(match.group("day"))


def _name_en(entity: Any) -> str:
    if not isinstance(entity, dict):
        return ""
    name = entity.get("name")
    if isinstance(name, dict):
        return _string(name.get("englishName"))
    return ""


def _name_ar(entity: Any) -> str:
    if not isinstance(entity, dict):
        return ""
    name = entity.get("name")
    if isinstance(name, dict):
        return _string(name.get("arabicName"))
    return ""


def _entity_id(entity: Any) -> int | None:
    if not isinstance(entity, dict):
        return None
    return _nullable_int(entity.get("id"))


def _project(raw: dict[str, Any]) -> dict[str, Any] | None:
    projects = raw.get("projects")
    if not isinstance(projects, list) or not projects:
        return None
    first_project = projects[0]
    if not isinstance(first_project, dict):
        return None
    project = first_project.get("project")
    return project if isinstance(project, dict) else None


def _raw_json(raw_row: dict[str, Any]) -> str:
    return json.dumps(raw_row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row_tuple(raw_row: dict[str, Any], *, fallback_run_id: str) -> tuple:
    raw = raw_row.get("raw")
    if not isinstance(raw, dict):
        raise ValueError("DLD raw row is missing raw transaction object")

    kind = _string(raw_row.get("transaction_kind"))
    if not kind:
        raise ValueError("DLD raw row is missing transaction_kind")
    transaction_date = _date(raw_row.get("transaction_date"), field_name="transaction_date")
    data_mode = _string(raw_row.get("data_mode"))
    property_type = raw_row.get("property_type")
    if not isinstance(property_type, dict):
        property_type = {}

    community = raw.get("community")
    project = _project(raw)
    building = raw.get("building")
    usage = raw.get("usage")
    property_status = raw.get("propertyStatus")
    property_sub_type = raw.get("propertySubType")
    sale_type = raw.get("saleType")
    row_json = _raw_json(raw_row)

    transaction_key = hashlib.sha1(
        f"{kind}|{transaction_date.isoformat()}|{row_json}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()

    return (
        transaction_key,
        kind,
        transaction_date,
        data_mode,
        _nullable_int(property_type.get("id")),
        _name_en({"name": property_type.get("name")}),
        _name_ar({"name": property_type.get("name")}),
        _string(community.get("id") if isinstance(community, dict) else ""),
        _name_en(community),
        _name_ar(community),
        _entity_id(project),
        _name_en(project),
        _name_ar(project),
        _entity_id(building),
        _name_en(building),
        _name_ar(building),
        _entity_id(usage),
        _name_en(usage),
        _name_ar(usage),
        _entity_id(property_status),
        _name_en(property_status),
        _name_ar(property_status),
        _entity_id(property_sub_type),
        _name_en(property_sub_type),
        _name_ar(property_sub_type),
        _entity_id(sale_type),
        _name_en(sale_type),
        _name_ar(sale_type),
        _float(raw.get("value")),
        _float(raw.get("size")),
        _float(raw.get("per_Sqm")),
        max(_nullable_int(raw.get("totalTrx")) or 0, 0),
        row_json,
        _string(raw_row.get("_run_id")) or fallback_run_id,
    )


def _delete_condition(keys: set[tuple[str, date]]) -> str:
    return " OR ".join(
        f"(transaction_kind = '{kind}' AND transaction_date = toDate('{day.isoformat()}'))"
        for kind, day in sorted(keys)
    )


def load_release_to_clickhouse(
    *,
    raw_release: dict[str, Any],
    s3: S3Client,
    clickhouse: ClickHouseClient,
) -> dict[str, Any]:
    source_name = _string(raw_release.get("source"))
    if source_name != DLD_SOURCE_NAME:
        raise ValueError(f"Expected raw_release.source={DLD_SOURCE_NAME}, got {source_name!r}")

    run_id = _string(raw_release.get("run_id"))
    if not run_id:
        raise ValueError("raw_release.run_id is required")

    files_by_name = manifest_files_by_name(raw_release)
    jsonl_file_names = _transaction_file_names(files_by_name)
    if not jsonl_file_names:
        raise ValueError("DLD raw_release has no transaction jsonl files")

    table_rows: list[tuple] = []
    touched_keys: set[tuple[str, date]] = set()
    manifest_detail_rows = 0
    downloaded_detail_rows = 0

    with TemporaryDirectory(prefix=f"holocron-dld-bronze-{run_id}-") as scratch:
        scratch_path = Path(scratch)
        for file_name in jsonl_file_names:
            file_entry = files_by_name[file_name]
            local_path = download_manifest_file(
                file_name=file_name,
                file_entry=file_entry,
                s3=s3,
                scratch_path=scratch_path,
                source_label="DLD",
            )
            raw_rows = read_jsonl_manifest_rows(
                path=local_path,
                file_entry=file_entry,
                source_label="DLD",
            )
            manifest_detail_rows += int(file_entry.get("row_count") or 0)
            downloaded_detail_rows += len(raw_rows)
            touched_keys.add(_file_key(file_name))

            for raw_row in raw_rows:
                row = _row_tuple(raw_row, fallback_run_id=run_id)
                table_rows.append(row)

    if manifest_detail_rows != downloaded_detail_rows:
        raise ValueError(
            "DLD detail row reconciliation failed: "
            f"manifest={manifest_detail_rows} downloaded={downloaded_detail_rows}"
        )

    ensure_schema(clickhouse=clickhouse)
    if table_rows:
        clickhouse.command(
            "ALTER TABLE dld_transactions_bronze DELETE WHERE "
            f"{_delete_condition(touched_keys)} SETTINGS mutations_sync = 1"
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
        "reconciliation": {
            "manifest_detail_rows": manifest_detail_rows,
            "downloaded_detail_rows": downloaded_detail_rows,
        },
    }
