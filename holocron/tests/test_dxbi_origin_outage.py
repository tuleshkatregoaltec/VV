"""DXBI's origin goes down nightly at about 01:00 UTC and Cloudflare answers 520.

From 2026-10-30 every nightly rentals run reached that window and died on the first 520, so
lease data stopped at 2026-10-29. These tests pin the recovery: wait out the outage politely,
start a fresh session, and finish the day instead of losing the night.
"""

import importlib.util
import json
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

HOLOCRON = Path(__file__).parents[1]


def _load(relative: str, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, HOLOCRON / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scraper() -> ModuleType:
    return _load("scripts/dxbi_rental_backfill.py", "dxbi_rental_backfill_outage")


def _legacy() -> ModuleType:
    return _load("deploy/ph-box-rentals/dxbi_rental_backfill_legacy.py", "dxbi_legacy_outage")


def _configuration() -> dict:
    return {
        "manifest_version": 2,
        "manifest_hash": "manifest",
        "report_type": "rentals",
        "account": "account-b",
        "profile_id": "broad",
        "profile_label": "All",
        "location_id": "1",
        "location_text": "Dubai",
        "location_slug": "dubai",
        "filters": {"P74_DEAL": "RENT"},
        "configuration_hash": "12345678901234567890",
    }


class _Context:
    def storage_state(self, path: Path) -> None:
        pass


def _ok() -> dict:
    return {"status": 200, "login_redirect": False, "rows": [], "error": ""}


def _down() -> dict:
    return {"status": 520, "login_redirect": False, "rows": [], "error": ""}


def _run(scraper: ModuleType, tmp_path: Path, days: list[date], outage_wait_seconds: float):
    return scraper.scrape_configuration(
        page=object(),
        context=_Context(),
        credentials={},
        storage_path=tmp_path / "state.json",
        output_dir=tmp_path,
        configuration=_configuration(),
        dates=days,
        direction="asc",
        template_date="2026-06-30",
        report=scraper.REPORTS["rentals"],
        delay_min=0,
        delay_max=0,
        request_limit=None,
        outage_wait_seconds=outage_wait_seconds,
    )


@pytest.mark.parametrize("loader", [_scraper, _legacy])
def test_outage_probes_back_off_to_five_minutes_within_the_budget(loader) -> None:
    delays = loader().outage_probe_delays(90 * 60)

    assert delays[:4] == [60, 120, 240, 300]
    assert max(delays) == 300  # never more than one probe per five minutes...
    assert sum(delays) <= 90 * 60  # ...and never past the budget
    assert sum(delays) > 90 * 60 - 300


@pytest.mark.parametrize("loader", [_scraper, _legacy])
def test_wait_stops_at_the_first_answer_from_the_origin(loader) -> None:
    module = loader()
    answers = iter([_down(), {"status": 500, "login_redirect": False, "rows": [], "error": ""}])
    slept: list[float] = []

    response = module.wait_out_origin_outage(
        "2026-11-08|0|||", _down(), lambda: next(answers), [60, 120, 240], slept.append
    )

    # A 500 is the slice's problem, not an outage: hand it back for normal failure handling.
    assert response["status"] == 500
    assert slept == [60, 120]


def test_nightly_outage_is_waited_out_and_the_day_completes(monkeypatch, tmp_path: Path) -> None:
    scraper = _scraper()
    responses = iter([_down(), _down(), _ok()])
    logins: list[int] = []
    slept: list[float] = []
    monkeypatch.setattr(scraper, "capture_template", lambda *args, **kwargs: {})
    monkeypatch.setattr(scraper, "login", lambda *args, **kwargs: logins.append(1))
    monkeypatch.setattr(scraper, "fetch_rows", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(scraper.time, "sleep", slept.append)

    status, requests = _run(scraper, tmp_path, [date(2026, 11, 8)], 90 * 60)

    assert status == "complete"
    assert requests == 3
    assert len(logins) == 2  # a fresh session after each wait
    assert [delay for delay in slept if delay >= 60] == [60, 120]
    state = json.loads(next((tmp_path / "checkpoints").glob("*.json")).read_text())
    assert state["partitions"]["2026-11-08"]["status"] == "complete"


def test_outage_past_the_budget_fails_the_remaining_days_fast(monkeypatch, tmp_path: Path) -> None:
    scraper = _scraper()
    calls: list[int] = []

    def always_down(*args, **kwargs) -> dict:
        calls.append(1)
        return _down()

    monkeypatch.setattr(scraper, "capture_template", lambda *args, **kwargs: {})
    monkeypatch.setattr(scraper, "login", lambda *args, **kwargs: None)
    monkeypatch.setattr(scraper, "fetch_rows", always_down)
    monkeypatch.setattr(scraper.time, "sleep", lambda _: None)

    status, _ = _run(scraper, tmp_path, [date(2026, 11, 7), date(2026, 11, 8)], 7 * 60)

    assert status == "failed"
    # Day one: first request plus one probe per delay (60, 120, 240). Day two: one request,
    # no second wait.
    assert len(calls) == 1 + 3 + 1
    state = json.loads(next((tmp_path / "checkpoints").glob("*.json")).read_text())
    assert state["partitions"]["2026-11-07"]["status"] == "failed"
    assert state["partitions"]["2026-11-08"]["status"] == "failed"
