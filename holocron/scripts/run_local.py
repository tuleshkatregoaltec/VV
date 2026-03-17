#!/usr/bin/env python3
"""Run one Holocron Dagster source job locally."""

from __future__ import annotations

import argparse
import json
import sys

from dagster import DagsterInstance

from holocron.sources import SOURCES_BY_NAME


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Holocron source locally")
    parser.add_argument("--source", required=True, choices=sorted(SOURCES_BY_NAME))
    parser.add_argument(
        "--config",
        default="{}",
        help='JSON config passed to the source release asset, for example \'{"release_id": "..."}\'',
    )
    args = parser.parse_args()

    try:
        source_config = json.loads(args.config)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON for --config: {exc}") from exc

    from holocron.definitions import defs

    source = SOURCES_BY_NAME[args.source]
    job = defs.resolve_job_def(source.ingest_job_name)
    run_config = {}
    if source_config:
        run_config = {"ops": {source.local_release_asset_name: {"config": source_config}}}
        print(f"Using run config: {json.dumps(run_config, indent=2, sort_keys=True)}")

    result = job.execute_in_process(run_config=run_config, instance=DagsterInstance.get())
    if result.success:
        print(f"Job {source.ingest_job_name} succeeded.")
        sys.exit(0)
    print(f"Job {source.ingest_job_name} failed.")
    sys.exit(1)


if __name__ == "__main__":
    main()
