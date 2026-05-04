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
from holocron.sources.pf_listings.media_assets import (
    PropertyFinderListingMediaHydrationConfig,
    hydrate_pf_listing_media_assets,
)
from holocron.sources.reelly_supply.document_assets import (
    ReellyDocumentAssetHydrationConfig,
    hydrate_reelly_document_assets,
)

_DUBAI_TIMEZONE = "Asia/Dubai"
_REELLY_ARCHIVE_OPERATION = "archive_chunk"
_PF_LISTINGS_PLAN_OPERATION = "plan_snapshot"
_PF_LISTINGS_SEARCH_OPERATION = "search_chunk"
_PF_LISTINGS_DETAIL_OPERATION = "detail_chunk"
_BAY_LOCATIONS_FULL_FETCH_DEFAULTS = {
    "queries": list(DEFAULT_DUBAI_LOCATION_QUERIES),
    "max_pages": 20,
    "only_dubai": True,
    "include_ancestors": True,
    "stop_after_pages_without_new": 2,
}
_REELLY_ARCHIVE_CHUNK_DEFAULTS = {
    "pages_per_run": 5,
    "download_documents": False,
    "download_all_project_docs": True,
}
_PF_LISTINGS_MANUAL_SNAPSHOT_DEFAULTS = {
    "mode": "snapshot",
    "max_planned_queries": 12000,
    "max_search_pages_per_run": 50000,
    "max_details_per_run": 100000,
    "fetch_details": True,
    "split_by_location": True,
}
_PF_LISTINGS_PLAN_DEFAULTS = {
    "mode": "plan",
    "max_planned_queries": 25000,
    "max_results_per_query": 750,
    "max_partition_depth": 10,
    "split_by_location": True,
}
_PF_LISTINGS_SEARCH_CHUNK_DEFAULTS = {
    "mode": "search",
    "max_search_pages_per_run": 10000,
    "fetch_details": False,
}
_PF_LISTINGS_DETAIL_CHUNK_DEFAULTS = {
    "mode": "details",
    "max_details_per_run": 25000,
    "fetch_details": True,
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


def _resolve_pf_listings_config(
    *,
    source_config: Mapping[str, Any],
    s3_client: Any,
) -> dict[str, Any]:
    resolved_config = dict(source_config)
    reset_checkpoint = bool(resolved_config.pop("reset_checkpoint", False))
    mode = str(resolved_config.get("mode") or "snapshot")

    if mode == "search":
        plan_manifest_key = str(resolved_config.get("plan_manifest_s3_key") or "").strip()
        if not plan_manifest_key:
            plan_checkpoint = read_checkpoint(
                s3_client,
                source="pf_listings",
                operation=_PF_LISTINGS_PLAN_OPERATION,
            )
            plan_manifest_key = (
                str(plan_checkpoint.get("last_manifest_s3_key") or "").strip()
                if plan_checkpoint
                else ""
            )
        if not plan_manifest_key:
            raise Failure(
                description=(
                    "Property Finder search chunks require a completed planning manifest. "
                    "Run pf_listings_plan_snapshot first or pass plan_manifest_s3_key."
                ),
                metadata={"source": "pf_listings", "operation": _PF_LISTINGS_SEARCH_OPERATION},
            )
        resolved_config["plan_manifest_s3_key"] = plan_manifest_key

        has_explicit_cursor = (
            "search_query_cursor" in source_config or "search_page_cursor" in source_config
        )
        checkpoint = read_checkpoint(
            s3_client,
            source="pf_listings",
            operation=_PF_LISTINGS_SEARCH_OPERATION,
        )
        if (
            checkpoint
            and not reset_checkpoint
            and checkpoint.get("plan_manifest_s3_key") == plan_manifest_key
        ):
            if checkpoint.get("completed"):
                raise Failure(
                    description=(
                        "Property Finder search checkpoint is already completed for the "
                        "current plan. Pass reset_checkpoint=true or run a new plan."
                    ),
                    metadata={
                        "source": "pf_listings",
                        "operation": _PF_LISTINGS_SEARCH_OPERATION,
                        "plan_manifest_s3_key": plan_manifest_key,
                    },
                )
            if not has_explicit_cursor:
                resolved_config["search_query_cursor"] = checkpoint.get("next_query_index", 0)
                resolved_config["search_page_cursor"] = checkpoint.get("next_page", 1)
        return resolved_config

    if mode == "details":
        has_explicit_cursor = (
            "detail_manifest_cursor" in source_config or "detail_row_cursor" in source_config
        )
        checkpoint = read_checkpoint(
            s3_client,
            source="pf_listings",
            operation=_PF_LISTINGS_DETAIL_OPERATION,
        )
        if checkpoint and not reset_checkpoint and not has_explicit_cursor:
            resolved_config["detail_manifest_cursor"] = checkpoint.get("next_manifest_index", 0)
            resolved_config["detail_row_cursor"] = checkpoint.get("next_row_index", 0)
        return resolved_config

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


def _write_pf_listings_checkpoint(
    *,
    raw_release: RawRelease,
    manifest_key: str,
    s3_client: Any,
) -> None:
    metadata = dict(raw_release.metadata)
    stage = metadata.get("stage")
    if stage == "plan":
        write_checkpoint(
            s3_client,
            source=raw_release.source,
            operation=_PF_LISTINGS_PLAN_OPERATION,
            payload={
                "completed": True,
                "last_run_id": raw_release.run_id,
                "last_manifest_s3_key": manifest_key,
                "planned_query_count": metadata.get("planned_query_count"),
                "terminal_query_count": metadata.get("terminal_query_count"),
                "location_partition_count": metadata.get("location_partition_count"),
                "updated_at": utc_now().isoformat(),
            },
        )
        return

    if stage == "search":
        write_checkpoint(
            s3_client,
            source=raw_release.source,
            operation=_PF_LISTINGS_SEARCH_OPERATION,
            payload={
                "completed": bool(metadata.get("search_completed_result_set")),
                "next_query_index": metadata.get("next_query_index"),
                "next_page": metadata.get("next_page"),
                "plan_manifest_s3_key": metadata.get("plan_manifest_s3_key"),
                "last_run_id": raw_release.run_id,
                "last_manifest_s3_key": manifest_key,
                "search_page_count": metadata.get("search_page_count"),
                "property_row_count": metadata.get("property_row_count"),
                "search_error_count": metadata.get("search_error_count"),
                "updated_at": utc_now().isoformat(),
            },
        )
        return

    if stage == "details":
        write_checkpoint(
            s3_client,
            source=raw_release.source,
            operation=_PF_LISTINGS_DETAIL_OPERATION,
            payload={
                "completed": bool(metadata.get("detail_completed_result_set")),
                "next_manifest_index": metadata.get("next_manifest_index"),
                "next_row_index": metadata.get("next_row_index"),
                "source_manifest_count": metadata.get("source_manifest_count"),
                "source_property_row_count": metadata.get("source_property_row_count"),
                "last_run_id": raw_release.run_id,
                "last_manifest_s3_key": manifest_key,
                "detail_row_count": metadata.get("detail_row_count"),
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
    if source.name == "pf_listings":
        source_config = _resolve_pf_listings_config(
            source_config=source_config,
            s3_client=s3_client,
        )
    context.log.info(
        "materializing raw source=%s with config keys=%s", source.name, sorted(source_config)
    )

    with TemporaryDirectory(prefix=f"holocron-{source.name}-") as scratch_dir:
        extractor_kwargs: dict[str, Any] = {"config": source_config}
        if source.name in {
            "reelly_supply",
            "dxbi_transactions",
            "pf_locations",
            "pf_listings",
        }:
            extractor_kwargs["progress_log"] = context.log
        if source.name == "pf_listings":
            extractor_kwargs["state_store"] = s3_client
        raw_release = source.extractor(scratch_dir, **extractor_kwargs)
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
        if source.name == "pf_listings":
            _write_pf_listings_checkpoint(
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

_REELLY_PROJECT_MEDIA_DEFAULTS = {
    "target_prefix": "media/reelly_supply/project_media",
    "inventory_prefix": "raw/source=reelly_supply/project_media_asset_manifests",
    "inventory_file_name": "reelly_supply_project_media_assets.jsonl",
    "include_project_documents": False,
    "include_project_detail_media": True,
    "structured_target_keys": True,
    "max_concurrent_downloads": 8,
    "asset_type_allowlist": (
        "cover_image",
        "developer_logo",
        "building_image",
        "interior_image",
        "facility_image",
        "master_plan",
        "floorplan",
        "unit_image",
        "project_image",
    ),
}


def build_reelly_document_assets() -> list[AssetsDefinition]:
    @asset(
        name="reelly_supply_document_assets", group_name="reelly_supply", config_schema=Permissive()
    )
    def reelly_supply_document_assets(
        context: AssetExecutionContext,
        s3: S3Resource,
    ) -> MaterializeResult:
        result = hydrate_reelly_document_assets(
            s3=s3.client(),
            config=_resolve_source_config(context),
            progress_log=context.log,
        )
        return MaterializeResult(
            metadata={
                "source": "reelly_supply",
                "stage": "document_assets",
                "status": "materialized",
                "run_id": result["run_id"],
                "discovered": result["discovered"],
                "attempted": result["attempted"],
                "downloaded": result["downloaded"],
                "already_existing": result["already_existing"],
                "errors": result["errors"],
                "total_bytes": result["total_bytes"],
                "max_concurrent_downloads": result["max_concurrent_downloads"],
                "inventory_manifest_key": result["inventory_manifest_key"],
                "status_counts": MetadataValue.json(result["status_counts"]),
            }
        )

    @asset(
        name="reelly_supply_project_media_assets",
        group_name="reelly_supply",
        config_schema=Permissive(),
    )
    def reelly_supply_project_media_assets(
        context: AssetExecutionContext,
        s3: S3Resource,
    ) -> MaterializeResult:
        result = hydrate_reelly_document_assets(
            s3=s3.client(),
            config={**_REELLY_PROJECT_MEDIA_DEFAULTS, **_resolve_source_config(context)},
            progress_log=context.log,
        )
        return MaterializeResult(
            metadata={
                "source": "reelly_supply",
                "stage": "project_media_assets",
                "status": "materialized",
                "run_id": result["run_id"],
                "discovered": result["discovered"],
                "attempted": result["attempted"],
                "downloaded": result["downloaded"],
                "already_existing": result["already_existing"],
                "errors": result["errors"],
                "total_bytes": result["total_bytes"],
                "max_concurrent_downloads": result["max_concurrent_downloads"],
                "inventory_manifest_key": result["inventory_manifest_key"],
                "status_counts": MetadataValue.json(result["status_counts"]),
            }
        )

    return [reelly_supply_document_assets, reelly_supply_project_media_assets]


def build_pf_listing_media_assets() -> list[AssetsDefinition]:
    @asset(
        name="pf_listing_media_assets",
        group_name="pf_listings",
        config_schema=Permissive(),
    )
    def pf_listing_media_assets(
        context: AssetExecutionContext,
        s3: S3Resource,
    ) -> MaterializeResult:
        result = hydrate_pf_listing_media_assets(
            s3=s3.client(),
            config=_resolve_source_config(context),
            progress_log=context.log,
        )
        return MaterializeResult(
            metadata={
                "source": "pf_listings",
                "stage": "listing_media_assets",
                "status": "materialized",
                "run_id": result["run_id"],
                "discovered": result["discovered"],
                "attempted": result["attempted"],
                "downloaded": result["downloaded"],
                "already_existing": result["already_existing"],
                "errors": result["errors"],
                "total_bytes": result["total_bytes"],
                "max_concurrent_downloads": result["max_concurrent_downloads"],
                "inventory_manifest_key": result["inventory_manifest_key"],
                "status_counts": MetadataValue.json(result["status_counts"]),
            }
        )

    return [pf_listing_media_assets]


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
            source=sources["pf_locations"],
            name="pf_locations_manual_full_fetch",
            raw_only=True,
        ),
        _build_source_asset_job(
            source=sources["pf_listings"],
            name="pf_listings_manual_snapshot",
            raw_only=True,
            config=_defaulted_raw_config_mapping(
                sources["pf_listings"],
                defaults=_PF_LISTINGS_MANUAL_SNAPSHOT_DEFAULTS,
            ),
        ),
        _build_source_asset_job(
            source=sources["pf_listings"],
            name="pf_listings_plan_snapshot",
            raw_only=True,
            config=_pf_listings_config_mapping(
                sources["pf_listings"],
                defaults=_PF_LISTINGS_PLAN_DEFAULTS,
            ),
        ),
        _build_source_asset_job(
            source=sources["pf_listings"],
            name="pf_listings_search_chunk",
            raw_only=True,
            config=_pf_listings_config_mapping(
                sources["pf_listings"],
                defaults=_PF_LISTINGS_SEARCH_CHUNK_DEFAULTS,
            ),
        ),
        _build_source_asset_job(
            source=sources["pf_listings"],
            name="pf_listings_detail_chunk",
            raw_only=True,
            config=_pf_listings_config_mapping(
                sources["pf_listings"],
                defaults=_PF_LISTINGS_DETAIL_CHUNK_DEFAULTS,
            ),
        ),
        _build_source_asset_job(
            source=sources["reelly_supply"],
            name="reelly_supply_archive_chunk",
            raw_only=True,
            config=_reelly_archive_config_mapping(sources["reelly_supply"]),
        ),
        define_asset_job(
            name="reelly_supply_document_assets_backfill",
            selection=["reelly_supply_document_assets"],
            config=_reelly_document_asset_config_mapping(
                asset_name="reelly_supply_document_assets",
                defaults=ReellyDocumentAssetHydrationConfig(),
            ),
        ),
        define_asset_job(
            name="reelly_supply_project_media_assets_backfill",
            selection=["reelly_supply_project_media_assets"],
            config=_reelly_document_asset_config_mapping(
                asset_name="reelly_supply_project_media_assets",
                defaults=ReellyDocumentAssetHydrationConfig.model_validate(
                    _REELLY_PROJECT_MEDIA_DEFAULTS
                ),
            ),
        ),
        define_asset_job(
            name="pf_listing_media_assets_backfill",
            selection=["pf_listing_media_assets"],
            config=_pf_listing_media_asset_config_mapping(
                defaults=PropertyFinderListingMediaHydrationConfig(),
            ),
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


def _pf_listings_config_mapping(
    source: SourceSpec,
    *,
    defaults: Mapping[str, Any],
) -> ConfigMapping:
    def _map_pf_listings_config(config: Mapping[str, Any]) -> dict[str, Any]:
        overrides = _source_overrides(config, reserved_keys={"reset_checkpoint"})
        source_config = {**defaults, **overrides}
        if config.get("reset_checkpoint"):
            source_config["reset_checkpoint"] = True
        return _raw_asset_run_config(source, source_config)

    return ConfigMapping(
        config_fn=_map_pf_listings_config,
        config_schema=Permissive(
            {
                "reset_checkpoint": Field(
                    bool,
                    default_value=False,
                    is_required=False,
                    description="Ignore the relevant Property Finder checkpoint and start over.",
                ),
                "overrides": Field(
                    Permissive(),
                    default_value={},
                    is_required=False,
                    description="Optional Property Finder raw asset config overrides.",
                ),
            }
        ),
        receive_processed_config_values=True,
    )


def _reelly_document_asset_config_mapping(
    *,
    asset_name: str,
    defaults: ReellyDocumentAssetHydrationConfig,
) -> ConfigMapping:
    def _map_reelly_document_asset_config(config: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "ops": {
                asset_name: {
                    "config": dict(config),
                }
            }
        }

    return ConfigMapping(
        config_fn=_map_reelly_document_asset_config,
        config_schema=Permissive(
            {
                "manifest_prefix": Field(
                    StringSource,
                    default_value=defaults.manifest_prefix,
                    is_required=False,
                    description="R2 prefix containing Reelly raw manifests.",
                ),
                "target_prefix": Field(
                    StringSource,
                    default_value=defaults.target_prefix,
                    is_required=False,
                    description="R2 prefix for hydrated Reelly document assets.",
                ),
                "inventory_prefix": Field(
                    StringSource,
                    default_value=defaults.inventory_prefix,
                    is_required=False,
                    description="R2 prefix for document asset inventory manifests.",
                ),
                "max_assets_per_run": Field(
                    int,
                    default_value=defaults.max_assets_per_run,
                    is_required=False,
                    description="Maximum document rows to process in one run.",
                ),
                "overwrite_existing": Field(
                    bool,
                    default_value=defaults.overwrite_existing,
                    is_required=False,
                    description="Re-download and replace objects that already exist.",
                ),
                "allowed_document_hosts": Field(
                    [str],
                    default_value=list(defaults.allowed_document_hosts),
                    is_required=False,
                    description="Allowlisted HTTPS hosts for document downloads.",
                ),
                "max_document_mb": Field(
                    int,
                    default_value=defaults.max_document_mb,
                    is_required=False,
                    description="Maximum single document download size in MiB.",
                ),
                "request_pause_seconds": Field(
                    float,
                    default_value=defaults.request_pause_seconds,
                    is_required=False,
                    description="Pause between document download attempts.",
                ),
                "timeout_seconds": Field(
                    float,
                    default_value=defaults.timeout_seconds,
                    is_required=False,
                    description="HTTP timeout for document downloads.",
                ),
                "max_concurrent_downloads": Field(
                    int,
                    default_value=defaults.max_concurrent_downloads,
                    is_required=False,
                    description="Maximum concurrent document downloads.",
                ),
                "include_project_documents": Field(
                    bool,
                    default_value=defaults.include_project_documents,
                    is_required=False,
                    description="Read media rows from reelly_supply_project_documents.jsonl.",
                ),
                "include_project_detail_media": Field(
                    bool,
                    default_value=defaults.include_project_detail_media,
                    is_required=False,
                    description="Discover media URLs from reelly_supply_project_details.jsonl.",
                ),
                "structured_target_keys": Field(
                    bool,
                    default_value=defaults.structured_target_keys,
                    is_required=False,
                    description="Include asset_type and field_path segments in R2 target keys.",
                ),
                "inventory_file_name": Field(
                    StringSource,
                    default_value=defaults.inventory_file_name,
                    is_required=False,
                    description="Inventory manifest JSONL file name.",
                ),
                "asset_type_allowlist": Field(
                    [str],
                    default_value=list(defaults.asset_type_allowlist),
                    is_required=False,
                    description="Optional list of asset_type values to hydrate.",
                ),
            }
        ),
        receive_processed_config_values=True,
    )


def _pf_listing_media_asset_config_mapping(
    *,
    defaults: PropertyFinderListingMediaHydrationConfig,
) -> ConfigMapping:
    def _map_pf_listing_media_asset_config(config: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "ops": {
                "pf_listing_media_assets": {
                    "config": dict(config),
                }
            }
        }

    return ConfigMapping(
        config_fn=_map_pf_listing_media_asset_config,
        config_schema=Permissive(
            {
                "manifest_prefix": Field(
                    StringSource,
                    default_value=defaults.manifest_prefix,
                    is_required=False,
                    description="R2 prefix containing Property Finder raw manifests.",
                ),
                "target_prefix": Field(
                    StringSource,
                    default_value=defaults.target_prefix,
                    is_required=False,
                    description="R2 prefix for hydrated Property Finder listing media.",
                ),
                "inventory_prefix": Field(
                    StringSource,
                    default_value=defaults.inventory_prefix,
                    is_required=False,
                    description="R2 prefix for Property Finder media inventory manifests.",
                ),
                "inventory_file_name": Field(
                    StringSource,
                    default_value=defaults.inventory_file_name,
                    is_required=False,
                    description="Inventory manifest JSONL file name.",
                ),
                "max_assets_per_run": Field(
                    int,
                    default_value=defaults.max_assets_per_run,
                    is_required=False,
                    description="Maximum media assets to process in one run.",
                ),
                "overwrite_existing": Field(
                    bool,
                    default_value=defaults.overwrite_existing,
                    is_required=False,
                    description="Re-download and replace media objects that already exist.",
                ),
                "allowed_media_hosts": Field(
                    [str],
                    default_value=list(defaults.allowed_media_hosts),
                    is_required=False,
                    description="Allowlisted HTTPS hosts for Property Finder media downloads.",
                ),
                "max_media_mb": Field(
                    int,
                    default_value=defaults.max_media_mb,
                    is_required=False,
                    description="Maximum single media download size in MiB.",
                ),
                "request_pause_seconds": Field(
                    float,
                    default_value=defaults.request_pause_seconds,
                    is_required=False,
                    description="Pause between media download attempts.",
                ),
                "timeout_seconds": Field(
                    float,
                    default_value=defaults.timeout_seconds,
                    is_required=False,
                    description="HTTP timeout for media downloads.",
                ),
                "max_concurrent_downloads": Field(
                    int,
                    default_value=defaults.max_concurrent_downloads,
                    is_required=False,
                    description="Maximum concurrent media downloads.",
                ),
                "include_search_listing_media": Field(
                    bool,
                    default_value=defaults.include_search_listing_media,
                    is_required=False,
                    description="Discover media from pf_listing_properties.jsonl.",
                ),
                "include_detail_media": Field(
                    bool,
                    default_value=defaults.include_detail_media,
                    is_required=False,
                    description="Discover media from pf_listing_details.jsonl.",
                ),
                "asset_type_allowlist": Field(
                    [str],
                    default_value=list(defaults.asset_type_allowlist),
                    is_required=False,
                    description="Optional list of Property Finder media asset_type values to hydrate.",
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
