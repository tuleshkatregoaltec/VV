from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from holocron.sources import DXBI_SOURCE, registry
from holocron.sources.dxbi.extract import extract_release, load_page_urls
from holocron.sources.dxbi.source import DateSlice, DxbiConfig, build_date_slices


def test_dxbi_source_is_registered() -> None:
    assert registry.get("dxbi_transactions") is DXBI_SOURCE


def test_incremental_date_slices_use_lookback_window() -> None:
    config = DxbiConfig(mode="incremental", lookback_days=2, slice_days=2)

    slices = build_date_slices(config, today=date(2026, 3, 31))

    assert slices == (
        DateSlice(start_date=date(2026, 3, 29), end_date=date(2026, 3, 30)),
        DateSlice(start_date=date(2026, 3, 31), end_date=date(2026, 3, 31)),
    )


def test_backfill_requires_explicit_dates() -> None:
    with pytest.raises(ValueError, match="start_date and end_date"):
        DxbiConfig(mode="backfill")


def test_load_page_urls_defaults_and_dedupes() -> None:
    urls = load_page_urls(
        page_urls_text="https://dxbinteract.com/\nhttps://dxbinteract.com/projects/a",
        page_urls_file="",
    )

    assert urls == ["https://dxbinteract.com/", "https://dxbinteract.com/projects/a"]


def test_extract_release_writes_one_jsonl_file_per_slice(tmp_path: Path) -> None:
    config = DxbiConfig(
        mode="backfill",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 3),
        slice_days=2,
    )

    def page_scraper(**kwargs):
        date_slice = kwargs["date_slice"]
        return [
            {
                "table": "sales",
                "cells": ["row"],
                "_slice_start_date": date_slice.start_date.isoformat(),
                "_slice_end_date": date_slice.end_date.isoformat(),
            }
        ]

    release = extract_release(
        tmp_path,
        config=config,
        now=datetime(2026, 3, 31, 8, 0, tzinfo=UTC),
        page_scraper=page_scraper,
    )

    assert release.run_id == "2026-03-31T08-00-00Z"
    assert len(release.files) == 2
    assert all(file.path.endswith(".jsonl") for file in release.files)
