"""Generic extract and publish helpers for Holocron."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dagster import AssetExecutionContext

from holocron.framework.models import (
    APPEND,
    FULL_SWAP,
    FileArtifact,
    LocalReleaseManifest,
    ReleaseManifest,
    SourceSpec,
    TableSpec,
    artifact_for_table,
    build_local_file_artifact,
    new_release_id,
    utc_now_iso,
)
from holocron.framework.storage import manifest_key, raw_key
from holocron.resources.clickhouse import ClickHouseResource
from holocron.resources.http import HttpClientResource
from holocron.resources.local_release import LocalReleaseStorageResource
from holocron.resources.s3 import S3Resource


def merged_config(source: SourceSpec, config: dict[str, Any] | None) -> dict[str, Any]:
    return {**source.default_config, **(config or {})}


def manifest_config_metadata(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items()}


def resolve_release_id(config: dict[str, Any]) -> str:
    for key in ("release_id", "batch_id", "run_id"):
        value = str(config.get(key, "")).strip()
        if value:
            return value
    return new_release_id()


def stage_local_source(
    *,
    context: AssetExecutionContext,
    source: SourceSpec,
    config: dict[str, Any] | None,
    http: HttpClientResource,
    local_storage: LocalReleaseStorageResource,
) -> LocalReleaseManifest:
    source_config = merged_config(source, config)
    release_id = resolve_release_id(source_config)
    context.log.info(f"{source.name}: release_id={release_id}")

    declared_tables = {table.csv_name: table for table in source.tables}
    artifacts = []
    output_dir = local_storage.reset_release_dir(source.name, release_id)
    context.log.info(f"{source.name}: staging local release in {output_dir}")

    paths = list(
        source.extract_fn(
            output_dir,
            release_id=release_id,
            config=source_config,
            http=http,
            context=context,
        )
    )
    for path in paths:
        table_spec = declared_tables.get(path.name)
        if table_spec is None:
            context.log.warning(f"{source.name}: skipping undeclared output {path.name}")
            continue
        artifact = build_local_file_artifact(path, table_name=table_spec.table_name)
        artifacts.append(artifact)
        context.log.info(
            f"{source.name}: staged {table_spec.csv_name} "
            f"({artifact.size_bytes:,} bytes, {artifact.row_count:,} rows)"
        )

    return LocalReleaseManifest(
        dataset=source.name,
        release_id=release_id,
        mode=source.mode,
        source=source.source,
        created_at=utc_now_iso(),
        root_path=str(output_dir),
        files=artifacts,
        metadata={"config": manifest_config_metadata(source_config)},
    )


def promote_local_source(
    *,
    context: AssetExecutionContext,
    source: SourceSpec,
    local_release: LocalReleaseManifest,
    s3: S3Resource,
) -> ReleaseManifest:
    artifacts = []
    for local_file in local_release.files:
        local_path = Path(local_file.local_path)
        if not local_path.exists():
            raise FileNotFoundError(
                f"Expected local staged file for {source.name} release {local_release.release_id}: "
                f"{local_path}"
            )
        s3_key = raw_key(source.name, local_release.release_id, local_file.name)
        s3.upload_file(local_path, s3_key)
        artifact = FileArtifact(
            name=local_file.name,
            s3_key=s3_key,
            size_bytes=local_file.size_bytes,
            sha256=local_file.sha256,
            row_count=local_file.row_count,
            table_name=local_file.table_name,
        )
        artifacts.append(artifact)
        context.log.info(
            f"{source.name}: uploaded {local_file.name} "
            f"({artifact.size_bytes:,} bytes, {artifact.row_count:,} rows)"
        )

    manifest = ReleaseManifest(
        dataset=source.name,
        release_id=local_release.release_id,
        mode=source.mode,
        source=source.source,
        created_at=utc_now_iso(),
        files=artifacts,
        metadata={
            "local_root_path": local_release.root_path,
            "local_file_count": len(local_release.files),
            **local_release.metadata,
        },
    )
    s3.put_json(manifest_key(source.name, local_release.release_id), manifest.to_json())
    return manifest


def cleanup_local_release(
    *,
    source: SourceSpec,
    release_id: str,
    local_storage: LocalReleaseStorageResource,
) -> bool:
    return local_storage.delete_release_dir(source.name, release_id)


def publish_table(
    *,
    context: AssetExecutionContext,
    source: SourceSpec,
    table_spec: TableSpec,
    manifest: ReleaseManifest,
    s3: S3Resource,
    clickhouse: ClickHouseResource,
) -> tuple[int, Any]:
    artifact = artifact_for_table(manifest, table_spec)
    s3_url = s3.s3_url(artifact.s3_key)
    context.log.info(f"{source.name}: publishing {table_spec.table_name} from {artifact.s3_key}")
    kwargs = {
        "table": table_spec.table_name,
        "s3_url": s3_url,
        "aws_access_key_id": s3.aws_access_key_id,
        "aws_secret_access_key": s3.aws_secret_access_key,
        "format": table_spec.file_format,
        "staging_suffix": manifest.release_id,
        "allow_empty": table_spec.min_rows == 0,
    }
    if table_spec.load_strategy == FULL_SWAP:
        row_count = clickhouse.load_table_from_s3(**kwargs)
    elif table_spec.load_strategy == APPEND:
        row_count = clickhouse.append_table_from_s3(
            **kwargs,
            dedupe_key=table_spec.unique_key,
        )
    else:
        raise ValueError(
            f"Unsupported load strategy {table_spec.load_strategy!r} for {table_spec.table_name}"
        )
    return row_count, artifact
