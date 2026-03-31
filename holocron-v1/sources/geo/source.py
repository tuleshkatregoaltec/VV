"""Geo source definition for Holocron."""

from __future__ import annotations

import os
from pathlib import Path

from holocron.framework.models import (
    CheckOutcome,
    REFERENCE_REPLACE,
    ReleaseManifest,
    SourceSpec,
    TableSpec,
    release_id_field,
)


def extract(
    output_dir: Path,
    *,
    release_id: str,
    config: dict,
    http,
    context,
) -> list[Path]:
    url = os.environ.get("GEO_BUILDINGS_URL", "")
    if not url:
        raise NotImplementedError("GEO_BUILDINGS_URL not set.")
    path = output_dir / "building_coordinates.csv"
    response = http.get(url)
    path.write_bytes(response.content)
    return [path]


def extra_checks(context, clickhouse, manifest: ReleaseManifest, table_spec: TableSpec):
    if table_spec.table_name != "geo_buildings":
        return []
    out_of_bounds = int(
        clickhouse.query_scalar(
            "SELECT count() FROM geo_buildings "
            "WHERE lat NOT BETWEEN 24.7 AND 25.4 OR lng NOT BETWEEN 54.8 AND 55.6"
        )
    )
    return [
        CheckOutcome(
            name="dubai_bounds",
            passed=out_of_bounds == 0,
            metadata={"out_of_bounds": out_of_bounds},
            description="All geo building coordinates fall within the Dubai bounding box",
        )
    ]


SOURCE = SourceSpec(
    name="geo_buildings",
    provider="geo_api",
    source="geo_api_buildings",
    mode=REFERENCE_REPLACE,
    description="Fetch geo building coordinates and publish the reference table to ClickHouse.",
    config_schema={"release_id": release_id_field("")},
    default_config={"release_id": ""},
    tables=(
        TableSpec(
            "building_coordinates.csv",
            "geo_buildings",
            unique_key=("address_key",),
            non_empty_columns=("address_key",),
        ),
    ),
    extract_fn=extract,
    extra_check_names={"geo_buildings": ("dubai_bounds",)},
    extra_checks_fn=extra_checks,
)
