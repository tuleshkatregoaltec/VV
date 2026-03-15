"""Central registry for dataset table layout, source mode, and validation rules."""

from __future__ import annotations

from dataclasses import dataclass


FULL_SNAPSHOT = "full_snapshot"
REFERENCE_REPLACE = "reference_replace"

FULL_SWAP = "full_swap"
APPEND = "append"


@dataclass(frozen=True)
class TableSpec:
    filename: str
    table_name: str
    load_strategy: str = FULL_SWAP
    min_rows: int = 1
    unique_key: tuple[str, ...] = ()
    non_empty_columns: tuple[str, ...] = ()
    nonzero_columns: tuple[str, ...] = ()
    file_format: str = "CSVWithNames"


@dataclass(frozen=True)
class DatasetSpec:
    dataset: str
    source: str
    mode: str
    release_prefix: str
    tables: tuple[TableSpec, ...]


DLD_TABLES = (
    TableSpec(
        "transactions.csv",
        "dld_transactions",
        unique_key=("transaction_id",),
        non_empty_columns=("transaction_id",),
    ),
    TableSpec(
        "rent_contracts.csv",
        "dld_rent_contracts",
        unique_key=("contract_id", "line_number"),
        non_empty_columns=("contract_id",),
    ),
    TableSpec(
        "buildings.csv",
        "dld_buildings",
        unique_key=("property_id",),
        nonzero_columns=("property_id",),
    ),
    TableSpec(
        "units.csv",
        "dld_units",
        unique_key=("property_id",),
        nonzero_columns=("property_id",),
    ),
    TableSpec(
        "projects.csv",
        "dld_projects",
        unique_key=("project_id",),
        nonzero_columns=("project_id",),
    ),
    TableSpec(
        "developers.csv",
        "dld_developers",
        unique_key=("developer_id",),
        nonzero_columns=("developer_id",),
    ),
    TableSpec(
        "land_registry.csv",
        "dld_land_registry",
        unique_key=("property_id",),
        nonzero_columns=("property_id",),
    ),
)

GIS_TABLES = (
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
)

GEO_TABLES = (
    TableSpec(
        "building_coordinates.csv",
        "geo_buildings",
        unique_key=("address_key",),
        non_empty_columns=("address_key",),
    ),
)

DXBI_TABLES = (
    TableSpec(
        "locations.csv",
        "dxbi_locations",
        unique_key=("location_id",),
        nonzero_columns=("location_id",),
    ),
    TableSpec(
        "developers.csv",
        "dxbi_developers",
        unique_key=("developer_id",),
        nonzero_columns=("developer_id",),
    ),
)

DXBI_FUTURE_TABLES = (
    TableSpec("popular_searches.csv", "dxbi_popular_searches", load_strategy=APPEND),
    TableSpec("popular_sales_areas.csv", "dxbi_popular_sales_areas", load_strategy=APPEND),
    TableSpec("sales_transactions.csv", "dxbi_sales_transactions", load_strategy=APPEND),
    TableSpec("rental_transactions.csv", "dxbi_rental_transactions", load_strategy=APPEND),
)

DATASET_SPECS: dict[str, DatasetSpec] = {
    "dld": DatasetSpec(
        dataset="dld",
        source="dubaipulse.gov.ae",
        mode=FULL_SNAPSHOT,
        release_prefix="batch",
        tables=DLD_TABLES,
    ),
    "gis": DatasetSpec(
        dataset="gis",
        source="gis.dda.gov.ae",
        mode=FULL_SNAPSHOT,
        release_prefix="release",
        tables=GIS_TABLES,
    ),
    "geo": DatasetSpec(
        dataset="geo",
        source="geo_api_buildings",
        mode=REFERENCE_REPLACE,
        release_prefix="release",
        tables=GEO_TABLES,
    ),
    "dxbi": DatasetSpec(
        dataset="dxbi",
        source="dxbinteract.com",
        mode=REFERENCE_REPLACE,
        release_prefix="release",
        tables=DXBI_TABLES,
    ),
}


def table_by_filename(dataset: str) -> dict[str, TableSpec]:
    return {table.filename: table for table in DATASET_SPECS[dataset].tables}


def table_by_name(dataset: str) -> dict[str, TableSpec]:
    return {table.table_name: table for table in DATASET_SPECS[dataset].tables}
