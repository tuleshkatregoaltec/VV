from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from holocron.contracts import BronzeTable, SourceSpec

DDA_SOURCE_NAME = "dda_planning_layers"
DDA_PROVIDER = "dda"


class DdaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concurrency: int = Field(default=20, ge=1)
    max_plots: int | None = Field(default=None, ge=1)


def extract_release(*args, **kwargs):
    from holocron.sources.dda.extract import extract_release as run_extract_release

    return run_extract_release(*args, **kwargs)


def load_bronze(*args, **kwargs):
    from holocron.sources.dda.bronze import load_release_to_clickhouse

    return load_release_to_clickhouse(*args, **kwargs)


SOURCE = SourceSpec(
    name=DDA_SOURCE_NAME,
    provider=DDA_PROVIDER,
    extractor=extract_release,
    bronze_loader=load_bronze,
    bronze_tables=(
        BronzeTable(name="dda_land_plots"),
        BronzeTable(name="dda_project_areas"),
        BronzeTable(name="dda_subproject_areas"),
        BronzeTable(name="dda_plot_building_limits"),
        BronzeTable(name="dda_plot_podium_limits"),
        BronzeTable(name="dda_plot_features"),
        BronzeTable(name="dda_frozen_plots"),
        BronzeTable(name="dda_landuse_symbols"),
        BronzeTable(name="dda_plot_built_to_lines"),
        BronzeTable(name="dda_plot_arcades"),
        BronzeTable(name="dda_plot_retail"),
    ),
    checkpoint_strategy="full_refresh",
    cadence="0 7 * * 1",
    description="DDA planning map extraction into immutable raw CSV releases.",
)
