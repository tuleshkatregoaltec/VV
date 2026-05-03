from dagster import (
    AssetExecutionContext,
    AssetIn,
    AssetsDefinition,
    ConfigMapping,
    DefaultScheduleStatus,
    Failure,
    Field,
    JobDefinition,
    MaterializeResult,
    MetadataValue,
    Output,
    Permissive,
    ScheduleDefinition,
    StringSource,
    asset,
    define_asset_job,
)

from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from holocron.contracts import RawRelease, SourceSpec
from holocron.platform.checkpoints import read_checkpoint, write_checkpoint
from holocron.platform.execution import utc_now
from holocron.platform.manifests import manifest_s3_key, raw_file_s3_key
from holocron.platform.resources import ClickHouseResource, S3Resource
from holocron.sources.bay_locations.source import DEFAULT_DUBAI_LOCATION_QUERIES

_DUBAI_TIMEZONE = "Asia/Dubai"
_REELLY_ARCHIVE_OPERATION = "archive_chunk"
_BAY_LOCATIONS_FULL_FETCH_DEFAULTS = {
    "queries": list(DEFAULT_DUBAI_LOCATION_QUERIES),
    "max_pages": 20,
    "only_dubai": True,
    "include_ancestors": True,
    "stop_after_pages_without_new": 2,
}
_REELLY_ARCHIVE_CHUNK_DEFAULTS = {
    "pages_per_run": 5,
    "download_documents": True,
    "download_all_project_docs": True,
}


def _raw_asset_name(source: SourceSpec) -> str:
    return f"{source.name}_raw"


def _bronze_asset_name(source: SourceSpec) -> str:
    return f"{source.name}_bronze"


def _resolve_source_config(context: AssetExecutionContext) -> dict:
    config = context.op_execution_context.op_config
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise TypeError(f"Expected dict-like source config, got {type(config)!r}")
    return config


def _resolve_reelly_archive_config(
    *,
    source_config: Mapping[str, Any],
    s3_client: Any,
) -> dict[str, Any]:
    resolved_config = dict(source_config)
    reset_checkpoint = bool(resolved_config.pop("reset_checkpoint", False))
    checkpoint = read_checkpoint(
        s3_client,
        source="reelly_supply",
        operation=_REELLY_ARCHIVE_OPERATION,
    )
    if checkpoint and checkpoint.get("completed") and not reset_checkpoint:
        raise Failure(
            description=(
                "Reelly supply archive checkpoint is already completed. "
                "Pass reset_checkpoint=true to run another archive pass."
            ),
            metadata={
                "source": "reelly_supply",
                "operation": _REELLY_ARCHIVE_OPERATION,
            },
        )

    has_explicit_cursor = (
        "page_cursor" in resolved_config and resolved_config["page_cursor"] is not None
    )
    if (
        checkpoint
        and not reset_checkpoint
        and not has_explicit_cursor
        and checkpoint.get("next_page") is not None
    ):
        resolved_config["page_cursor"] = checkpoint["next_page"]
    return resolved_config


def _write_reelly_archive_checkpoint(
    *,
    raw_release: RawRelease,
    manifest_key: str,
    s3_client: Any,
) -> None:
    metadata = dict(raw_release.metadata)
    write_checkpoint(
        s3_client,
        source=raw_release.source,
        operation=_REELLY_ARCHIVE_OPERATION,
        payload={
            "next_page": metadata.get("next_page"),
            "completed": bool(metadata.get("batch_completed_result_set")),
            "last_run_id": raw_release.run_id,
            "last_manifest_s3_key": manifest_key,
            "page_total": metadata.get("page_total"),
            "updated_at": utc_now().isoformat(),
        },
    )


def _raw_release_file_path(*, scratch_path: Path, local_path: Path) -> str:
    try:
        return local_path.resolve().relative_to(scratch_path.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Raw file path is outside extractor scratch directory: {local_path}"
        ) from exc


def _run_raw_extractor(
    *,
    context: AssetExecutionContext,
    source: SourceSpec,
    s3: S3Resource,
) -> tuple[dict, dict]:
    source_config = _resolve_source_config(context)
    s3_client = s3.client()
    if source.name == "reelly_supply":
        source_config = _resolve_reelly_archive_config(
            source_config=source_config,
            s3_client=s3_client,
        )
    context.log.info(
        "materializing raw source=%s with config keys=%s", source.name, sorted(source_config)
    )

    with TemporaryDirectory(prefix=f"holocron-{source.name}-") as scratch_dir:
        raw_release = source.extractor(scratch_dir, config=source_config)
        if not isinstance(raw_release, RawRelease):
            raise TypeError(
                f"Extractor for source={source.name} must return RawRelease, got {type(raw_release)!r}"
            )
        if raw_release.source != source.name:
            raise ValueError(
                f"Extractor source mismatch: expected {source.name}, got {raw_release.source}"
            )
        if not raw_release.files:
            raise ValueError(f"Extractor for source={source.name} returned no files")

        manifest_files: list[dict] = []
        total_rows = 0

        scratch_path = Path(scratch_dir)
        for raw_file in raw_release.files:
            local_path = Path(raw_file.path)
            if not local_path.exists():
                raise FileNotFoundError(
                    f"Raw file does not exist for source={source.name}: {local_path}"
                )

            file_path = _raw_release_file_path(scratch_path=scratch_path, local_path=local_path)
            file_key = raw_file_s3_key(
                source=raw_release.source,
                extract_date=raw_release.extract_date,
                run_id=raw_release.run_id,
                file_name=file_path,
            )
            s3_client.upload_file(
                path=local_path,
                key=file_key,
                content_type=raw_file.content_type,
            )

            if raw_file.row_count is not None:
                total_rows += raw_file.row_count

            manifest_files.append(
                {
                    "path": file_path,
                    "sha256": raw_file.sha256,
                    "size_bytes": raw_file.size_bytes,
                    "row_count": raw_file.row_count,
                    "content_type": raw_file.content_type,
                    "metadata": dict(raw_file.metadata),
                    "s3_key": file_key,
                }
            )

        manifest_payload = {
            "source": raw_release.source,
            "run_id": raw_release.run_id,
            "extract_date": raw_release.extract_date,
            "created_at": raw_release.created_at,
            "manifest_version": raw_release.manifest_version,
            "schema_version": raw_release.schema_version,
            "files": manifest_files,
            "metadata": dict(raw_release.metadata),
        }

        manifest_key = manifest_s3_key(source=raw_release.source, run_id=raw_release.run_id)
        s3_client.put_json(key=manifest_key, payload=manifest_payload)
        if source.name == "reelly_supply":
            _write_reelly_archive_checkpoint(
                raw_release=raw_release,
                manifest_key=manifest_key,
                s3_client=s3_client,
            )

    release_payload = {
        "source": raw_release.source,
        "run_id": raw_release.run_id,
        "extract_date": raw_release.extract_date,
        "created_at": raw_release.created_at,
        "manifest_version": raw_release.manifest_version,
        "schema_version": raw_release.schema_version,
        "files": manifest_files,
        "metadata": dict(raw_release.metadata),
        "manifest_s3_key": manifest_key,
    }
    output_metadata = {
        "source": source.name,
        "provider": source.provider,
        "stage": "raw",
        "status": "materialized",
        "run_id": raw_release.run_id,
        "extract_date": raw_release.extract_date,
        "file_count": len(raw_release.files),
        "total_rows": total_rows,
        "manifest_s3_key": manifest_key,
        "files": MetadataValue.json(manifest_files),
    }
    return release_payload, output_metadata


def _run_bronze_loader(
    *,
    context: AssetExecutionContext,
    source: SourceSpec,
    raw_release: dict,
    s3: S3Resource,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    if source.bronze_loader is None:
        raise ValueError(f"No bronze loader configured for source={source.name}")

    result = source.bronze_loader(
        raw_release=raw_release,
        s3=s3.client(),
        clickhouse=clickhouse.client(),
    )
    return MaterializeResult(
        metadata={
            "source": source.name,
            "stage": "bronze",
            "status": "materialized",
            "run_id": result["run_id"],
            "table_count": result["table_count"],
            "total_rows": result["total_rows"],
            "table_row_counts": MetadataValue.json(result["table_row_counts"]),
        }
    )


def build_assets_for_source(source: SourceSpec) -> list[AssetsDefinition]:
    """Produce the raw -> bronze asset chain for one source.

    Raw extraction is taken from SourceSpec.extractor, and bronze loading is
    delegated to SourceSpec.bronze_loader when the source declares bronze tables.
    """
    raw_name = _raw_asset_name(source)
    bronze_name = _bronze_asset_name(source)

    @asset(name=raw_name, group_name=source.name, config_schema=Permissive())
    def raw_asset(
        context: AssetExecutionContext,
        s3: S3Resource,
    ) -> Output[dict]:
        release_payload, output_metadata = _run_raw_extractor(context=context, source=source, s3=s3)
        return Output(release_payload, metadata=output_metadata)

    assets = [raw_asset]
    if not source.bronze_tables:
        return assets

    @asset(name=bronze_name, ins={"raw_release": AssetIn(key=raw_name)}, group_name=source.name)
    def bronze_asset(
        context: AssetExecutionContext,
        raw_release: dict,
        clickhouse: ClickHouseResource,
        s3: S3Resource,
    ) -> MaterializeResult:
        if not isinstance(raw_release, dict):
            raise TypeError(f"Expected raw release payload dict, got {type(raw_release)!r}")
        return _run_bronze_loader(
            context=context,
            source=source,
            raw_release=raw_release,
            s3=s3,
            clickhouse=clickhouse,
        )

    return [raw_asset, bronze_asset]


def build_operational_jobs(sources: Mapping[str, SourceSpec]) -> list[JobDefinition]:
    return [
        _build_source_asset_job(
            source=sources["bay_listings"],
            name="bay_listings_daily_incremental",
            raw_only=False,
        ),
        _build_source_asset_job(
            source=sources["bay_transactions"],
            name="bay_transactions_daily_incremental",
            raw_only=False,
            config=_raw_asset_run_config(sources["bay_transactions"], {"mode": "incremental"}),
        ),
        _build_source_asset_job(
            source=sources["dld_transactions"],
            name="dld_transactions_daily_incremental",
            raw_only=False,
            config=_raw_asset_run_config(sources["dld_transactions"], {"mode": "incremental"}),
        ),
        _build_source_asset_job(
            source=sources["dxbi_transactions"],
            name="dxbi_transactions_daily_incremental",
            raw_only=False,
            config=_raw_asset_run_config(sources["dxbi_transactions"], {"mode": "incremental"}),
        ),
        _build_source_asset_job(
            source=sources["dda_planning_layers"],
            name="dda_planning_layers_weekly_full_refresh",
            raw_only=False,
        ),
        _build_source_asset_job(
            source=sources["bay_locations"],
            name="bay_locations_manual_full_fetch",
            raw_only=False,
            config=_defaulted_raw_config_mapping(
                sources["bay_locations"],
                defaults=_BAY_LOCATIONS_FULL_FETCH_DEFAULTS,
            ),
        ),
        _build_source_asset_job(
            source=sources["bay_transactions"],
            name="bay_transactions_manual_backfill",
            raw_only=False,
            config=_backfill_config_mapping(sources["bay_transactions"]),
        ),
        _build_source_asset_job(
            source=sources["dld_transactions"],
            name="dld_transactions_manual_backfill",
            raw_only=False,
            config=_backfill_config_mapping(sources["dld_transactions"]),
        ),
        _build_source_asset_job(
            source=sources["dxbi_transactions"],
            name="dxbi_transactions_manual_backfill",
            raw_only=False,
            config=_backfill_config_mapping(sources["dxbi_transactions"]),
        ),
        _build_source_asset_job(
            source=sources["dda_planning_layers"],
            name="dda_planning_layers_manual_full_refresh",
            raw_only=False,
            config=_defaulted_raw_config_mapping(sources["dda_planning_layers"], defaults={}),
        ),
        _build_source_asset_job(
            source=sources["reelly_supply"],
            name="reelly_supply_archive_chunk",
            raw_only=True,
            config=_reelly_archive_config_mapping(sources["reelly_supply"]),
        ),
    ]


def build_operational_schedules(
    jobs_by_name: Mapping[str, JobDefinition],
) -> list[ScheduleDefinition]:
    schedule_specs = {
        "dld_transactions_daily_incremental": "0 5 * * *",
        "bay_transactions_daily_incremental": "30 5 * * *",
        "dxbi_transactions_daily_incremental": "0 6 * * *",
        "bay_listings_daily_incremental": "30 6 * * *",
        "dda_planning_layers_weekly_full_refresh": "0 6 * * 0",
    }
    return [
        ScheduleDefinition(
            name=f"{job_name}_schedule",
            job=jobs_by_name[job_name],
            cron_schedule=cron_schedule,
            execution_timezone=_DUBAI_TIMEZONE,
            default_status=DefaultScheduleStatus.STOPPED,
        )
        for job_name, cron_schedule in schedule_specs.items()
    ]


def _build_source_asset_job(
    *,
    source: SourceSpec,
    name: str,
    raw_only: bool,
    config: Mapping[str, Any] | ConfigMapping | None = None,
) -> JobDefinition:
    return define_asset_job(
        name=name,
        selection=_source_asset_selection(source, raw_only=raw_only),
        config=config,
    )


def _source_asset_selection(source: SourceSpec, *, raw_only: bool) -> list[str]:
    selection = [_raw_asset_name(source)]
    if source.bronze_tables and not raw_only:
        selection.append(_bronze_asset_name(source))
    return selection


def _raw_asset_run_config(source: SourceSpec, source_config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ops": {
            _raw_asset_name(source): {
                "config": dict(source_config),
            }
        }
    }


def _backfill_config_mapping(source: SourceSpec) -> ConfigMapping:
    def _map_backfill_config(config: Mapping[str, Any]) -> dict[str, Any]:
        overrides = _source_overrides(config, reserved_keys={"start_date", "end_date"})
        source_config = {
            **overrides,
            "mode": "backfill",
            "start_date": config["start_date"],
            "end_date": config["end_date"],
        }
        return _raw_asset_run_config(source, source_config)

    return ConfigMapping(
        config_fn=_map_backfill_config,
        config_schema=Permissive(
            {
                "start_date": Field(StringSource, description="Inclusive backfill start date."),
                "end_date": Field(StringSource, description="Inclusive backfill end date."),
                "overrides": Field(
                    Permissive(),
                    default_value={},
                    is_required=False,
                    description="Optional source-specific raw asset config overrides.",
                ),
            }
        ),
        receive_processed_config_values=True,
    )


def _defaulted_raw_config_mapping(
    source: SourceSpec,
    *,
    defaults: Mapping[str, Any],
) -> ConfigMapping:
    def _map_defaulted_config(config: Mapping[str, Any]) -> dict[str, Any]:
        overrides = _source_overrides(config)
        return _raw_asset_run_config(source, {**defaults, **overrides})

    return ConfigMapping(
        config_fn=_map_defaulted_config,
        config_schema=Permissive(
            {
                "overrides": Field(
                    Permissive(),
                    default_value={},
                    is_required=False,
                    description="Optional source-specific raw asset config overrides.",
                )
            }
        ),
        receive_processed_config_values=True,
    )


def _reelly_archive_config_mapping(source: SourceSpec) -> ConfigMapping:
    def _map_reelly_config(config: Mapping[str, Any]) -> dict[str, Any]:
        overrides = _source_overrides(config, reserved_keys={"reset_checkpoint"})
        source_config = {**_REELLY_ARCHIVE_CHUNK_DEFAULTS, **overrides}
        if config.get("reset_checkpoint"):
            source_config["reset_checkpoint"] = True
        return _raw_asset_run_config(source, source_config)

    return ConfigMapping(
        config_fn=_map_reelly_config,
        config_schema=Permissive(
            {
                "reset_checkpoint": Field(
                    bool,
                    default_value=False,
                    is_required=False,
                    description="Ignore a completed Reelly archive checkpoint and start a new pass.",
                ),
                "overrides": Field(
                    Permissive(),
                    default_value={},
                    is_required=False,
                    description="Optional Reelly raw asset config overrides.",
                ),
            }
        ),
        receive_processed_config_values=True,
    )


def _source_overrides(
    config: Mapping[str, Any],
    *,
    reserved_keys: set[str] | None = None,
) -> dict[str, Any]:
    reserved = {"overrides", *(reserved_keys or set())}
    direct_overrides = {key: value for key, value in config.items() if key not in reserved}
    nested_overrides = dict(config.get("overrides") or {})
    return {**direct_overrides, **nested_overrides}
