"""Dispatch table loads based on dataset/table semantics."""

from __future__ import annotations

from etl.core.dataset_registry import APPEND, FULL_SWAP, TableSpec
from etl.resources.clickhouse import ClickHouseResource
from etl.resources.s3 import S3Resource


def load_table_from_release(
    *,
    clickhouse: ClickHouseResource,
    s3: S3Resource,
    table_spec: TableSpec,
    s3_key: str,
    release_id: str,
) -> int:
    s3_url = s3.s3_url(s3_key)
    kwargs = {
        "table": table_spec.table_name,
        "s3_url": s3_url,
        "aws_access_key_id": s3.aws_access_key_id,
        "aws_secret_access_key": s3.aws_secret_access_key,
        "format": table_spec.file_format,
        "staging_suffix": release_id,
    }
    if table_spec.load_strategy == FULL_SWAP:
        return clickhouse.load_table_from_s3(**kwargs)
    if table_spec.load_strategy == APPEND:
        return clickhouse.append_table_from_s3(**kwargs)
    raise ValueError(
        f"Unsupported load strategy {table_spec.load_strategy!r} for {table_spec.table_name}"
    )
