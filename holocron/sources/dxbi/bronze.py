from __future__ import annotations

import hashlib
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
from holocron.sources.dxbi.source import DXBI_SOURCE_NAME

_TABLE_NAME = "dxbi_transactions_bronze"
_TABLE_COLUMNS = (
    "transaction_key",
    "source_table",
    "cells_json",
    "cells_count",
    "run_id",
    "scraped_at",
    "slice_start_date",
    "slice_end_date",
    "source_url",
    "page_number",
    "row_number",
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


def _date(value: Any, *, field_name: str) -> date:
    parsed = _string(value)
    if not parsed:
        raise ValueError(f"DXBI row is missing required date field: {field_name}")
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


def _row_tuple(raw_row: dict[str, Any], *, fallback_run_id: str) -> tuple:
    source_table = _string(raw_row.get("table"))
    if not source_table:
        raise ValueError("DXBI raw row is missing table")

    raw_cells = raw_row.get("cells")
    if not isinstance(raw_cells, list):
        raise ValueError("DXBI raw row cells must be a list")
    cells = [_string(value) for value in raw_cells]
    cells_json = json.dumps(cells, ensure_ascii=False)
    source_url = _string(raw_row.get("_source_url"))

    transaction_key = hashlib.sha1(
        f"{source_table}|{source_url}|{cells_json}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()

    run_id = _string(raw_row.get("_run_id")) or fallback_run_id
    return (
        transaction_key,
        source_table,
        cells_json,
        min(len(cells), 65535),
        run_id,
        _string(raw_row.get("_scraped_at")),
        _date(raw_row.get("_slice_start_date"), field_name="_slice_start_date"),
        _date(raw_row.get("_slice_end_date"), field_name="_slice_end_date"),
        source_url,
        max(_int(raw_row.get("_page_number")), 0),
        max(_int(raw_row.get("_row_number")), 0),
    )


def _slice_delete_predicate(table_rows: list[tuple]) -> str:
    slices = sorted({(row[6], row[7]) for row in table_rows})
    return " OR ".join(
        "("
        f"slice_start_date = toDate('{start_date.isoformat()}') "
        f"AND slice_end_date = toDate('{end_date.isoformat()}')"
        ")"
        for start_date, end_date in slices
    )


def load_release_to_clickhouse(
    *,
    raw_release: dict[str, Any],
    s3: S3Client,
    clickhouse: ClickHouseClient,
) -> dict[str, Any]:
    source_name = _string(raw_release.get("source"))
    if source_name != DXBI_SOURCE_NAME:
        raise ValueError(f"Expected raw_release.source={DXBI_SOURCE_NAME}, got {source_name!r}")

    run_id = _string(raw_release.get("run_id"))
    if not run_id:
        raise ValueError("raw_release.run_id is required")

    files_by_name = manifest_files_by_name(raw_release)
    jsonl_file_names = sorted(name for name in files_by_name if name.endswith(".jsonl"))
    if not jsonl_file_names:
        raise ValueError("DXBI raw_release has no jsonl files")

    table_rows: list[tuple] = []
    with TemporaryDirectory(prefix=f"holocron-dxbi-bronze-{run_id}-") as scratch:
        scratch_path = Path(scratch)
        for file_name in jsonl_file_names:
            file_entry = files_by_name[file_name]
            local_path = download_manifest_file(
                file_name=file_name,
                file_entry=file_entry,
                s3=s3,
                scratch_path=scratch_path,
                source_label="DXBI",
            )
            for raw_row in read_jsonl_manifest_rows(
                path=local_path,
                file_entry=file_entry,
                source_label="DXBI",
            ):
                table_rows.append(_row_tuple(raw_row, fallback_run_id=run_id))

    ensure_schema(clickhouse=clickhouse)
    if table_rows:
        delete_predicate = _slice_delete_predicate(table_rows)
        clickhouse.command(
            "ALTER TABLE dxbi_transactions_bronze "
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
