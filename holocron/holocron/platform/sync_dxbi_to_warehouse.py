"""Load finished DXBI scrapes from the evidence directory into the live warehouse.

The scraper box writes ``<kind>/run=YYYY-MM-DD/`` (kind: ``sales`` or ``rentals``) and touches
``_SUCCESS`` in a run only when every shard finished. This job loads only those runs, oldest
first, each replacing the dates its own checkpoint covers (a run re-reads a rolling window, so a
later run supersedes an earlier one). After anything new was loaded it rebuilds the served
market releases and the profiles, then clears the API caches that read them.

A run's marker in ``<state>/loaded`` is written after its load succeeds, so a failed night is
retried whole on the next run. ``<state>/release-pending`` keeps a failed release build owed.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
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


def load_command(config: Config, run: Run) -> list[str]:
    window = [run.first.isoformat(), run.last.isoformat()]
    if run.kind == "sales":
        script = config.scripts_dir / "load_dxbi_sales_units.py"
        return [config.python, str(script), str(run.path), "--replace-window", *window]
    script = config.scripts_dir / "load_dxbi_rental_events.py"
    reconciliation = config.state_dir / "reconciliations" / f"rentals-{run.name}.json"
    return [
        config.python,
        str(script),
        str(run.path),
        "--target",
        "active",
        "--run-id",
        f"sync-{run.name}",
        "--reconciliation-output",
        str(reconciliation),
        "--replace-window",
        *window,
    ]


def _default_run_command(argv: list[str]) -> int:
    return subprocess.run(argv, check=False).returncode


def run_sync(
    config: Config,
    *,
    run_command: Callable[[list[str]], int] = _default_run_command,
    build_release: Callable[[], None],
    flush_cache: Callable[[], None],
) -> int:
    config.loaded_dir.mkdir(parents=True, exist_ok=True)
    (config.state_dir / "reconciliations").mkdir(parents=True, exist_ok=True)
    failures = 0
    for kind in KINDS:
        pending = [
            run
            for run in discover_runs(config.evidence_dir, kind)
            if not (config.loaded_dir / f"{kind}-{run.name}").exists()
        ]
        for run in pending:
            logger.info("Loading %s %s (%s to %s)", kind, run.name, run.first, run.last)
            if run_command(load_command(config, run)) != 0:
                logger.error("Loading %s %s failed; later runs wait for it", kind, run.name)
                failures += 1
                break
            (config.loaded_dir / f"{kind}-{run.name}").touch()
            config.release_pending.touch()
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
    for kind in stale_reports(config.evidence_dir, max_age_hours=36):
        logger.warning("No finished %s run in the last 36 hours", kind)
        if kind == "sales":
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
        )


if __name__ == "__main__":
    raise SystemExit(main())
