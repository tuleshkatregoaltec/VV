"""Validation helpers for Holocron table assets."""

from __future__ import annotations


from dagster import AssetCheckResult

from holocron.framework.models import (
    APPEND,
    CheckOutcome,
    ReleaseManifest,
    SourceSpec,
    TableSpec,
    artifact_for_table,
)
from holocron.resources.clickhouse import ClickHouseResource


def check_names_for_table(source: SourceSpec, table_spec: TableSpec) -> list[str]:
    names = ["row_count_minimum"]
    if table_spec.load_strategy != APPEND:
        names.append("row_count_matches_manifest")
    if table_spec.unique_key:
        names.append("unique_key")
    names.extend(f"non_empty__{column}" for column in table_spec.non_empty_columns)
    names.extend(f"nonzero__{column}" for column in table_spec.nonzero_columns)
    names.extend(source.extra_check_names.get(table_spec.table_name, ()))
    return names


def _base_outcomes(
    clickhouse: ClickHouseResource,
    table_spec: TableSpec,
    expected_rows: int | None,
) -> list[CheckOutcome]:
    table = table_spec.table_name
    count = int(clickhouse.query_scalar(f"SELECT count() FROM {table}"))
    outcomes = [
        CheckOutcome(
            name="row_count_minimum",
            passed=count >= table_spec.min_rows,
            metadata={"row_count": count, "minimum_rows": table_spec.min_rows},
            description=f"{table} row count is above the configured minimum",
        )
    ]
    if table_spec.load_strategy != APPEND:
        outcomes.append(
            CheckOutcome(
                name="row_count_matches_manifest",
                passed=expected_rows is None or count == expected_rows,
                metadata={"row_count": count, "expected_rows": expected_rows or -1},
                description=f"{table} row count matches the extracted manifest",
            )
        )
    if table_spec.unique_key:
        group_cols = ", ".join(table_spec.unique_key)
        duplicate_count = int(
            clickhouse.query_scalar(
                f"SELECT count() FROM (SELECT {group_cols}, count() AS c FROM {table} "
                f"GROUP BY {group_cols} HAVING c > 1)"
            )
        )
        outcomes.append(
            CheckOutcome(
                name="unique_key",
                passed=duplicate_count == 0,
                metadata={"duplicate_key_groups": duplicate_count, "columns": group_cols},
                description=f"{table} has no duplicate key groups",
            )
        )

    for column in table_spec.non_empty_columns:
        empty_count = int(
            clickhouse.query_scalar(
                f"SELECT count() FROM {table} WHERE {column} = '' OR {column} IS NULL"
            )
        )
        outcomes.append(
            CheckOutcome(
                name=f"non_empty__{column}",
                passed=empty_count == 0,
                metadata={"empty_count": empty_count, "column": column},
                description=f"{table}.{column} contains no empty values",
            )
        )

    for column in table_spec.nonzero_columns:
        zero_count = int(clickhouse.query_scalar(f"SELECT count() FROM {table} WHERE {column} = 0"))
        outcomes.append(
            CheckOutcome(
                name=f"nonzero__{column}",
                passed=zero_count == 0,
                metadata={"zero_count": zero_count, "column": column},
                description=f"{table}.{column} contains no zero values",
            )
        )

    return outcomes


def run_checks_for_table(
    *,
    source: SourceSpec,
    table_spec: TableSpec,
    manifest: ReleaseManifest,
    clickhouse: ClickHouseResource,
    context,
) -> list[AssetCheckResult]:
    artifact = artifact_for_table(manifest, table_spec)
    outcomes = _base_outcomes(clickhouse, table_spec, artifact.row_count)
    if source.extra_checks_fn:
        outcomes.extend(source.extra_checks_fn(context, clickhouse, manifest, table_spec))
    return [
        AssetCheckResult(
            passed=outcome.passed,
            asset_key=table_spec.table_name,
            check_name=outcome.name,
            metadata=dict(outcome.metadata),
            description=outcome.description,
        )
        for outcome in outcomes
    ]
