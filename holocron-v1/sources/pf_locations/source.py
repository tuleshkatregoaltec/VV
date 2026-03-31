"""Property Finder locations source definition for Holocron."""

from __future__ import annotations

from pathlib import Path

from holocron.framework.models import (
    REFERENCE_REPLACE,
    SourceSpec,
    TableSpec,
    release_id_field,
    testing_limit_field,
    worker_count_field,
)
from holocron.sources.pf_locations.extract import download_all as pf_locations_download_all


def extract(
    output_dir: Path,
    *,
    release_id: str,
    config: dict,
    http,
    context,
) -> list[Path]:
    results = pf_locations_download_all(
        dest_dir=output_dir,
        run_id=release_id,
        http=http,
        max_pages_per_purpose=(
            int(config["max_pages_per_purpose"]) if config.get("max_pages_per_purpose") else None
        ),
        worker_count=int(config.get("worker_count", 8)),
        context=context,
    )
    return [result.local_path for result in results]


SOURCE = SourceSpec(
    name="pf_locations",
    provider="propertyfinder",
    source="propertyfinder.ae",
    mode=REFERENCE_REPLACE,
    description=(
        "Build a Property Finder Dubai location hierarchy from buy/rent listing location pages "
        "and persist canonical slugs, path ids, breadcrumbs, and visibility flags."
    ),
    config_schema={
        "release_id": release_id_field(""),
        "worker_count": worker_count_field(
            8,
            description="Worker count for Property Finder listing page fetches.",
        ),
        "max_pages_per_purpose": testing_limit_field(
            "Optional testing limit for generic location pages fetched per purpose sitemap."
        ),
    },
    default_config={
        "release_id": "",
        "worker_count": 8,
        "max_pages_per_purpose": None,
    },
    tables=(
        TableSpec(
            "pf_locations.csv",
            "pf_locations",
            unique_key=("pf_location_id",),
            non_empty_columns=("pf_location_id", "location_name", "slug", "path_ids"),
        ),
    ),
    extract_fn=extract,
)
