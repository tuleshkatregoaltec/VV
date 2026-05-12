from __future__ import annotations

import hashlib
from typing import Any

from holocron.contracts import (
    BronzeLoadResult,
    ClickHouseInserter,
    RawFileStore,
    RawManifest,
)
from holocron.platform.bronze import (
    bronze_load_result,
    coerce_int,
    load_jsonl_table_rows,
    replace_run_rows,
    stable_json,
    validate_raw_manifest,
)
from holocron.platform.clickhouse_schema import ensure_schema
from holocron.platform.raw_files import manifest_files_by_name, string_value
from holocron.sources.reelly_supply.source import REELLY_SUPPLY_SOURCE_NAME

_PROJECTS_TABLE = "reelly_projects_bronze"
_DOCUMENTS_TABLE = "reelly_documents_bronze"
_AVAILABILITY_TABLE = "reelly_matrix_availability_bronze"
_PROJECT_DETAILS_FILE = "reelly_supply_project_details.jsonl"
_DOCUMENTS_FILE = "reelly_supply_project_documents.jsonl"
_AVAILABILITY_FILE = "reelly_supply_matrix_availability.jsonl"
_PROJECT_COLUMNS = (
    "project_key",
    "run_id",
    "scraped_at",
    "project_id",
    "delta_reason",
    "list_item_json",
    "raw_json",
)
_DOCUMENT_COLUMNS = (
    "document_key",
    "run_id",
    "scraped_at",
    "project_id",
    "source_endpoint",
    "field_path",
    "name",
    "url",
    "normalized_url",
    "status",
    "error",
    "downloaded_path",
    "final_url",
    "content_type",
    "sha256",
    "size_bytes",
    "raw_json",
)
_AVAILABILITY_COLUMNS = (
    "availability_key",
    "run_id",
    "scraped_at",
    "project_id",
    "endpoint",
    "candidate",
    "status",
    "error",
    "raw_json",
)


def load_release_to_clickhouse(
    *,
    raw_manifest: RawManifest,
    s3: RawFileStore,
    clickhouse: ClickHouseInserter,
) -> BronzeLoadResult:
    source_name, run_id = validate_raw_manifest(
        raw_manifest,
        expected_source=REELLY_SUPPLY_SOURCE_NAME,
    )
    files_by_name = manifest_files_by_name(raw_manifest)
    project_rows = load_jsonl_table_rows(
        files_by_name=files_by_name,
        file_name=_PROJECT_DETAILS_FILE,
        s3=s3,
        run_id=run_id,
        source_label="Reelly project details",
        row_builder=_project_row_tuple,
        scratch_prefix="holocron-reelly-bronze",
    )
    document_rows = load_jsonl_table_rows(
        files_by_name=files_by_name,
        file_name=_DOCUMENTS_FILE,
        s3=s3,
        run_id=run_id,
        source_label="Reelly project documents",
        row_builder=_document_row_tuple,
        scratch_prefix="holocron-reelly-bronze",
    )
    availability_rows = load_jsonl_table_rows(
        files_by_name=files_by_name,
        file_name=_AVAILABILITY_FILE,
        s3=s3,
        run_id=run_id,
        source_label="Reelly matrix availability",
        row_builder=_availability_row_tuple,
        scratch_prefix="holocron-reelly-bronze",
    )

    ensure_schema(clickhouse=clickhouse)
    table_row_counts = {
        _PROJECTS_TABLE: len(project_rows),
        _DOCUMENTS_TABLE: len(document_rows),
        _AVAILABILITY_TABLE: len(availability_rows),
    }
    replace_run_rows(
        clickhouse=clickhouse,
        table=_PROJECTS_TABLE,
        run_id=run_id,
        rows=project_rows,
        column_names=_PROJECT_COLUMNS,
    )
    replace_run_rows(
        clickhouse=clickhouse,
        table=_DOCUMENTS_TABLE,
        run_id=run_id,
        rows=document_rows,
        column_names=_DOCUMENT_COLUMNS,
    )
    replace_run_rows(
        clickhouse=clickhouse,
        table=_AVAILABILITY_TABLE,
        run_id=run_id,
        rows=availability_rows,
        column_names=_AVAILABILITY_COLUMNS,
    )
    return bronze_load_result(source=source_name, run_id=run_id, table_row_counts=table_row_counts)


def _project_row_tuple(raw_row: dict[str, Any], *, fallback_run_id: str) -> tuple:
    raw_json = _json(raw_row.get("raw"))
    project_id = string_value(raw_row.get("project_id"))
    project_key = _hash_key(project_id, raw_json)
    return (
        project_key,
        string_value(raw_row.get("_run_id")) or fallback_run_id,
        string_value(raw_row.get("scraped_at")),
        project_id,
        string_value(raw_row.get("delta_reason")),
        _json(raw_row.get("list_item")),
        raw_json,
    )


def _document_row_tuple(raw_row: dict[str, Any], *, fallback_run_id: str) -> tuple:
    raw_json = _json(raw_row.get("raw"))
    project_id = string_value(raw_row.get("project_id"))
    document_key = _hash_key(
        project_id,
        string_value(raw_row.get("normalized_url")) or string_value(raw_row.get("url")),
        string_value(raw_row.get("field_path")),
        raw_json,
    )
    return (
        document_key,
        string_value(raw_row.get("_run_id")) or fallback_run_id,
        string_value(raw_row.get("scraped_at")),
        project_id,
        string_value(raw_row.get("endpoint")),
        string_value(raw_row.get("field_path")),
        string_value(raw_row.get("name")),
        string_value(raw_row.get("url")),
        string_value(raw_row.get("normalized_url")),
        string_value(raw_row.get("status")),
        string_value(raw_row.get("error")),
        string_value(raw_row.get("downloaded_path")),
        string_value(raw_row.get("final_url")),
        string_value(raw_row.get("content_type")),
        string_value(raw_row.get("sha256")),
        max(coerce_int(raw_row.get("size_bytes")), 0),
        raw_json,
    )


def _availability_row_tuple(raw_row: dict[str, Any], *, fallback_run_id: str) -> tuple:
    raw_json = _json(raw_row.get("raw"))
    project_id = string_value(raw_row.get("project_id"))
    endpoint = string_value(raw_row.get("endpoint"))
    candidate = string_value(raw_row.get("candidate"))
    return (
        _hash_key(project_id, endpoint, candidate, raw_json),
        string_value(raw_row.get("_run_id")) or fallback_run_id,
        string_value(raw_row.get("scraped_at")),
        project_id,
        endpoint,
        candidate,
        string_value(raw_row.get("status")),
        string_value(raw_row.get("error")),
        raw_json,
    )


def _json(value: Any) -> str:
    return stable_json(value)


def _hash_key(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()
