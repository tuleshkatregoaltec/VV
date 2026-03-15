"""GIS release assets."""

import asyncio
import tempfile
import time
from pathlib import Path

from dagster import AssetExecutionContext, AssetIn, AssetKey, Config, Output, asset

from etl.core.dataset_registry import DATASET_SPECS, table_by_filename
from etl.core.load_strategies import load_table_from_release
from etl.core.releases import ReleaseManifest, build_file_artifact, new_release_id, utc_now_iso
from etl.lib.paths import gis_manifest_key, gis_raw_key
from etl.lib.scrapers.dda_gis import (
    scrape as scrape_dda_plots,
    scrape_building_limits,
    scrape_frozen_plots,
    scrape_landuse_symbols,
    scrape_plot_arcades,
    scrape_plot_built_to_lines,
    scrape_plot_features,
    scrape_plot_retail,
    scrape_podium_limits,
    scrape_project_areas,
    scrape_subproject_areas,
)
from etl.resources.clickhouse import ClickHouseResource
from etl.resources.s3 import S3Resource


class GISReleaseConfig(Config):
    release_id: str = ""


class GISPlotsConfig(Config):
    concurrency: int = 15
    max_plots: int | None = None


_GIS_SPEC = DATASET_SPECS["gis"]
_GIS_BY_FILENAME = table_by_filename("gis")


def _run_scrape_with_retries(scrape_call, log, label: str, attempts: int = 3) -> None:
    for attempt in range(1, attempts + 1):
        try:
            scrape_call()
            return
        except Exception:
            if attempt == attempts:
                raise
            log.warning(f"{label} failed on attempt {attempt}/{attempts}; retrying")
            time.sleep(2**attempt)


@asset(group_name="gis")
def gis_release(context: AssetExecutionContext, config: GISReleaseConfig) -> Output[dict]:
    release_id = config.release_id or new_release_id()
    context.log.info(f"GIS shared release_id={release_id}")
    return Output(
        value={
            "dataset": _GIS_SPEC.dataset,
            "release_id": release_id,
            "mode": _GIS_SPEC.mode,
            "source": _GIS_SPEC.source,
            "created_at": utc_now_iso(),
        },
        metadata={"release_id": release_id},
    )


@asset(group_name="gis")
def raw_gis_plots(
    context: AssetExecutionContext,
    gis_release: dict,
    config: GISPlotsConfig,
    s3: S3Resource,
) -> Output[dict]:
    release_id = gis_release["release_id"]
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "dda_plots.csv"
        _run_scrape_with_retries(
            lambda: asyncio.run(
                scrape_dda_plots(
                    output=output,
                    concurrency=config.concurrency,
                    max_plots=config.max_plots,
                )
            ),
            context.log,
            "GIS plots scrape",
        )
        s3_key = gis_raw_key(release_id, output.name)
        s3.upload_file(output, s3_key)
        artifact = build_file_artifact(output, s3_key=s3_key, table_name="gis_land_plots")
    return Output(
        value={"release_id": release_id, **artifact.model_dump(mode="json")},
        metadata={"release_id": release_id},
    )


def _make_raw_gis_layer_asset(
    asset_name: str, filename: str, scrape_fn, log_label: str, table_name: str
):
    @asset(name=asset_name, group_name="gis")
    def _asset(
        context: AssetExecutionContext,
        gis_release: dict,
        s3: S3Resource,
    ) -> Output[dict]:
        release_id = gis_release["release_id"]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / filename
            _run_scrape_with_retries(
                lambda: asyncio.run(scrape_fn(output=output)),
                context.log,
                f"GIS {log_label} scrape",
            )
            s3_key = gis_raw_key(release_id, filename)
            s3.upload_file(output, s3_key)
            artifact = build_file_artifact(output, s3_key=s3_key, table_name=table_name)
        return Output(
            value={"release_id": release_id, **artifact.model_dump(mode="json")},
            metadata={"release_id": release_id},
        )

    return _asset


def _make_gis_table_asset(asset_name: str, raw_asset_name: str, filename: str, table_name: str):
    table_spec = _GIS_BY_FILENAME[filename]

    @asset(
        name=asset_name,
        group_name="gis",
        ins={"raw_layer": AssetIn(key=AssetKey([raw_asset_name]))},
    )
    def _asset(
        context: AssetExecutionContext,
        raw_layer: dict,
        s3: S3Resource,
        clickhouse: ClickHouseResource,
    ) -> Output[int]:
        release_id = raw_layer["release_id"]
        count = load_table_from_release(
            clickhouse=clickhouse,
            s3=s3,
            table_spec=table_spec,
            s3_key=gis_raw_key(release_id, filename),
            release_id=release_id,
        )
        return Output(value=count, metadata={"row_count": count, "release_id": release_id})

    return _asset


gis_land_plots = _make_gis_table_asset(
    "gis_land_plots", "raw_gis_plots", "dda_plots.csv", "gis_land_plots"
)


raw_gis_project_areas = _make_raw_gis_layer_asset(
    "raw_gis_project_areas",
    "project_areas.csv",
    scrape_project_areas,
    "project areas",
    "gis_project_areas",
)
gis_project_areas = _make_gis_table_asset(
    "gis_project_areas", "raw_gis_project_areas", "project_areas.csv", "gis_project_areas"
)

raw_gis_subproject_areas = _make_raw_gis_layer_asset(
    "raw_gis_subproject_areas",
    "subproject_areas.csv",
    scrape_subproject_areas,
    "subproject areas",
    "gis_subproject_areas",
)
gis_subproject_areas = _make_gis_table_asset(
    "gis_subproject_areas",
    "raw_gis_subproject_areas",
    "subproject_areas.csv",
    "gis_subproject_areas",
)

raw_gis_building_limits = _make_raw_gis_layer_asset(
    "raw_gis_building_limits",
    "plot_building_limits.csv",
    scrape_building_limits,
    "building limits",
    "gis_plot_building_limits",
)
gis_plot_building_limits = _make_gis_table_asset(
    "gis_plot_building_limits",
    "raw_gis_building_limits",
    "plot_building_limits.csv",
    "gis_plot_building_limits",
)

raw_gis_podium_limits = _make_raw_gis_layer_asset(
    "raw_gis_podium_limits",
    "plot_podium_limits.csv",
    scrape_podium_limits,
    "podium limits",
    "gis_plot_podium_limits",
)
gis_plot_podium_limits = _make_gis_table_asset(
    "gis_plot_podium_limits",
    "raw_gis_podium_limits",
    "plot_podium_limits.csv",
    "gis_plot_podium_limits",
)

raw_gis_plot_features = _make_raw_gis_layer_asset(
    "raw_gis_plot_features",
    "plot_features.csv",
    scrape_plot_features,
    "plot features",
    "gis_plot_features",
)
gis_plot_features = _make_gis_table_asset(
    "gis_plot_features", "raw_gis_plot_features", "plot_features.csv", "gis_plot_features"
)

raw_gis_frozen_plots = _make_raw_gis_layer_asset(
    "raw_gis_frozen_plots",
    "frozen_plots.csv",
    scrape_frozen_plots,
    "frozen plots",
    "gis_frozen_plots",
)
gis_frozen_plots = _make_gis_table_asset(
    "gis_frozen_plots", "raw_gis_frozen_plots", "frozen_plots.csv", "gis_frozen_plots"
)

raw_gis_landuse_symbols = _make_raw_gis_layer_asset(
    "raw_gis_landuse_symbols",
    "landuse_symbols.csv",
    scrape_landuse_symbols,
    "land-use symbols",
    "gis_landuse_symbols",
)
gis_landuse_symbols = _make_gis_table_asset(
    "gis_landuse_symbols", "raw_gis_landuse_symbols", "landuse_symbols.csv", "gis_landuse_symbols"
)

raw_gis_plot_built_to_lines = _make_raw_gis_layer_asset(
    "raw_gis_plot_built_to_lines",
    "plot_built_to_lines.csv",
    scrape_plot_built_to_lines,
    "built-to-lines",
    "gis_plot_built_to_lines",
)
gis_plot_built_to_lines = _make_gis_table_asset(
    "gis_plot_built_to_lines",
    "raw_gis_plot_built_to_lines",
    "plot_built_to_lines.csv",
    "gis_plot_built_to_lines",
)

raw_gis_plot_arcades = _make_raw_gis_layer_asset(
    "raw_gis_plot_arcades",
    "plot_arcades.csv",
    scrape_plot_arcades,
    "arcades",
    "gis_plot_arcades",
)
gis_plot_arcades = _make_gis_table_asset(
    "gis_plot_arcades", "raw_gis_plot_arcades", "plot_arcades.csv", "gis_plot_arcades"
)

raw_gis_plot_retail = _make_raw_gis_layer_asset(
    "raw_gis_plot_retail",
    "plot_retail.csv",
    scrape_plot_retail,
    "retail areas",
    "gis_plot_retail",
)
gis_plot_retail = _make_gis_table_asset(
    "gis_plot_retail", "raw_gis_plot_retail", "plot_retail.csv", "gis_plot_retail"
)


@asset(group_name="gis")
def gis_release_manifest(
    context: AssetExecutionContext,
    gis_release: dict,
    raw_gis_plots: dict,
    raw_gis_project_areas: dict,
    raw_gis_subproject_areas: dict,
    raw_gis_building_limits: dict,
    raw_gis_podium_limits: dict,
    raw_gis_plot_features: dict,
    raw_gis_frozen_plots: dict,
    raw_gis_landuse_symbols: dict,
    raw_gis_plot_built_to_lines: dict,
    raw_gis_plot_arcades: dict,
    raw_gis_plot_retail: dict,
    s3: S3Resource,
) -> Output[dict]:
    files = [
        raw_gis_plots,
        raw_gis_project_areas,
        raw_gis_subproject_areas,
        raw_gis_building_limits,
        raw_gis_podium_limits,
        raw_gis_plot_features,
        raw_gis_frozen_plots,
        raw_gis_landuse_symbols,
        raw_gis_plot_built_to_lines,
        raw_gis_plot_arcades,
        raw_gis_plot_retail,
    ]
    manifest = ReleaseManifest(
        dataset=gis_release["dataset"],
        release_id=gis_release["release_id"],
        mode=gis_release["mode"],
        source=gis_release["source"],
        created_at=gis_release["created_at"],
        files=files,
    )
    s3.put_json(gis_manifest_key(gis_release["release_id"]), manifest.to_json())
    context.log.info(f"Wrote GIS release manifest with {len(files)} files")
    return Output(
        value=manifest.model_dump(mode="json"), metadata={"release_id": gis_release["release_id"]}
    )


GIS_ASSETS = [
    gis_release,
    raw_gis_plots,
    gis_land_plots,
    raw_gis_project_areas,
    gis_project_areas,
    raw_gis_subproject_areas,
    gis_subproject_areas,
    raw_gis_building_limits,
    gis_plot_building_limits,
    raw_gis_podium_limits,
    gis_plot_podium_limits,
    raw_gis_plot_features,
    gis_plot_features,
    raw_gis_frozen_plots,
    gis_frozen_plots,
    raw_gis_landuse_symbols,
    gis_landuse_symbols,
    raw_gis_plot_built_to_lines,
    gis_plot_built_to_lines,
    raw_gis_plot_arcades,
    gis_plot_arcades,
    raw_gis_plot_retail,
    gis_plot_retail,
    gis_release_manifest,
]
