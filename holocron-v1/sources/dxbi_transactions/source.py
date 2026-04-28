"""DXBI transactions source definition for Holocron."""

from __future__ import annotations

from pathlib import Path

from holocron.framework.models import (
    APPEND,
    REFERENCE_REPLACE,
    SourceSpec,
    TableSpec,
    optional_int,
    optional_str,
    release_id_field,
)
from holocron.sources.dxbi_transactions.extract import (
    download_all as dxbi_transactions_download_all,
)


def extract(
    output_dir: Path,
    *,
    release_id: str,
    config: dict,
    http,
    context,
) -> list[Path]:
    results = dxbi_transactions_download_all(
        dest_dir=output_dir,
        run_id=release_id,
        page_urls_text=str(config.get("page_urls") or ""),
        page_urls_file=str(config.get("page_urls_file") or ""),
        storage_state_path=str(config.get("storage_state_path") or ""),
        chrome_path=str(config.get("chrome_path") or ""),
        proxy=str(config.get("proxy") or ""),
        diagnostics_dir=str(config.get("diagnostics_dir") or ""),
        max_pages=int(config["max_pages"]) if config.get("max_pages") else None,
        context=context,
    )
    return [result.local_path for result in results]


SOURCE = SourceSpec(
    name="dxbi_transactions",
    provider="dxbinteract",
    source="dxbinteract.com",
    mode=REFERENCE_REPLACE,
    description=(
        "Fetch DXB Interact transaction and rental history tables from supplied DXBI pages "
        "through a browser-backed session and append normalized rows to ClickHouse."
    ),
    config_schema={
        "release_id": release_id_field(""),
        "page_urls": optional_str(
            "",
            description=(
                "Newline-delimited DXBI page URLs to scrape. Each page may contribute sale "
                "history, rent history, or both. If omitted, Holocron defaults to the DXBI "
                "home transactions page and paginates it automatically."
            ),
        ),
        "page_urls_file": optional_str(
            "",
            description=(
                "Optional local text file containing one DXBI page URL per line. Used in "
                "addition to page_urls."
            ),
        ),
        "storage_state_path": optional_str(
            "",
            description=(
                "Optional Playwright storage-state JSON captured from a browser session that "
                "has already passed DXBI Cloudflare checks. Usually not required when a local "
                "Chrome/Chromium binary can clear the challenge automatically."
            ),
        ),
        "chrome_path": optional_str(
            "",
            description=(
                "Optional path to a Chrome/Chromium executable for DXBI browser fetches. "
                "DXBI automation works best with a real local Chrome-family binary."
            ),
        ),
        "max_pages": optional_int(
            None,
            description="Optional cap on the number of supplied DXBI pages visited.",
        ),
    },
    default_config={
        "release_id": "",
        "page_urls": "",
        "page_urls_file": "",
        "storage_state_path": "",
        "chrome_path": "",
        "max_pages": None,
    },
    tables=(
        TableSpec(
            "sales.csv",
            "dxbi_sale_transactions",
            load_strategy=APPEND,
            min_rows=0,
            unique_key=("transaction_key",),
            non_empty_columns=("transaction_key", "source_page"),
        ),
        TableSpec(
            "rentals.csv",
            "dxbi_rental_transactions",
            load_strategy=APPEND,
            min_rows=0,
            unique_key=("transaction_key",),
            non_empty_columns=("transaction_key", "source_page"),
        ),
    ),
    extract_fn=extract,
)
