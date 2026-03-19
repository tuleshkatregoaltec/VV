#!/usr/bin/env python3
"""Run chunked historical backfills for the Bayut transactions source."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import sys

from dagster import DagsterInstance

from holocron.sources import SOURCES_BY_NAME

SOURCE_NAME = "bay_transactions"


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _chunk_release_prefix() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{SOURCE_NAME}-backfill-{timestamp}"


def _iter_chunks(start_date: date, end_date: date, chunk_days: int):
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_date)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a chunked Bayut historical backfill")
    parser.add_argument("--start-date", required=True, help="Inclusive start date in YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="Inclusive end date in YYYY-MM-DD")
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=30,
        help="Days per Bayut backfill chunk. Defaults to 30.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional page cap per purpose for bounded runs.",
    )
    parser.add_argument(
        "--chrome-path",
        default="",
        help="Optional Chrome/Chromium executable path for Playwright bootstrap.",
    )
    parser.add_argument(
        "--release-prefix",
        default="",
        help="Optional prefix for generated release ids. Defaults to a UTC timestamped prefix.",
    )
    args = parser.parse_args()

    start_date = _parse_date(args.start_date)
    end_date = _parse_date(args.end_date)
    if start_date > end_date:
        raise SystemExit(f"start-date {args.start_date} is after end-date {args.end_date}")
    if args.chunk_days <= 0:
        raise SystemExit("--chunk-days must be greater than 0")

    from holocron.definitions import defs

    source = SOURCES_BY_NAME[SOURCE_NAME]
    job = defs.resolve_job_def(source.ingest_job_name)
    release_prefix = args.release_prefix.strip() or _chunk_release_prefix()

    for chunk_start, chunk_end in _iter_chunks(start_date, end_date, args.chunk_days):
        release_id = f"{release_prefix}-{chunk_start.isoformat()}-to-{chunk_end.isoformat()}"
        source_config = {
            "release_id": release_id,
            "start_date": chunk_start.isoformat(),
            "end_date": chunk_end.isoformat(),
            "lookback_days": 0,
        }
        if args.max_pages is not None:
            source_config["max_pages"] = args.max_pages
        if args.chrome_path:
            source_config["chrome_path"] = args.chrome_path

        run_config = {"ops": {source.local_release_asset_name: {"config": source_config}}}
        print(
            f"Running {SOURCE_NAME} for {chunk_start.isoformat()}..{chunk_end.isoformat()} "
            f"with release_id={release_id}"
        )
        print(json.dumps(run_config, indent=2, sort_keys=True))
        result = job.execute_in_process(run_config=run_config, instance=DagsterInstance.get())
        if not result.success:
            print(f"Job {source.ingest_job_name} failed for release {release_id}")
            sys.exit(1)

    print(f"Completed Bayut backfill for {args.start_date}..{args.end_date}")


if __name__ == "__main__":
    main()
