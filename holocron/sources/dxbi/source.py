"""DXBI source definition for Holocron."""

from __future__ import annotations

from pathlib import Path

from holocron.framework.models import REFERENCE_REPLACE, SourceSpec, TableSpec, release_id_field
from holocron.sources.dxbi.extract import download_all as dxbi_download_all


def extract(
    output_dir: Path,
    *,
    release_id: str,
    config: dict,
    http,
    context,
) -> list[Path]:
    results = dxbi_download_all(
        dest_dir=output_dir,
        run_id=release_id,
        http=http,
        proxy=str(config.get("proxy") or ""),
        diagnostics_dir=str(config.get("diagnostics_dir") or ""),
    )
    return [result.local_path for result in results]


SOURCE = SourceSpec(
    name="dxbi_lookups",
    provider="dxbinteract",
    source="dxbinteract.com",
    mode=REFERENCE_REPLACE,
    description="Fetch DXBI lookup tables, persist the release, and publish ClickHouse tables.",
    config_schema={"release_id": release_id_field("")},
    default_config={"release_id": ""},
    tables=(
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
    ),
    extract_fn=extract,
)
