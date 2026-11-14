import json
import os
import time
from datetime import date
from pathlib import Path

import pytest

from holocron.platform import sync_dxbi_to_warehouse as sync


def _run(root: Path, kind: str, name: str, days: list[str], *, success: bool = True) -> Path:
    run = root / kind / name
    run.mkdir(parents=True)
    completed = {f"{day}|0|12500.00||": {"rows": 1, "path": ""} for day in days}
    (run / "checkpoint.json").write_text(json.dumps({"completed": completed, "failed": {}}))
    if success:
        (run / "_SUCCESS").touch()
    return run


class Recorder:
    """Stands in for subprocess, the release build and the cache flush."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.calls: list[str] = []
        self.commands: list[list[str]] = []
        self.fail_on = fail_on

    def command(self, argv: list[str]) -> int:
        self.commands.append(argv)
        script = next(part for part in argv if part.endswith(".py"))
        name = Path(script).name
        self.calls.append(f"{name}:{Path(argv[argv.index(script) + 1]).name}")
        return 1 if self.fail_on and self.fail_on in self.calls[-1] else 0

    def release(self) -> None:
        self.calls.append("release")
        if self.fail_on == "release":
            raise RuntimeError("release failed")

    def flush(self) -> None:
        self.calls.append("flush")


def _config(tmp_path: Path) -> sync.Config:
    return sync.Config(
        evidence_dir=tmp_path / "evidence",
        state_dir=tmp_path / "state",
        python="python",
        scripts_dir=Path("scripts"),
    )


def _go(config: sync.Config, recorder: Recorder) -> int:
    return sync.run_sync(
        config,
        run_command=recorder.command,
        build_release=recorder.release,
        flush_cache=recorder.flush,
    )


def test_a_run_without_success_is_never_listed(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    _run(root, "rentals", "run=2026-11-05", ["2026-11-01", "2026-11-05"], success=False)
    _run(root, "rentals", "run=2026-11-06", ["2026-11-02", "2026-11-06"])
    names = [run.name for run in sync.discover_runs(root, "rentals")]
    assert names == ["run=2026-11-06"]


def test_a_runs_window_is_the_dates_its_checkpoint_covers(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    _run(root, "sales", "run=2026-11-14", ["2026-11-10", "2026-11-07", "2026-11-14"])
    (run,) = sync.discover_runs(root, "sales")
    assert (run.first, run.last) == (date(2026, 11, 7), date(2026, 11, 14))


def test_a_successful_run_without_a_readable_checkpoint_is_an_error(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    run = _run(root, "sales", "run=2026-11-14", [])
    with pytest.raises(sync.RunError):
        sync.discover_runs(root, "sales")
    assert run.exists()


def test_other_directories_next_to_runs_are_ignored(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    _run(root, "sales", "run=2026-11-14", ["2026-11-14"])
    (root / "sales" / "scratch").mkdir()
    (root / "sales" / "run=2026-11-14-morning").mkdir()
    assert [r.name for r in sync.discover_runs(root, "sales")] == ["run=2026-11-14"]


def test_new_runs_load_oldest_first_each_with_its_own_window(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _run(config.evidence_dir, "sales", "run=2026-11-13", ["2026-11-06", "2026-11-13"])
    _run(config.evidence_dir, "sales", "run=2026-11-12", ["2026-11-05", "2026-11-12"])
    recorder = Recorder()
    assert _go(config, recorder) == 0
    assert recorder.calls[:2] == [
        "load_dxbi_sales_units.py:run=2026-11-12",
        "load_dxbi_sales_units.py:run=2026-11-13",
    ]
    argv = recorder.commands[1]
    assert argv[argv.index("--replace-window") + 1 :] == ["2026-11-06", "2026-11-13"]
    assert (config.state_dir / "loaded" / "sales-run=2026-11-13").exists()


def test_rentals_load_into_the_active_table_with_a_run_id(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _run(config.evidence_dir, "sales", "run=2026-11-14", ["2026-11-14"])
    (config.state_dir / "loaded").mkdir(parents=True)
    (config.state_dir / "loaded" / "sales-run=2026-11-14").touch()
    _run(config.evidence_dir, "rentals", "run=2026-11-14", ["2026-11-07", "2026-11-14"])
    recorder = Recorder()
    assert _go(config, recorder) == 0
    argv = recorder.commands[0]
    assert argv[argv.index("--target") + 1] == "active"
    assert argv[argv.index("--run-id") + 1] == "sync-run=2026-11-14"
    assert argv[argv.index("--replace-window") + 1 :][:2] == ["2026-11-07", "2026-11-14"]


def test_a_loaded_run_is_not_loaded_again_and_nothing_else_runs(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _run(config.evidence_dir, "sales", "run=2026-11-14", ["2026-11-14"])
    (config.state_dir / "loaded").mkdir(parents=True)
    (config.state_dir / "loaded" / "sales-run=2026-11-14").touch()
    recorder = Recorder()
    assert _go(config, recorder) == 0
    assert recorder.calls == []


def test_a_load_that_fails_stops_that_report_and_skips_the_release(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _run(config.evidence_dir, "sales", "run=2026-11-12", ["2026-11-12"])
    _run(config.evidence_dir, "sales", "run=2026-11-13", ["2026-11-13"])
    recorder = Recorder(fail_on="run=2026-11-12")
    assert _go(config, recorder) == 1
    assert recorder.calls == ["load_dxbi_sales_units.py:run=2026-11-12"]
    assert not (config.state_dir / "loaded" / "sales-run=2026-11-12").exists()


def test_the_release_and_cache_flush_follow_a_load_and_clear_the_pending_marker(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    _run(config.evidence_dir, "sales", "run=2026-11-14", ["2026-11-14"])
    recorder = Recorder()
    assert _go(config, recorder) == 0
    assert recorder.calls[-2:] == ["release", "flush"]
    assert not (config.state_dir / "release-pending").exists()


def test_a_failed_release_is_retried_on_the_next_run_without_new_data(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _run(config.evidence_dir, "sales", "run=2026-11-14", ["2026-11-14"])
    assert _go(config, Recorder(fail_on="release")) == 1
    assert (config.state_dir / "release-pending").exists()
    retry = Recorder()
    assert _go(config, retry) == 0
    assert retry.calls == ["release", "flush"]


def test_a_sales_load_failure_in_one_report_does_not_block_the_other(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _run(config.evidence_dir, "sales", "run=2026-11-14", ["2026-11-14"])
    _run(config.evidence_dir, "rentals", "run=2026-11-14", ["2026-11-14"])
    recorder = Recorder(fail_on="load_dxbi_sales_units.py")
    assert _go(config, recorder) == 1
    assert "load_dxbi_rental_events.py:run=2026-11-14" in recorder.calls
    assert "release" in recorder.calls


def test_stale_reports_name_a_report_with_no_recent_success(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    old = _run(root, "rentals", "run=2026-10-29", ["2026-10-29"])
    stamp = time.time() - 40 * 3600
    os.utime(old / "_SUCCESS", (stamp, stamp))
    _run(root, "sales", "run=2026-11-14", ["2026-11-14"])
    assert sync.stale_reports(root, max_age_hours=36) == ["rentals"]
