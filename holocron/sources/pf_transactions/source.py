"""Property Finder transactions source definition for Holocron."""

from __future__ import annotations

from pathlib import Path

from holocron.framework.models import (
    APPEND,
    REFERENCE_REPLACE,
    SourceSpec,
    TableSpec,
    optional_str,
    release_id_field,
    testing_limit_field,
    worker_count_field,
)
from holocron.sources.pf_transactions.extract import download_all as pf_transactions_download_all


def extract(
    output_dir: Path,
    *,
    release_id: str,
    config: dict,
    http,
    context,
) -> list[Path]:
    results = pf_transactions_download_all(
        dest_dir=output_dir,
        run_id=release_id,
        http=http,
        period=str(config.get("period") or "3y"),
        max_listing_pages_per_purpose=(
            int(config["max_listing_pages_per_purpose"])
            if config.get("max_listing_pages_per_purpose")
            else None
        ),
        max_nodes_per_purpose=(
            int(config["max_nodes_per_purpose"]) if config.get("max_nodes_per_purpose") else None
        ),
        worker_count=int(config.get("worker_count", 8)),
        context=context,
    )
    return [result.local_path for result in results]


SOURCE = SourceSpec(
    name="pf_transactions",
    provider="propertyfinder",
    source="propertyfinder.ae",
    mode=REFERENCE_REPLACE,
    schedule="0 10 * * *",
    description=(
        "Traverse the Property Finder Dubai transaction hierarchy, recover buy and rent "
        "transaction rows where the public page cap allows it, and publish coverage metadata."
    ),
    config_schema={
        "release_id": release_id_field(""),
        "period": optional_str(
            "3y",
            description=(
                "Public Property Finder transaction period. Supported public values observed on "
                "the site include ytd, 1w, 1m, 3m, 6m, 1y, and 3y."
            ),
        ),
        "worker_count": worker_count_field(
            8,
            description="Worker count for Property Finder listing-page discovery fetches.",
        ),
        "max_listing_pages_per_purpose": testing_limit_field(
            "Optional testing limit for Dubai listing location pages scanned per purpose."
        ),
        "max_nodes_per_purpose": testing_limit_field(
            "Optional testing limit for transaction-visible nodes visited per purpose."
        ),
    },
    default_config={
        "release_id": "",
        "period": "3y",
        "worker_count": 8,
        "max_listing_pages_per_purpose": None,
        "max_nodes_per_purpose": None,
    },
    tables=(
        TableSpec(
            "sales.csv",
            "pf_sale_transactions",
            load_strategy=APPEND,
            min_rows=0,
            unique_key=("pf_transaction_id",),
            non_empty_columns=(
                "pf_transaction_id",
                "transaction_date",
                "propertyfinder_location_id",
            ),
        ),
        TableSpec(
            "rentals.csv",
            "pf_rental_transactions",
            load_strategy=APPEND,
            min_rows=0,
            unique_key=("pf_transaction_id",),
            non_empty_columns=(
                "pf_transaction_id",
                "transaction_date",
                "propertyfinder_location_id",
            ),
        ),
        TableSpec(
            "coverage.csv",
            "pf_transaction_coverage",
            min_rows=0,
            unique_key=("purpose", "pf_location_id"),
            non_empty_columns=("purpose", "pf_location_id", "strategy"),
        ),
    ),
    extract_fn=extract,
)
