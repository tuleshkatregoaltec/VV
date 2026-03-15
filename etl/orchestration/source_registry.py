from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dagster import AssetExecutionContext, AssetSelection, AssetsDefinition, ScheduleDefinition

from etl.assets.validations import validate_dld, validate_dxbi, validate_geo, validate_gis
from etl.core.releases import ReleaseManifest
from etl.resources.clickhouse import ClickHouseResource
from etl.sources.dld.assets import DLD_TABLE_ASSETS, raw_dld_files
from etl.sources.dxbi.assets import DXBI_TABLE_ASSETS, raw_dxbi_files
from etl.sources.geo.assets import geo_buildings, raw_building_coordinates
from etl.sources.gis.assets import (
    GIS_ASSETS,
    gis_frozen_plots,
    gis_land_plots,
    gis_landuse_symbols,
    gis_plot_features,
    gis_plot_podium_limits,
    gis_project_areas,
    gis_release,
    gis_release_manifest,
    gis_subproject_areas,
    raw_gis_frozen_plots,
    raw_gis_landuse_symbols,
    raw_gis_plot_features,
    raw_gis_plots,
    raw_gis_podium_limits,
    raw_gis_project_areas,
    raw_gis_subproject_areas,
)

ValidationHook = Callable[
    [AssetExecutionContext, ClickHouseResource, ReleaseManifest], dict[str, Any]
]
RunConfigHook = Callable[[Any], dict[str, dict]]


def _merge_config_parts(parts: list[dict[str, dict]]) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for part in parts:
        merged.update(part)
    return merged


def _dld_run_config(args: Any) -> dict[str, dict]:
    if args.job in {"dld_ingest", "full_refresh"} and args.batch_id:
        return {"raw_dld_files": {"config": {"batch_id": args.batch_id}}}
    return {}


def _gis_run_config(args: Any) -> dict[str, dict]:
    if args.job not in {"gis_ingest", "gis_smoke", "full_refresh"}:
        return {}
    release_id = args.release_id or args.run_id
    config: dict[str, dict] = {}
    if release_id:
        config["gis_release"] = {"config": {"release_id": release_id}}
    plot_config: dict[str, object] = {}
    if args.max_plots is not None:
        plot_config["max_plots"] = args.max_plots
    if args.concurrency is not None:
        plot_config["concurrency"] = args.concurrency
    if plot_config:
        config["raw_gis_plots"] = {"config": plot_config}
    return config


def _dxbi_run_config(args: Any) -> dict[str, dict]:
    release_id = args.release_id or args.run_id
    if args.job in {"dxbi_ingest", "full_refresh"} and release_id:
        return {"raw_dxbi_files": {"config": {"release_id": release_id}}}
    return {}


def _geo_run_config(args: Any) -> dict[str, dict]:
    release_id = args.release_id or args.run_id
    if args.job in {"geo_enrichment", "full_refresh"} and release_id:
        return {"raw_building_coordinates": {"config": {"release_id": release_id}}}
    return {}


def _geo_validation_hook(
    context: AssetExecutionContext,
    clickhouse: ClickHouseResource,
    manifest: ReleaseManifest,
) -> dict[str, Any]:
    if manifest.dataset != "geo":
        return {}
    out_of_bounds = int(
        clickhouse.query_scalar(
            "SELECT count() FROM geo_buildings "
            "WHERE lat NOT BETWEEN 24.7 AND 25.4 OR lng NOT BETWEEN 54.8 AND 55.6"
        )
    )
    if out_of_bounds:
        raise ValueError(f"geo_buildings has {out_of_bounds} rows outside the Dubai bounding box")
    context.log.info("geo_buildings: geographic bounds validated")
    return {"geo_buildings": {"out_of_bounds": out_of_bounds}}


@dataclass(frozen=True)
class SourceSpec:
    name: str
    dataset_names: tuple[str, ...]
    asset_defs: tuple[AssetsDefinition, ...]
    validation_def: AssetsDefinition
    ingest_job_name: str
    ingest_job_description: str
    run_config_hook: RunConfigHook
    schedule_name: str | None = None
    cron_schedule: str | None = None
    validation_hook: ValidationHook | None = None
    extra_jobs: tuple[tuple[str, AssetSelection, str], ...] = ()

    @property
    def all_asset_defs(self) -> tuple[AssetsDefinition, ...]:
        return (*self.asset_defs, self.validation_def)

    @property
    def validation_asset_name(self) -> str:
        return next(iter(self.validation_def.keys)).path[-1]

    @property
    def ingest_selection(self) -> AssetSelection:
        return AssetSelection.groups(self.name) | AssetSelection.assets(self.validation_def)


DLD_SOURCE = SourceSpec(
    name="dld",
    dataset_names=("dld",),
    asset_defs=(raw_dld_files, *DLD_TABLE_ASSETS),
    validation_def=validate_dld,
    ingest_job_name="dld_ingest",
    ingest_job_description="Fetch DLD snapshot release -> S3 -> full ClickHouse swap -> validate.",
    run_config_hook=_dld_run_config,
    schedule_name="dld_daily",
    cron_schedule="0 6 * * *",
)

DXBI_SOURCE = SourceSpec(
    name="dxbi",
    dataset_names=("dxbi",),
    asset_defs=(raw_dxbi_files, *DXBI_TABLE_ASSETS),
    validation_def=validate_dxbi,
    ingest_job_name="dxbi_ingest",
    ingest_job_description="Fetch DXBI reference release -> S3 -> publish tables -> validate.",
    run_config_hook=_dxbi_run_config,
)

GIS_SOURCE = SourceSpec(
    name="gis",
    dataset_names=("gis",),
    asset_defs=tuple(GIS_ASSETS),
    validation_def=validate_gis,
    ingest_job_name="gis_ingest",
    ingest_job_description="Scrape one coherent GIS release -> S3 -> full ClickHouse swap -> validate.",
    run_config_hook=_gis_run_config,
    schedule_name="gis_weekly",
    cron_schedule="0 7 * * 1",
    extra_jobs=(
        (
            "gis_smoke",
            AssetSelection.assets(
                gis_release,
                raw_gis_plots,
                gis_land_plots,
                raw_gis_project_areas,
                gis_project_areas,
                raw_gis_subproject_areas,
                gis_subproject_areas,
                raw_gis_podium_limits,
                gis_plot_podium_limits,
                raw_gis_plot_features,
                gis_plot_features,
                raw_gis_frozen_plots,
                gis_frozen_plots,
                raw_gis_landuse_symbols,
                gis_landuse_symbols,
                gis_release_manifest,
                validate_gis,
            ),
            "Scrape a smaller GIS release slice and validate the published snapshot.",
        ),
    ),
)

GEO_SOURCE = SourceSpec(
    name="geo",
    dataset_names=("geo",),
    asset_defs=(raw_building_coordinates, geo_buildings),
    validation_def=validate_geo,
    ingest_job_name="geo_enrichment",
    ingest_job_description="Fetch geo reference release -> S3 -> publish -> validate.",
    run_config_hook=_geo_run_config,
    validation_hook=_geo_validation_hook,
)

SOURCE_SPECS = (DLD_SOURCE, DXBI_SOURCE, GIS_SOURCE, GEO_SOURCE)
SOURCE_BY_DATASET = {
    dataset_name: source for source in SOURCE_SPECS for dataset_name in source.dataset_names
}


def all_source_assets() -> list[AssetsDefinition]:
    assets: list[AssetsDefinition] = []
    for source in SOURCE_SPECS:
        assets.extend(source.all_asset_defs)
    return assets


def full_refresh_selection() -> AssetSelection:
    selections = [AssetSelection.assets(*source.all_asset_defs) for source in SOURCE_SPECS]
    selection = selections[0]
    for part in selections[1:]:
        selection = selection | part
    return selection


def registered_job_specs() -> tuple[tuple[str, AssetSelection, str], ...]:
    job_specs: list[tuple[str, AssetSelection, str]] = []
    for source in SOURCE_SPECS:
        job_specs.append(
            (source.ingest_job_name, source.ingest_selection, source.ingest_job_description)
        )
        job_specs.extend(source.extra_jobs)
    job_specs.append(
        (
            "full_refresh",
            full_refresh_selection(),
            "Run dataset release pipelines and validations across all registered sources.",
        )
    )
    return tuple(job_specs)


def registered_job_names() -> tuple[str, ...]:
    return tuple(job_name for job_name, _, _ in registered_job_specs())


def schedule_defs_by_job_name(jobs_by_name: dict[str, Any]) -> list[ScheduleDefinition]:
    schedules: list[ScheduleDefinition] = []
    for source in SOURCE_SPECS:
        if source.schedule_name and source.cron_schedule:
            schedules.append(
                ScheduleDefinition(
                    job=jobs_by_name[source.ingest_job_name],
                    cron_schedule=source.cron_schedule,
                    name=source.schedule_name,
                )
            )
    return schedules


def run_config_for_args(args: Any) -> dict[str, dict]:
    return _merge_config_parts([source.run_config_hook(args) for source in SOURCE_SPECS])


def validation_hook_for_dataset(dataset: str) -> ValidationHook | None:
    source = SOURCE_BY_DATASET.get(dataset)
    return source.validation_hook if source else None
