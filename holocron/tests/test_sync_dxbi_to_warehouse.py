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
    for day in days:
        shard = run / "shards" / day
        shard.mkdir(parents=True)
        (shard / "a.jsonl.gz").write_text(day)
    (run / "checkpoint.json").write_text(json.dumps({"completed": completed, "failed": {}}))
    if success:
        (run / "_SUCCESS").touch()
    return run


class Recorder:
    """Stands in for subprocess, the release build, the cache flush and the Owners refresh."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.calls: list[str] = []
        self.commands: list[list[str]] = []
        self.inputs: list[list[str]] = []
        self.fail_on = fail_on

    def command(self, argv: list[str]) -> int:
        self.commands.append(argv)
        script = next(part for part in argv if part.endswith(".py"))
        source = Path(argv[argv.index(script) + 1])
        self.inputs.append(sorted(p.parent.name for p in source.rglob("*.jsonl.gz")))
        name = Path(script).name
        self.calls.append(f"{name}:{Path(argv[argv.index(script) + 1]).name}")
        return 1 if self.fail_on and self.fail_on in self.calls[-1] else 0

    def release(self) -> None:
        self.calls.append("release")
        if self.fail_on == "release":
            raise RuntimeError("release failed")

    def flush(self) -> None:
        self.calls.append("flush")

    def owners(self) -> None:
        self.calls.append("owners")
        if self.fail_on == "owners":
            raise RuntimeError("owners refresh failed")


def _config(tmp_path: Path) -> sync.Config:
    return sync.Config(
        evidence_dir=tmp_path / "evidence",
        state_dir=tmp_path / "state",
        python="python",
        scripts_dir=Path("scripts"),
    )


def _fresh(config: sync.Config, *kinds: str) -> None:
    """Both feeds must have a recent finished run, or the sync fails as stale."""
    for kind in kinds:
        run = _run(config.evidence_dir, kind, "run=2026-11-01", ["2026-11-01"])
        (config.state_dir / "loaded").mkdir(parents=True, exist_ok=True)
        (config.state_dir / "loaded" / f"{kind}-{run.name}").touch()


def _go(config: sync.Config, recorder: Recorder) -> int:
    return sync.run_sync(
        config,
        run_command=recorder.command,
        build_release=recorder.release,
        flush_cache=recorder.flush,
        refresh_owners=recorder.owners,
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
    _fresh(config, "rentals")
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


def test_a_loaded_run_is_not_loaded_again_and_only_the_owners_refresh_runs(
    tmp_path: Path,
) -> None:
    # Lease links age out of their window daily, so the Owners refresh runs on every sync.
    config = _config(tmp_path)
    _fresh(config, "rentals")
    _run(config.evidence_dir, "sales", "run=2026-11-14", ["2026-11-14"])
    (config.state_dir / "loaded" / "sales-run=2026-11-14").touch()
    recorder = Recorder()
    assert _go(config, recorder) == 0
    assert recorder.calls == ["owners"]


def test_a_load_that_fails_stops_that_report_and_skips_the_release(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _run(config.evidence_dir, "sales", "run=2026-11-12", ["2026-11-12"])
    _run(config.evidence_dir, "sales", "run=2026-11-13", ["2026-11-13"])
    recorder = Recorder(fail_on="run=2026-11-12")
    assert _go(config, recorder) == 1
    # Nor do the Owners lease links follow a window that may be half loaded.
    assert recorder.calls == ["load_dxbi_sales_units.py:run=2026-11-12"]
    assert not (config.state_dir / "loaded" / "sales-run=2026-11-12").exists()


def test_the_release_and_cache_flush_follow_a_load_and_clear_the_pending_marker(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    _fresh(config, "rentals")
    _run(config.evidence_dir, "sales", "run=2026-11-14", ["2026-11-14"])
    recorder = Recorder()
    assert _go(config, recorder) == 0
    assert recorder.calls[-3:] == ["release", "flush", "owners"]
    assert not (config.state_dir / "release-pending").exists()


def test_a_failed_release_is_retried_on_the_next_run_without_new_data(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _fresh(config, "rentals")
    _run(config.evidence_dir, "sales", "run=2026-11-14", ["2026-11-14"])
    assert _go(config, Recorder(fail_on="release")) == 1
    assert (config.state_dir / "release-pending").exists()
    retry = Recorder()
    assert _go(config, retry) == 0
    assert retry.calls == ["release", "flush", "owners"]


def test_a_sales_load_failure_in_one_report_does_not_block_the_other(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _run(config.evidence_dir, "sales", "run=2026-11-14", ["2026-11-14"])
    _run(config.evidence_dir, "rentals", "run=2026-11-14", ["2026-11-14"])
    recorder = Recorder(fail_on="load_dxbi_sales_units.py")
    assert _go(config, recorder) == 1
    assert "load_dxbi_rental_events.py:run=2026-11-14" in recorder.calls
    assert "release" in recorder.calls
    assert "owners" not in recorder.calls


def test_stale_reports_name_a_report_with_no_recent_success(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    old = _run(root, "rentals", "run=2026-10-29", ["2026-10-29"])
    stamp = time.time() - 40 * 3600
    os.utime(old / "_SUCCESS", (stamp, stamp))
    _run(root, "sales", "run=2026-11-14", ["2026-11-14"])
    assert sync.stale_reports(root, max_age_hours=36) == ["rentals"]


def test_a_failed_release_skips_the_owners_refresh(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _run(config.evidence_dir, "rentals", "run=2026-11-14", ["2026-11-14"])
    recorder = Recorder(fail_on="release")
    assert _go(config, recorder) == 1
    assert "owners" not in recorder.calls


def test_a_failed_owners_refresh_fails_the_run_and_keeps_the_loads(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _run(config.evidence_dir, "sales", "run=2026-11-14", ["2026-11-14"])
    _run(config.evidence_dir, "rentals", "run=2026-11-14", ["2026-11-14"])
    assert _go(config, Recorder(fail_on="owners")) == 1
    assert (config.state_dir / "loaded" / "rentals-run=2026-11-14").exists()
    assert not (config.state_dir / "release-pending").exists()
    retry = Recorder()
    assert _go(config, retry) == 0
    assert retry.calls == ["owners"]


def test_the_owners_refresh_runs_the_backend_script_with_its_own_state(tmp_path: Path) -> None:
    repo = tmp_path / "vv"
    argv, cwd, env = sync.owners_refresh_command(repo, tmp_path / "state")
    assert argv == [
        str(repo / "backend/.venv/bin/python"),
        "scripts/crm/refresh_rental_imports.py",
        "--state-dir",
        str(tmp_path / "state" / "owners"),
    ]
    assert cwd == repo / "backend"
    assert env["PYTHONPATH"] == str(repo / "backend")


def test_the_transactions_page_tables_build_with_the_backend_after_the_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The Transactions pages read page tables built from the profiles; a release that rebuilt
    # the profiles but not the page tables would serve yesterday's records.
    repo = tmp_path / "vv"
    argv, cwd, env = sync.page_tables_command(repo)
    assert argv == [str(repo / "backend/.venv/bin/python"), "-m", "app.transaction.page_tables"]
    assert cwd == repo / "backend"
    assert env["PYTHONPATH"] == str(repo / "backend")

    steps: list[str] = []
    monkeypatch.setattr(sync, "_build_market_release", lambda: steps.append("release"))
    monkeypatch.setattr(sync, "_build_page_tables", lambda repo_dir: steps.append("page tables"))
    sync._build_release(repo)
    assert steps == ["release", "page tables"]


def test_the_cache_flush_covers_every_page_that_reads_the_release() -> None:
    assert set(sync.CACHE_PREFIXES) >= {"transactions:", "filters:", "analytics:"}


def _loaded(config: sync.Config, kind: str, *names: str) -> None:
    (config.state_dir / "loaded").mkdir(parents=True, exist_ok=True)
    for name in names:
        (config.state_dir / "loaded" / f"{kind}-{name}").touch()


def _span(first: int, last: int) -> list[str]:
    return [f"2026-11-{day:02d}" for day in range(first, last + 1)]


def test_a_late_run_loads_only_the_days_no_newer_loaded_run_covers(tmp_path: Path) -> None:
    # Run 11-10 got its _SUCCESS after run 11-12 was loaded. Days 11-05..11-10 belong to the
    # newer run; only 11-03 and 11-04 are the late run's to replace.
    config = _config(tmp_path)
    _fresh(config, "sales")
    _run(config.evidence_dir, "rentals", "run=2026-11-12", _span(5, 12))
    _loaded(config, "rentals", "run=2026-11-12")
    _run(config.evidence_dir, "rentals", "run=2026-11-10", _span(3, 10))
    recorder = Recorder()
    assert _go(config, recorder) == 0
    assert recorder.inputs == [["2026-11-03", "2026-11-04"]]
    argv = recorder.commands[0]
    assert argv[argv.index("--replace-window") + 1 :] == ["2026-11-03", "2026-11-04"]
    assert (config.state_dir / "loaded" / "rentals-run=2026-11-10").exists()
    assert not (config.state_dir / "views").exists() or not list(
        (config.state_dir / "views").iterdir()
    )


def test_a_late_run_whose_days_are_all_newer_loaded_is_marked_without_loading(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    _fresh(config, "rentals")
    _run(config.evidence_dir, "sales", "run=2026-11-14", _span(7, 14))
    _loaded(config, "sales", "run=2026-11-14")
    _run(config.evidence_dir, "sales", "run=2026-11-13", _span(7, 13))
    recorder = Recorder()
    assert _go(config, recorder) == 0
    assert recorder.commands == []
    assert (config.state_dir / "loaded" / "sales-run=2026-11-13").exists()


def test_a_late_run_split_around_newer_days_loads_each_older_stretch(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _fresh(config, "sales")
    _run(config.evidence_dir, "rentals", "run=2026-11-12", _span(4, 5))
    _loaded(config, "rentals", "run=2026-11-12")
    _run(config.evidence_dir, "rentals", "run=2026-11-10", _span(1, 10))
    recorder = Recorder()
    assert _go(config, recorder) == 0
    windows = [argv[argv.index("--replace-window") + 1 :] for argv in recorder.commands]
    assert windows == [["2026-11-01", "2026-11-03"], ["2026-11-06", "2026-11-10"]]
    assert recorder.inputs == [_span(1, 3), _span(6, 10)]


def test_an_older_loaded_run_does_not_narrow_a_newer_one(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _fresh(config, "sales")
    _run(config.evidence_dir, "rentals", "run=2026-11-12", _span(5, 12))
    _loaded(config, "rentals", "run=2026-11-05")
    _run(config.evidence_dir, "rentals", "run=2026-11-05", _span(1, 5))
    recorder = Recorder()
    # run=2026-11-12 is pending and newer: both load, oldest first, nothing narrowed.
    assert _go(config, recorder) == 0
    assert recorder.inputs == [_span(5, 12)]


def test_a_failure_while_loading_a_late_run_leaves_it_unmarked(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _fresh(config, "sales")
    _run(config.evidence_dir, "rentals", "run=2026-11-12", _span(5, 12))
    _loaded(config, "rentals", "run=2026-11-12")
    _run(config.evidence_dir, "rentals", "run=2026-11-10", _span(3, 10))
    assert _go(config, Recorder(fail_on="run=2026-11-10")) == 1
    assert not (config.state_dir / "loaded" / "rentals-run=2026-11-10").exists()


def test_a_stale_rentals_feed_fails_the_run_like_a_stale_sales_feed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _fresh(config, "sales")
    old = _run(config.evidence_dir, "rentals", "run=2026-10-29", ["2026-10-29"])
    _loaded(config, "rentals", "run=2026-10-29")
    stamp = time.time() - 40 * 3600
    os.utime(old / "_SUCCESS", (stamp, stamp))
    recorder = Recorder()
    assert _go(config, recorder) == 1
    # The data that is there is still served and the Owners refresh still runs.
    assert recorder.calls == ["owners"]


def test_a_feed_with_no_finished_run_at_all_fails_the_run(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _fresh(config, "sales")
    assert _go(config, Recorder()) == 1


def test_a_stale_sales_feed_still_fails_the_run(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _fresh(config, "rentals")
    old = _run(config.evidence_dir, "sales", "run=2026-10-29", ["2026-10-29"])
    _loaded(config, "sales", "run=2026-10-29")
    stamp = time.time() - 40 * 3600
    os.utime(old / "_SUCCESS", (stamp, stamp))
    assert _go(config, Recorder()) == 1


def test_a_loaded_run_records_its_days_as_verified_load_evidence(tmp_path: Path) -> None:
    """The run's _SUCCESS proves every price-band shard of its days finished: the warehouse keeps
    that as load evidence (source_load_windows), so Analytics coverage can say which DXBI days
    are fully loaded instead of calling every day since the DLD feed stopped unverified."""
    config = _config(tmp_path)
    _run(config.evidence_dir, "sales", "run=2026-11-14", ["2026-11-08", "2026-11-14"])
    _run(config.evidence_dir, "rentals", "run=2026-11-14", ["2026-11-10", "2026-11-13"])
    windows: list[tuple] = []
    recorder = Recorder()
    assert (
        sync.run_sync(
            config,
            run_command=recorder.command,
            build_release=recorder.release,
            flush_cache=recorder.flush,
            refresh_owners=recorder.owners,
            record_window=lambda run, first, last: windows.append(
                (*sync.evidence_table(run.kind), run.name, first, last)
            ),
        )
        == 0
    )
    assert windows == [
        ("dxbi_sales_unit_events", "transaction_date", "run=2026-11-14",
         date(2026, 11, 8), date(2026, 11, 14)),
        ("dxbi_rental_events", "lease_start", "run=2026-11-14",
         date(2026, 11, 10), date(2026, 11, 13)),
    ]  # fmt: skip


def test_a_failed_load_records_no_load_evidence(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _fresh(config, "rentals")
    _run(config.evidence_dir, "sales", "run=2026-11-14", ["2026-11-14"])
    windows: list[tuple] = []
    recorder = Recorder(fail_on="load_dxbi_sales_units.py")
    sync.run_sync(
        config,
        run_command=recorder.command,
        build_release=recorder.release,
        flush_cache=recorder.flush,
        refresh_owners=recorder.owners,
        record_window=lambda run, first, last: windows.append((run.name, first, last)),
    )
    assert windows == []


def test_a_late_run_records_only_the_stretch_it_loaded(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _fresh(config, "rentals")
    _run(config.evidence_dir, "sales", "run=2026-11-13", ["2026-11-06", "2026-11-13"])
    newer = _run(config.evidence_dir, "sales", "run=2026-11-14", ["2026-11-10", "2026-11-14"])
    (config.state_dir / "loaded" / f"sales-{newer.name}").touch()
    windows: list[tuple] = []
    recorder = Recorder()
    sync.run_sync(
        config,
        run_command=recorder.command,
        build_release=recorder.release,
        flush_cache=recorder.flush,
        refresh_owners=recorder.owners,
        record_window=lambda run, first, last: windows.append((run.name, first, last)),
    )
    assert windows == [("run=2026-11-13", date(2026, 11, 6), date(2026, 11, 9))]


def test_runs_loaded_before_evidence_was_kept_record_the_days_they_still_hold(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    (config.state_dir / "loaded").mkdir(parents=True)
    for name, days in (("run=2026-11-13", ["2026-11-06", "2026-11-13"]),
                       ("run=2026-11-14", ["2026-11-10", "2026-11-14"])):  # fmt: skip
        run = _run(config.evidence_dir, "sales", name, days)
        (config.state_dir / "loaded" / f"sales-{run.name}").touch()
    _run(config.evidence_dir, "sales", "run=2026-11-15", ["2026-11-15"])  # not loaded yet
    windows: list[tuple] = []
    sync.record_loaded(config, lambda run, first, last: windows.append((run.name, first, last)))
    assert windows == [
        ("run=2026-11-13", date(2026, 11, 6), date(2026, 11, 9)),
        ("run=2026-11-14", date(2026, 11, 10), date(2026, 11, 14)),
    ]
