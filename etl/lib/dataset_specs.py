"""Static definitions for each dataset: filenames and ClickHouse table names."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetFile:
    filename: str
    ch_table: str           # actual ClickHouse table name
    ch_format: str = "CSVWithNames"


DLD_FILES: list[DatasetFile] = [
    DatasetFile("transactions.csv",  "ch_transactions"),
    DatasetFile("rent_contracts.csv", "ch_rent_contracts"),
    DatasetFile("buildings.csv",     "ch_buildings"),
    DatasetFile("units.csv",         "ch_units"),
    DatasetFile("projects.csv",      "ch_projects"),
    DatasetFile("developers.csv",    "ch_developers"),
    DatasetFile("land_registry.csv", "ch_land_registry"),
]

GIS_FILES: list[DatasetFile] = [
    DatasetFile("dda_plots.csv", "ch_gis_land_plots"),
]

GEO_FILES: list[DatasetFile] = [
    DatasetFile("building_coordinates.csv", "ch_geo_buildings"),
    DatasetFile("project_polygons.csv",     "ch_geo_projects"),
]

DLD_BY_FILENAME: dict[str, DatasetFile] = {f.filename: f for f in DLD_FILES}
GIS_BY_FILENAME: dict[str, DatasetFile] = {f.filename: f for f in GIS_FILES}
GEO_BY_FILENAME: dict[str, DatasetFile] = {f.filename: f for f in GEO_FILES}
