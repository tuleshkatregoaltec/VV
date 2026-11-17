#!/usr/bin/env python3
"""Move leads whose rotation timed out on to the next person (or the team pool).

Run this as its own long-lived worker with `--loop`, never inside the API workers.
Production targets ECS/Fargate; `crm-rotation` in docker-compose.yml is the legacy runner. Every minute it moves the overdue leads; a run that
finds more than one batch goes again at once. State lives in PostgreSQL and each lead is handled
in its own transaction under its own row lock, so the worker is safe to restart at any moment,
to run as more than one copy, and to miss runs (a lead is then moved late, never twice).

    uv run python scripts/crm/advance_lead_rotations.py            # one run, exit 1 if a lead failed
    uv run python scripts/crm/advance_lead_rotations.py --loop     # the worker

The worker touches a heartbeat file after every run that reached the database; the container
health check fails when it is older than three minutes. A lead that fails is logged at ERROR
(and sent to Honeybadger when configured) and retried on the next run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.config
import signal
import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.rotation import advance_due
from app.postgres import close_postgres, get_postgres_engine

logger = logging.getLogger("crm.rotation_worker")

BATCH = 500
DEFAULT_HEARTBEAT = Path("/tmp/crm-rotation.heartbeat")


async def run_once(
    session_factory: Callable[[], AsyncSession], *, should_stop: Callable[[], bool] = lambda: False
) -> dict[str, int]:
    async with session_factory() as db:
        return await advance_due(db, limit=BATCH, should_stop=should_stop)


async def run_forever(
    session_factory: Callable[[], AsyncSession],
    *,
    stop: asyncio.Event,
    interval: float = 60.0,
    heartbeat: Path | None = None,
    report: Callable[[str], None] = lambda _message: None,
) -> None:
    """Run until `stop` is set. A failed run is logged and reported, then retried next interval."""
    while not stop.is_set():
        started = time.monotonic()
        full_batch = False
        try:
            counts = await run_once(session_factory, should_stop=stop.is_set)
            logger.info("crm rotation run %s", json.dumps(counts, sort_keys=True))
            if heartbeat is not None:
                heartbeat.touch()
            if counts.get("failed"):
                _report(
                    report,
                    f"CRM lead rotation: {counts['failed']} lead(s) failed and will be retried",
                )
            # More due than one batch: carry on now, unless the batch was all failures.
            full_batch = (
                sum(counts.get(key, 0) for key in ("rotated", "released", "stopped")) >= BATCH
            )
        except Exception:
            logger.exception("CRM lead rotation run failed")
            _report(report, "CRM lead rotation run failed")
        if full_batch:
            continue
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=max(0.0, interval - (time.monotonic() - started))
            )
        except TimeoutError:
            pass


def _report(report: Callable[[str], None], message: str) -> None:
    try:
        report(message)
    except Exception:
        logger.exception("CRM rotation alert delivery failed")


def _configure_reporting() -> Callable[[str], None]:
    from app.config import settings
    from app.core.logging_config import LOGGING_CONFIG

    logging.config.dictConfig(LOGGING_CONFIG)
    logger.setLevel(logging.INFO)
    if not settings.honeybadger_enabled:
        return lambda _message: None
    from honeybadger import honeybadger

    honeybadger.configure(api_key=settings.HONEYBADGER_API_KEY)
    return lambda message: honeybadger.notify(error_class="CrmLeadRotation", error_message=message)


def heartbeat_healthy(path: Path, *, now: float | None = None) -> bool:
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
        return 0 <= age < 180
    except OSError:
        return False


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--loop", action="store_true", help="run as a worker until stopped")
    parser.add_argument("--interval", type=float, default=60.0, help="seconds between runs")
    parser.add_argument("--heartbeat", type=Path, default=DEFAULT_HEARTBEAT)
    parser.add_argument(
        "--check-health", action="store_true", help="exit 0 only for a recent heartbeat"
    )
    args = parser.parse_args()
    if not 0 < args.interval <= 60:
        parser.error("--interval must be greater than zero and at most 60 seconds")

    if args.check_health:
        raise SystemExit(0 if heartbeat_healthy(args.heartbeat) else 1)

    session_factory = async_sessionmaker(
        get_postgres_engine(), class_=AsyncSession, expire_on_commit=False
    )
    try:
        if not args.loop:
            counts = await run_once(session_factory)
            print(json.dumps(counts, sort_keys=True))
            # A lead that failed is retried next run; the non-zero exit makes a scheduler alert.
            if counts.get("failed"):
                raise SystemExit(1)
            return
        report = _configure_reporting()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            # Finish the lead in hand, then exit; a lead never sits half-moved.
            loop.add_signal_handler(sig, stop.set)
        logger.info("CRM rotation worker started (every %ss)", args.interval)
        await run_forever(
            session_factory,
            stop=stop,
            interval=args.interval,
            heartbeat=args.heartbeat,
            report=report,
        )
        logger.info("CRM rotation worker stopped")
    finally:
        await close_postgres()


if __name__ == "__main__":
    asyncio.run(main())
