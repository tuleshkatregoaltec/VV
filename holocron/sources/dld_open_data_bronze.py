from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from holocron.contracts import (
    BronzeLoadResult,
    BronzeLoader,
    ClickHouseInserter,
    RawFileStore,
    RawManifest,
)
from holocron.platform.bronze import (
    bronze_load_result,
    coerce_int,
    iso_date_or_none,
    load_jsonl_table_rows,
    replace_run_rows,
    stable_json,
    validate_raw_manifest,
)
from holocron.platform.clickhouse_schema import ensure_schema
from holocron.platform.raw_files import manifest_files_by_name, string_value

_KEY_SEPARATOR = "|"


def dld_row_key(raw_row: dict[str, Any]) -> str:
    raw_payload = raw_row.get("raw")
    return hashlib.sha1(
        _KEY_SEPARATOR.join(
            [
                string_value(raw_row.get("category")),
                string_value(raw_row.get("endpoint")),
                string_value(raw_row.get("row_index")),
                stable_json(raw_payload),
            ]
        ).encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()


def dld_envelope_tuple(
    raw_row: dict[str, Any],
    *,
    row_key: str,
    fallback_run_id: str,
) -> tuple:
    window_meta = raw_row.get("date_window") or {}
    return (
        row_key,
        fallback_run_id,
        string_value(raw_row.get("scraped_at")),
        string_value(raw_row.get("mode")),
        iso_date_or_none(window_meta.get("start_date")),
        iso_date_or_none(window_meta.get("end_date")),
        max(coerce_int(raw_row.get("page_index")), 0),
        max(coerce_int(raw_row.get("row_index")), 0),
    )


def build_open_data_bronze_loader(
    *,
    source_name: str,
    column_names: tuple[str, ...],
    row_builder: Callable[..., tuple[Any, ...]],
) -> BronzeLoader:
    def load_release_to_clickhouse(
        *, raw_manifest: RawManifest, s3: RawFileStore, clickhouse: ClickHouseInserter
    ) -> BronzeLoadResult:
        return load_open_data_release_to_clickhouse(
            raw_manifest=raw_manifest,
            s3=s3,
            clickhouse=clickhouse,
            source_name=source_name,
            table_name=f"{source_name}_bronze",
            row_file_name=f"{source_name}_rows.jsonl",
            column_names=column_names,
            row_builder=row_builder,
        )

    return load_release_to_clickhouse


def load_open_data_release_to_clickhouse(
    *,
    raw_manifest: RawManifest,
    s3: RawFileStore,
    clickhouse: ClickHouseInserter,
    source_name: str,
    table_name: str,
    row_file_name: str,
    column_names: tuple[str, ...],
    row_builder: Callable[..., tuple[Any, ...]],
) -> BronzeLoadResult:
    actual_source, run_id = validate_raw_manifest(raw_manifest, expected_source=source_name)
    files_by_name = manifest_files_by_name(raw_manifest)
    table_rows = load_jsonl_table_rows(
        files_by_name=files_by_name,
        file_name=row_file_name,
        s3=s3,
        run_id=run_id,
        source_label=source_name,
        row_builder=row_builder,
        required=True,
        scratch_prefix=f"holocron-{source_name}-bronze",
    )

    ensure_schema(clickhouse=clickhouse)
    replace_run_rows(
        clickhouse=clickhouse,
        table=table_name,
        run_id=run_id,
        rows=table_rows,
        column_names=column_names,
    )

    return bronze_load_result(
        source=actual_source,
        run_id=run_id,
        table_row_counts={table_name: len(table_rows)},
    )
