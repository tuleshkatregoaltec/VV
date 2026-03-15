"""Validation helpers shared by dataset validation assets."""

from __future__ import annotations

from dagster import AssetExecutionContext

from etl.core.dataset_registry import APPEND, DatasetSpec, TableSpec, table_by_filename
from etl.core.releases import ReleaseManifest
from etl.resources.clickhouse import ClickHouseResource


def _expected_rows_from_manifest(manifest: ReleaseManifest, filename: str) -> int | None:
    for file in manifest.files:
        if file.name == filename:
            return file.row_count
    return None


def validate_table_release(
    *,
    context: AssetExecutionContext,
    clickhouse: ClickHouseResource,
    table_spec: TableSpec,
    expected_rows: int | None,
) -> dict[str, int]:
    table = table_spec.table_name
    count = int(clickhouse.query_scalar(f"SELECT count() FROM {table}"))
    if count < table_spec.min_rows:
        raise ValueError(f"{table} has {count} rows, below minimum {table_spec.min_rows}")
    if expected_rows is not None and table_spec.load_strategy != APPEND and count != expected_rows:
        raise ValueError(
            f"{table} row count {count} does not match manifest row count {expected_rows}"
        )

    for column in table_spec.non_empty_columns:
        empty_count = int(
            clickhouse.query_scalar(
                f"SELECT count() FROM {table} WHERE {column} = '' OR {column} IS NULL"
            )
        )
        if empty_count:
            raise ValueError(f"{table}.{column} has {empty_count} empty values")

    for column in table_spec.nonzero_columns:
        zero_count = int(clickhouse.query_scalar(f"SELECT count() FROM {table} WHERE {column} = 0"))
        if zero_count:
            raise ValueError(f"{table}.{column} has {zero_count} zero values")

    duplicate_count = 0
    if table_spec.unique_key:
        group_cols = ", ".join(table_spec.unique_key)
        duplicate_count = int(
            clickhouse.query_scalar(
                f"SELECT count() FROM (SELECT {group_cols}, count() AS c FROM {table} "
                f"GROUP BY {group_cols} HAVING c > 1)"
            )
        )
        if duplicate_count:
            raise ValueError(
                f"{table} has {duplicate_count} duplicate key groups on ({group_cols})"
            )

    context.log.info(f"{table}: {count:,} rows validated")
    return {
        "row_count": count,
        "expected_rows": expected_rows or -1,
        "duplicate_key_groups": duplicate_count,
    }


def validate_dataset_release(
    *,
    context: AssetExecutionContext,
    clickhouse: ClickHouseResource,
    dataset_spec: DatasetSpec,
    manifest: ReleaseManifest,
) -> dict[str, dict[str, int]]:
    files_by_name = table_by_filename(dataset_spec.dataset)
    results: dict[str, dict[str, int]] = {}
    for artifact in manifest.files:
        table_spec = files_by_name.get(artifact.name)
        if table_spec is None:
            continue
        results[table_spec.table_name] = validate_table_release(
            context=context,
            clickhouse=clickhouse,
            table_spec=table_spec,
            expected_rows=_expected_rows_from_manifest(manifest, artifact.name),
        )
    return results
