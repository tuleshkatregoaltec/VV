#!/usr/bin/env python3
"""Process durable large owner-import jobs.

Run as one long-lived worker. Jobs remain in PostgreSQL; each one is claimed under a row lock
and its file digest is fenced by a PostgreSQL advisory lock, so retries and two workers cannot
publish the same file twice.
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

from app.crm.owner_import_requests import claim_next_queued_import, process_queued_import
from app.postgres import close_postgres, get_postgres_engine

logger = logging.getLogger("crm.owner_import_worker")

DEFAULT_HEARTBEAT = Path("/tmp/crm-owner-imports.heartbeat")
BATCH = 20


async def run_once(
    session_factory: Callable[[], AsyncSession], *, limit: int = BATCH
) -> dict[str, int]:
    counts = {"processed": 0, "failed": 0}
    for _ in range(limit):
        async with session_factory() as db:
            request_id = await claim_next_queued_import(db)
            if request_id is None:
                break
            try:
                result = await process_queued_import(db, request_id)
                counts["processed"] += 1
                if result.status == "failed":
                    counts["failed"] += 1
            except Exception:
                logger.exception("Owner import request %s failed", request_id)
                counts["failed"] += 1
    return counts


def heartbeat_healthy(path: Path, *, now: float | None = None) -> bool:
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
        return 0 <= age < 180
    except OSError:
        return False


async def run_forever(
    session_factory: Callable[[], AsyncSession],
    *,
    stop: asyncio.Event,
    interval: float,
    heartbeat: Path,
    report: Callable[[str], None],
) -> None:
    while not stop.is_set():
        started = time.monotonic()
        try:
            counts = await run_once(session_factory)
            heartbeat.touch()
            logger.info("crm owner import run %s", json.dumps(counts, sort_keys=True))
        except Exception:
            logger.exception("CRM owner import run failed")
            _report(report, "CRM owner import worker run failed")
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
        logger.exception("CRM owner import alert delivery failed")


def _configure_reporting() -> Callable[[str], None]:
    from app.config import settings
    from app.core.logging_config import LOGGING_CONFIG

    logging.config.dictConfig(LOGGING_CONFIG)
    logger.setLevel(logging.INFO)
    if not settings.honeybadger_enabled:
        return lambda _message: None
    from honeybadger import honeybadger

    honeybadger.configure(api_key=settings.HONEYBADGER_API_KEY)
    return lambda message: honeybadger.notify(error_class="CrmOwnerImport", error_message=message)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--loop", action="store_true", help="run as a worker until stopped")
    parser.add_argument("--interval", type=float, default=30.0, help="seconds between runs")
    parser.add_argument("--heartbeat", type=Path, default=DEFAULT_HEARTBEAT)
    parser.add_argument("--check-health", action="store_true")
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
            print(json.dumps(await run_once(session_factory), sort_keys=True))
            return
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await run_forever(
            session_factory,
            stop=stop,
            interval=args.interval,
            heartbeat=args.heartbeat,
            report=_configure_reporting(),
        )
    finally:
        await close_postgres()


if __name__ == "__main__":
    asyncio.run(main())
