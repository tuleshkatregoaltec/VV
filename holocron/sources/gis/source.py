"""GIS source definition for Holocron."""

from __future__ import annotations

import time
from pathlib import Path

from holocron.framework.models import (
    FULL_SNAPSHOT,
    SourceSpec,
    TableSpec,
    release_id_field,
    testing_limit_field,
    worker_count_field,
)
from holocron.sources.gis.extract import scrape_all_layers


def _run_with_retries(label: str, fn, *, attempts: int = 3, log=None) -> None:
    for attempt in range(1, attempts + 1):
        try:
            if log is not None:
                log.info(f"{label}: extract attempt {attempt}/{attempts}")
            fn()
            return
        except Exception as exc:
            if attempt == attempts:
                raise
            if log is not None:
                log.warning(f"{label}: extract attempt {attempt}/{attempts} failed: {exc!r}")
            time.sleep(2**attempt)


def extract(
    output_dir: Path,
    *,
    release_id: str,
    config: dict,
    http,
    context,
) -> list[Path]:
    concurrency = int(config.get("concurrency", 20))
    max_plots = config.get("max_plots")
    _run_with_retries(
        "gis",
        lambda: scrape_all_layers(output_dir, concurrency, max_plots),
        log=context.log,
    )
    return sorted(output_dir.glob("*.csv"))


SOURCE = SourceSpec(
    name="gis",
    source="gis.dda.gov.ae",
    mode=FULL_SNAPSHOT,
    schedule="0 7 * * 1",
    description="Scrape GIS release files, upload them to S3, and publish ClickHouse tables.",
    config_schema={
        "release_id": release_id_field(""),
        "concurrency": worker_count_field(
            20,
            description=(
                "Worker count for GIS plot-detail requests. Higher values can speed up scraping "
                "but may increase timeout or WAF risk."
            ),
        ),
        "max_plots": testing_limit_field(
            "Optional testing limit for GIS plot-detail scraping. Leave empty for a full release."
        ),
    },
    default_config={"release_id": "", "concurrency": 20, "max_plots": None},
    tables=(
        TableSpec(
            "dda_plots.csv",
            "gis_land_plots",
            unique_key=("plot_number",),
            non_empty_columns=("plot_number",),
        ),
        TableSpec(
            "project_areas.csv",
            "gis_project_areas",
            unique_key=("object_id",),
            nonzero_columns=("object_id",),
        ),
        TableSpec(
            "subproject_areas.csv",
            "gis_subproject_areas",
            unique_key=("object_id",),
            nonzero_columns=("object_id",),
        ),
        TableSpec(
            "plot_building_limits.csv",
            "gis_plot_building_limits",
            unique_key=("object_id",),
            nonzero_columns=("object_id",),
        ),
        TableSpec(
            "plot_podium_limits.csv",
            "gis_plot_podium_limits",
            unique_key=("object_id",),
            nonzero_columns=("object_id",),
        ),
        TableSpec(
            "plot_features.csv",
            "gis_plot_features",
            unique_key=("object_id",),
            nonzero_columns=("object_id",),
        ),
        TableSpec(
            "frozen_plots.csv",
            "gis_frozen_plots",
            unique_key=("object_id",),
            nonzero_columns=("object_id",),
        ),
        TableSpec(
            "landuse_symbols.csv",
            "gis_landuse_symbols",
            unique_key=("object_id",),
            nonzero_columns=("object_id",),
        ),
        TableSpec(
            "plot_built_to_lines.csv",
            "gis_plot_built_to_lines",
            unique_key=("object_id",),
            nonzero_columns=("object_id",),
        ),
        TableSpec(
            "plot_arcades.csv",
            "gis_plot_arcades",
            unique_key=("object_id",),
            nonzero_columns=("object_id",),
        ),
        TableSpec(
            "plot_retail.csv",
            "gis_plot_retail",
            unique_key=("object_id",),
            nonzero_columns=("object_id",),
        ),
    ),
    extract_fn=extract,
)
