"""DLD source definition for Holocron."""

from __future__ import annotations

from pathlib import Path

from holocron.framework.models import (
    batch_id_field,
    FULL_SNAPSHOT,
    SourceSpec,
    TableSpec,
    optional_bool,
    worker_count_field,
)
from holocron.sources.dld.extract import download_all as dld_download_all


def extract(
    output_dir: Path,
    *,
    release_id: str,
    config: dict,
    http,
    context,
) -> list[Path]:
    results = dld_download_all(
        dest_dir=output_dir,
        workers=int(config.get("download_workers", 4)),
        skip_preflight=bool(config.get("skip_preflight", False)),
    )
    paths = [result.local_path for result in results if result.local_path]
    return paths


SOURCE = SourceSpec(
    name="dld",
    source="dubaipulse.gov.ae",
    mode=FULL_SNAPSHOT,
    schedule="0 6 * * *",
    description="Fetch DLD files, upload the release manifest to S3, and publish ClickHouse tables.",
    config_schema={
        "batch_id": batch_id_field(""),
        "download_workers": worker_count_field(
            4,
            description=(
                "Parallel worker count for DLD file downloads. Increase carefully if the source "
                "site remains stable."
            ),
        ),
        "skip_preflight": optional_bool(
            False,
            description=(
                "Skip the DLD availability preflight check and attempt downloads immediately."
            ),
        ),
    },
    default_config={
        "batch_id": "",
        "download_workers": 4,
        "skip_preflight": False,
    },
    tables=(
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
    ),
    extract_fn=extract,
)
