"""Load finished DXBI scrapes from the evidence directory into the live warehouse.

The scraper box writes ``<kind>/run=YYYY-MM-DD/`` (kind: ``sales`` or ``rentals``) and touches
``_SUCCESS`` in a run only when every shard finished. This job loads only those runs, oldest
first, each replacing the dates its own checkpoint covers (a run re-reads a rolling window, so a
later run supersedes an earlier one). The newest complete data for a day wins whatever order
runs finish in: a run that gets its ``_SUCCESS`` after a newer run was already loaded replaces
only the days no newer loaded run covers, loading just those days' shards, and is skipped when
none are left. After anything new was loaded it rebuilds the served
market releases and the profiles, then clears the API caches that read them. Every run then
refreshes the Owners lease links (imported claims' lease end, rent and lease id) and republishes
the stored owner assessments; a lease link's window moves with the date, so this runs even when
nothing new was loaded.

A run's marker in ``<state>/loaded`` is written after its load succeeds, so a failed night is
retried whole on the next run. ``<state>/release-pending`` keeps a failed release build owed.
The unit fails when a report has no finished run in 36 hours (sales or rentals) or a load fails,
so ``systemctl --failed`` and the journal show it.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger("sync_dxbi_to_warehouse")

KINDS = ("sales", "rentals")
_RUN_NAME = re.compile(r"^run=\d{4}-\d{2}-\d{2}$")
CACHE_PREFIXES = ("transactions:", "analytics:")


class RunError(RuntimeError):
    """A run marked successful that cannot be loaded as it stands."""


@dataclass(frozen=True)
class Run:
    kind: str
    path: Path
    first: date
    last: date

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class Config:
    evidence_dir: Path
    state_dir: Path
    python: str
    scripts_dir: Path

    @property
    def loaded_dir(self) -> Path:
        return self.state_dir / "loaded"

    @property
    def views_dir(self) -> Path:
        return self.state_dir / "views"

    @property
    def release_pending(self) -> Path:
        return self.state_dir / "release-pending"


def _window(run_dir: Path) -> tuple[date, date]:
    try:
        completed = json.loads((run_dir / "checkpoint.json").read_text())["completed"]
        days = [date.fromisoformat(key.split("|", 1)[0]) for key in completed]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise RunError(f"{run_dir} has _SUCCESS but no readable checkpoint: {exc}") from exc
    if not days:
        raise RunError(f"{run_dir} has _SUCCESS but its checkpoint covers no dates")
    return min(days), max(days)


def discover_runs(evidence_dir: Path, kind: str) -> list[Run]:
    """Finished runs of one report, oldest first."""
    root = evidence_dir / kind
    runs = []
    for path in sorted(root.glob("run=*")) if root.is_dir() else []:
        if not _RUN_NAME.match(path.name) or not path.is_dir() or not (path / "_SUCCESS").exists():
            continue
        first, last = _window(path)
        runs.append(Run(kind, path, first, last))
    return runs


def stale_reports(evidence_dir: Path, *, max_age_hours: float) -> list[str]:
    """Reports whose newest finished run is older than the limit (or that have none)."""
    cutoff = time.time() - max_age_hours * 3600
    stale = []
    for kind in KINDS:
        stamps = [
            marker.stat().st_mtime
            for marker in (evidence_dir / kind).glob("run=*/_SUCCESS")
            if _RUN_NAME.match(marker.parent.name)
        ]
        if not stamps or max(stamps) < cutoff:
            stale.append(kind)
    return stale


def load_command(
    config: Config,
    run: Run,
    *,
    first: date | None = None,
    last: date | None = None,
    source: Path | None = None,
) -> list[str]:
    """The loader call for a run, or for the stretch ``first`` to ``last`` of it read from ``source``."""
    narrowed = first is not None
    first, last = first or run.first, last or run.last
    window = [first.isoformat(), last.isoformat()]
    path = str(source or run.path)
    if run.kind == "sales":
        script = config.scripts_dir / "load_dxbi_sales_units.py"
        return [config.python, str(script), path, "--replace-window", *window]
    script = config.scripts_dir / "load_dxbi_rental_events.py"
    suffix = f"-{first.isoformat()}" if narrowed else ""
    reconciliation = config.state_dir / "reconciliations" / f"rentals-{run.name}{suffix}.json"
    return [
        config.python,
        str(script),
        path,
        "--target",
        "active",
        "--run-id",
        f"sync-{run.name}{suffix}",
        "--reconciliation-output",
        str(reconciliation),
        "--replace-window",
        *window,
    ]


def uncovered_stretches(run: Run, newer_loaded: list[Run]) -> list[tuple[date, date]]:
    """The stretches of the run's window that no newer, already loaded run covers.

    A newer run holds a later scrape of the days it covers, so the run's own copy of them is
    never loaded over it. Stretches are runs of consecutive days, since a load replaces one
    contiguous window.
    """
    stretches: list[tuple[date, date]] = []
    start: date | None = None
    day = run.first
    while day <= run.last:
        covered = any(other.first <= day <= other.last for other in newer_loaded)
        if not covered and start is None:
            start = day
        if covered and start is not None:
            stretches.append((start, day - timedelta(days=1)))
            start = None
        day += timedelta(days=1)
    if start is not None:
        stretches.append((start, run.last))
    return stretches


def _stretch_view(config: Config, run: Run, first: date, last: date) -> Path:
    """A folder holding only the shards of the days ``first`` to ``last`` of the run."""
    view = config.views_dir / f"{run.kind}-{run.name}-{first.isoformat()}"
    shutil.rmtree(view, ignore_errors=True)
    for day_dir in sorted((run.path / "shards").glob("*")):
        try:
            day = date.fromisoformat(day_dir.name)
        except ValueError:
            continue
        if first <= day <= last and day_dir.is_dir():
            target = view / "shards" / day_dir.name
            target.mkdir(parents=True)
            for shard in day_dir.iterdir():
                (target / shard.name).symlink_to(shard.resolve())
    return view


def _default_run_command(argv: list[str]) -> int:
    return subprocess.run(argv, check=False).returncode


def _is_loaded(config: Config, run: Run) -> bool:
    return (config.loaded_dir / f"{run.kind}-{run.name}").exists()


def _load_run(
    config: Config, run: Run, finished: list[Run], run_command: Callable[[list[str]], int]
) -> bool:
    """Load what the run still owns of its window; False when a load failed."""
    newer_loaded = [
        other for other in finished if other.name > run.name and _is_loaded(config, other)
    ]
    stretches = uncovered_stretches(run, newer_loaded)
    if not newer_loaded or stretches == [(run.first, run.last)]:
        logger.info("Loading %s %s (%s to %s)", run.kind, run.name, run.first, run.last)
        if run_command(load_command(config, run)) != 0:
            logger.error("Loading %s %s failed; later runs wait for it", run.kind, run.name)
            return False
        config.release_pending.touch()
        return True
    if not stretches:
        logger.info(
            "Skipping %s %s: newer loaded runs already cover %s to %s",
            run.kind,
            run.name,
            run.first,
            run.last,
        )
        return True
    for first, last in stretches:
        logger.info(
            "Loading %s %s late, only %s to %s; newer loaded runs hold the other days",
            run.kind,
            run.name,
            first,
            last,
        )
        view = _stretch_view(config, run, first, last)
        try:
            if not view.exists():
                logger.warning("%s %s has no shards for %s to %s", run.kind, run.name, first, last)
                continue
            if run_command(load_command(config, run, first=first, last=last, source=view)) != 0:
                logger.error("Loading %s %s failed; later runs wait for it", run.kind, run.name)
                return False
            config.release_pending.touch()
        finally:
            shutil.rmtree(view, ignore_errors=True)
    return True


def run_sync(
    config: Config,
    *,
    run_command: Callable[[list[str]], int] = _default_run_command,
    build_release: Callable[[], None],
    flush_cache: Callable[[], None],
    refresh_owners: Callable[[], None],
) -> int:
    config.loaded_dir.mkdir(parents=True, exist_ok=True)
    (config.state_dir / "reconciliations").mkdir(parents=True, exist_ok=True)
    failures = 0
    for kind in KINDS:
        finished = discover_runs(config.evidence_dir, kind)
        pending = [run for run in finished if not _is_loaded(config, run)]
        for run in pending:
            if not _load_run(config, run, finished, run_command):
                failures += 1
                break
            (config.loaded_dir / f"{kind}-{run.name}").touch()
    if config.release_pending.exists():
        try:
            build_release()
            flush_cache()
        except Exception:
            logger.exception("Release build or cache flush failed; it is retried next run")
            return 1
        config.release_pending.unlink()
    else:
        logger.info("Nothing new to load")
    if failures:
        logger.warning("A load failed; the Owners lease refresh waits for a complete load")
    else:
        try:
            refresh_owners()
        except Exception:
            logger.exception("Owners lease refresh failed; it is retried next run")
            failures += 1
    for kind in stale_reports(config.evidence_dir, max_age_hours=36):
        logger.error("No finished %s run in the last 36 hours", kind)
        failures += 1
    return 1 if failures else 0


def _build_release() -> None:
    from holocron.market import release
    from holocron.market.dxbi_profile import build_profiles
    from holocron.platform.clickhouse import ClickHouseClient
    from holocron.platform.settings import Settings

    clickhouse = ClickHouseClient(Settings())
    owner = f"dxbi-sync-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    # Rental areas are learned from the served sales release, so sales is built first.
    for name, build in (
        ("market_sale_events", release.materialize_market_sale_events),
        ("market_rental_events", release.materialize_market_rental_events),
    ):
        logger.info(
            "%s release %s",
            name,
            json.dumps(build(clickhouse=clickhouse, owner=owner), default=str),
        )
    logger.info("profiles %s", json.dumps(build_profiles(clickhouse), default=str))


def _flush_cache(backend_dir: Path) -> None:
    code = (
        "import asyncio\n"
        "from app.core.cache import invalidate_prefixes\n"
        f"print(asyncio.run(invalidate_prefixes({CACHE_PREFIXES!r}, require_connection=True)))\n"
    )
    python = backend_dir / ".venv/bin/python"
    subprocess.run([str(python), "-c", code], cwd=backend_dir, check=True)


def owners_refresh_command(repo_dir: Path, state_dir: Path) -> tuple[list[str], Path, dict]:
    backend = repo_dir / "backend"
    argv = [
        str(backend / ".venv/bin/python"),
        "scripts/crm/refresh_rental_imports.py",
        "--state-dir",
        str(state_dir / "owners"),
    ]
    return argv, backend, {**os.environ, "PYTHONPATH": str(backend)}


def _refresh_owners(repo_dir: Path, state_dir: Path) -> None:
    argv, cwd, env = owners_refresh_command(repo_dir, state_dir)
    logger.info("Refreshing Owners lease links and assessments")
    subprocess.run(argv, cwd=cwd, env=env, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args.state_dir.mkdir(parents=True, exist_ok=True)
    with (args.state_dir / "sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.info("A DXBI warehouse sync is already running")
            return 0
        os.environ.setdefault("PYTHONPATH", str(args.repo_dir / "holocron"))
        config = Config(
            evidence_dir=args.evidence_dir,
            state_dir=args.state_dir,
            python=sys.executable,
            scripts_dir=args.repo_dir / "holocron/scripts",
        )
        return run_sync(
            config,
            build_release=_build_release,
            flush_cache=lambda: _flush_cache(args.repo_dir / "backend"),
            refresh_owners=lambda: _refresh_owners(args.repo_dir, args.state_dir),
        )


if __name__ == "__main__":
    raise SystemExit(main())
