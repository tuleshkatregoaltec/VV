from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from holocron.sources import DXBI_SOURCE, registry
from holocron.sources.dxbi.extract import (
    _apply_date_slice,
    _raise_if_blocked_ajax,
    _resolve_browser_executable,
    extract_release,
    load_page_urls,
)
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


def test_resolve_browser_executable_uses_explicit_path(tmp_path: Path) -> None:
    chrome = tmp_path / "chrome"
    chrome.write_text("", encoding="utf-8")

    assert _resolve_browser_executable(str(chrome)) == str(chrome)


def test_resolve_browser_executable_raises_when_explicit_missing() -> None:
    with pytest.raises(FileNotFoundError, match="DXBI browser executable not found"):
        _resolve_browser_executable("/does/not/exist/chrome")


def test_resolve_browser_executable_falls_back_to_detected_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    detected = tmp_path / "google-chrome"
    detected.write_text("", encoding="utf-8")

    def fake_which(name: str) -> str | None:
        if name == "google-chrome":
            return str(detected)
        return None

    monkeypatch.setattr("holocron.sources.dxbi.extract.shutil.which", fake_which)

    assert _resolve_browser_executable("") == str(detected)


def test_raise_if_blocked_ajax_noop_when_all_ok() -> None:
    _raise_if_blocked_ajax(statuses=[200, 204], url="https://dxbinteract.com/")


def test_raise_if_blocked_ajax_raises_for_error_statuses() -> None:
    with pytest.raises(RuntimeError, match="HTTP 403, 429"):
        _raise_if_blocked_ajax(
            statuses=[200, 403, 429],
            url="https://dxbinteract.com/",
        )


def test_apply_date_slice_waits_for_report_refresh_not_existing_rows() -> None:
    class FakePage:
        wait_script = ""
        wait_arg = {}

        def evaluate(self, script: str, arg: list[str]) -> dict:
            assert "soldRows > 0" not in script
            return {"status": "ok", "token": "refresh-token"}

        def wait_for_function(self, script: str, *, arg: dict, timeout: int) -> None:
            self.wait_script = script
            self.wait_arg = arg
            assert timeout == 20000

        def wait_for_timeout(self, timeout: int) -> None:
            raise AssertionError(f"unexpected timeout fallback: {timeout}")

    page = FakePage()

    _apply_date_slice(
        page=page,  # type: ignore[arg-type]
        date_slice=DateSlice(start_date=date(2026, 3, 1), end_date=date(2026, 3, 3)),
    )

    assert page.wait_arg == {"token": "refresh-token"}
    assert "soldRows > 0" not in page.wait_script
    assert "rentRows > 0" not in page.wait_script
    assert "soldReady && rentReady" in page.wait_script
