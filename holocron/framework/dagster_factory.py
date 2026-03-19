"""Dagster factory functions for Holocron sources."""

from __future__ import annotations

from dagster import (
    AssetCheckSpec,
    AssetIn,
    AssetSelection,
    AssetSpec,
    MaterializeResult,
    MetadataValue,
    Output,
    ScheduleDefinition,
    asset,
    define_asset_job,
    job,
    multi_asset,
    op,
)
from holocron.framework.storage import manifest_key

from holocron.framework.models import (
    GROUPED,
    LocalReleaseManifest,
    ReleaseManifest,
    SourceSpec,
    TableSpec,
    optional_str,
)
from holocron.framework.runner import (
    cleanup_local_release,
    manifest_config_metadata,
    promote_local_source,
    publish_table,
    resolve_release_id,
    stage_local_source,
)
from holocron.framework.validation import check_names_for_table, run_checks_for_table
from holocron.resources.clickhouse import ClickHouseResource
from holocron.resources.http import HttpClientResource
from holocron.resources.local_release import LocalReleaseStorageResource
from holocron.resources.s3 import S3Resource


def _check_specs_for_table(source: SourceSpec, table_spec: TableSpec) -> list[AssetCheckSpec]:
    return [
        AssetCheckSpec(name=check_name, asset=table_spec.table_name)
        for check_name in check_names_for_table(source, table_spec)
    ]


def _manifest_totals(files) -> tuple[int, int]:
    total_bytes = sum(file.size_bytes for file in files)
    total_rows = sum(file.row_count or 0 for file in files)
    return total_bytes, total_rows


def _local_release_metadata(manifest: LocalReleaseManifest) -> dict:
    total_bytes, total_rows = _manifest_totals(manifest.files)
    metadata = {
        "release_id": manifest.release_id,
        "local_root_path": MetadataValue.path(manifest.root_path),
        "file_count": len(manifest.files),
        "total_bytes": total_bytes,
        "total_rows": total_rows,
        "files": MetadataValue.json(
            [
                {
                    "name": file.name,
                    "local_path": file.local_path,
                    "size_bytes": file.size_bytes,
                    "row_count": file.row_count,
                    "table_name": file.table_name,
                }
                for file in manifest.files
            ]
        ),
    }
    if manifest.metadata:
        metadata["manifest_metadata"] = MetadataValue.json(manifest.metadata)
    return metadata


def _raw_release_metadata(manifest: ReleaseManifest) -> dict:
    total_bytes, total_rows = _manifest_totals(manifest.files)
    metadata = {
        "release_id": manifest.release_id,
        "manifest_key": manifest_key(manifest.dataset, manifest.release_id),
        "file_count": len(manifest.files),
        "total_bytes": total_bytes,
        "total_rows": total_rows,
        "local_root_path": manifest.metadata.get("local_root_path", ""),
        "files": MetadataValue.json(
            [
                {
                    "name": file.name,
                    "s3_key": file.s3_key,
                    "size_bytes": file.size_bytes,
                    "row_count": file.row_count,
                    "table_name": file.table_name,
                }
                for file in manifest.files
            ]
        ),
    }
    if manifest.metadata:
        metadata["manifest_metadata"] = MetadataValue.json(manifest.metadata)
    return metadata


def _effective_config_metadata(config: dict) -> MetadataValue:
    return MetadataValue.json({key: value for key, value in config.items()})


def _asset_tags(
    source: SourceSpec, *, asset_type: str, table_name: str | None = None
) -> dict[str, str]:
    tags = {
        "provider": source.provider_name,
        "dataset": source.name,
        "asset_type": asset_type,
    }
    if table_name:
        tags["table"] = table_name
    return tags


def build_local_release_asset(source: SourceSpec):
    @asset(
        name=source.local_release_asset_name,
        group_name=source.asset_group_name,
        tags=_asset_tags(source, asset_type="local_release"),
        config_schema=source.config_schema or None,
        description=(
            f"Scrape {source.name} source files into the mounted local staging volume. "
            "This is the resumable boundary before S3 upload."
        ),
    )
    def local_release_asset(
        context,
        http: HttpClientResource,
        local_storage: LocalReleaseStorageResource,
    ) -> Output[dict]:
        config = dict(context.op_config)
        manifest = stage_local_source(
            context=context,
            source=source,
            config=config,
            http=http,
            local_storage=local_storage,
        )
        metadata = _local_release_metadata(manifest)
        metadata["config"] = _effective_config_metadata(manifest_config_metadata(config))
        return Output(
            manifest.model_dump(mode="json"),
            metadata=metadata,
        )

    return local_release_asset


def build_raw_release_asset(source: SourceSpec):
    @asset(
        name=source.raw_release_asset_name,
        group_name=source.asset_group_name,
        tags=_asset_tags(source, asset_type="raw_release"),
        ins={"local_release": AssetIn(key=source.local_release_asset_name)},
        description=(
            f"Upload staged {source.name} files from local storage to S3 and write the raw "
            "release manifest. This is the durable boundary before warehouse publish."
        ),
    )
    def raw_release_asset(
        context,
        local_release: dict,
        s3: S3Resource,
    ) -> Output[dict]:
        local_manifest = LocalReleaseManifest.model_validate(local_release)
        manifest = promote_local_source(
            context=context,
            source=source,
            local_release=local_manifest,
            s3=s3,
        )
        return Output(
            manifest.model_dump(mode="json"),
            metadata=_raw_release_metadata(manifest),
        )

    return raw_release_asset


def build_grouped_publish_asset(source: SourceSpec):
    release_key = source.raw_release_asset_name
    specs = [
        AssetSpec(
            key=table.table_name,
            group_name=source.asset_group_name,
            tags=_asset_tags(source, asset_type="table", table_name=table.table_name),
        )
        for table in source.tables
    ]
    all_check_specs = [
        check_spec
        for table in source.tables
        for check_spec in _check_specs_for_table(source, table)
    ]

    @multi_asset(
        name=f"{source.name}_publish",
        group_name=source.asset_group_name,
        ins={"release": AssetIn(key=release_key)},
        specs=specs,
        can_subset=False,
        check_specs=all_check_specs,
    )
    def publish_assets(
        context,
        release: dict,
        s3: S3Resource,
        clickhouse: ClickHouseResource,
    ):
        manifest = ReleaseManifest.model_validate(release)
        for table_spec in source.tables:
            row_count, artifact = publish_table(
                context=context,
                source=source,
                table_spec=table_spec,
                manifest=manifest,
                s3=s3,
                clickhouse=clickhouse,
            )
            yield MaterializeResult(
                asset_key=table_spec.table_name,
                metadata={
                    "row_count": row_count,
                    "release_id": manifest.release_id,
                    "csv_name": artifact.name,
                    "s3_key": artifact.s3_key,
                },
                check_results=run_checks_for_table(
                    source=source,
                    table_spec=table_spec,
                    manifest=manifest,
                    clickhouse=clickhouse,
                    context=context,
                ),
            )

    return [publish_assets]


def build_per_table_publish_assets(source: SourceSpec):
    assets = []
    release_key = source.raw_release_asset_name

    for table_spec in source.tables:
        check_specs = _check_specs_for_table(source, table_spec)

        def _build_publish_asset(current_table: TableSpec, current_check_specs):
            @asset(
                name=current_table.table_name,
                group_name=source.asset_group_name,
                tags=_asset_tags(source, asset_type="table", table_name=current_table.table_name),
                ins={"release": AssetIn(key=release_key)},
                check_specs=current_check_specs,
                description=(
                    f"Load {current_table.csv_name} from the {source.name} raw S3 release into "
                    f"ClickHouse table {current_table.table_name}."
                ),
            )
            def publish_asset(
                context,
                release: dict,
                s3: S3Resource,
                clickhouse: ClickHouseResource,
            ) -> MaterializeResult:
                manifest = ReleaseManifest.model_validate(release)
                row_count, artifact = publish_table(
                    context=context,
                    source=source,
                    table_spec=current_table,
                    manifest=manifest,
                    s3=s3,
                    clickhouse=clickhouse,
                )
                return MaterializeResult(
                    metadata={
                        "row_count": row_count,
                        "release_id": manifest.release_id,
                        "csv_name": artifact.name,
                        "s3_key": artifact.s3_key,
                    },
                    check_results=run_checks_for_table(
                        source=source,
                        table_spec=current_table,
                        manifest=manifest,
                        clickhouse=clickhouse,
                        context=context,
                    ),
                )

            return publish_asset

        assets.append(_build_publish_asset(table_spec, check_specs))

    return assets


def build_assets_for_source(source: SourceSpec):
    local_release_asset = build_local_release_asset(source)
    raw_release_asset = build_raw_release_asset(source)
    if source.publish_mode == GROUPED:
        publish_assets = build_grouped_publish_asset(source)
    else:
        publish_assets = build_per_table_publish_assets(source)
    return [local_release_asset, raw_release_asset, *publish_assets]


def build_job_for_source(source: SourceSpec):
    return define_asset_job(
        name=source.ingest_job_name,
        selection=AssetSelection.assets(
            source.local_release_asset_name,
            source.raw_release_asset_name,
            *(table.table_name for table in source.tables),
        ),
        description=(
            source.description
            or f"Run the {source.name} pipeline from local staging to raw S3 release to publish."
        ),
    )


def build_cleanup_job_for_source(source: SourceSpec):
    cleanup_config_schema = {
        "release_id": optional_str(""),
        "batch_id": optional_str(""),
        "run_id": optional_str(""),
    }

    @op(
        name=f"{source.name}_cleanup_local_release",
        config_schema=cleanup_config_schema,
        description=(
            f"Delete the mounted local staging directory for a {source.name} release after "
            "raw upload has completed successfully."
        ),
    )
    def cleanup_op(context, local_storage: LocalReleaseStorageResource) -> None:
        release_id = resolve_release_id(dict(context.op_config))
        if not release_id:
            raise ValueError(f"{source.name}: cleanup requires release_id, batch_id, or run_id")
        deleted = cleanup_local_release(
            source=source,
            release_id=release_id,
            local_storage=local_storage,
        )
        if deleted:
            context.log.info(f"{source.name}: cleaned local release {release_id}")
        else:
            context.log.info(f"{source.name}: no local release found for {release_id}")

    @job(
        name=source.cleanup_job_name,
        description=f"Delete staged local files for a {source.name} release by release_id.",
    )
    def cleanup_job():
        cleanup_op()

    return cleanup_job


def build_schedule_for_source(source: SourceSpec, job_def):
    if not source.schedule:
        return None
    return ScheduleDefinition(
        job=job_def,
        cron_schedule=source.schedule,
        name=source.schedule_name,
    )
