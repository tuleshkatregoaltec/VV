#!/usr/bin/env python3
"""Run a single Dagster job locally without the webserver."""

import argparse
import json
import sys

from dagster import DagsterInstance
from etl.orchestration.source_registry import registered_job_names, run_config_for_args


def main():
    parser = argparse.ArgumentParser(description="Run a Dagster job locally")
    parser.add_argument(
        "--job",
        required=True,
        choices=registered_job_names(),
    )
    parser.add_argument(
        "--release-id", default="", help="Override shared release ID for non-DLD jobs"
    )
    parser.add_argument("--batch-id", default="", help="Override DLD batch ID")
    parser.add_argument("--run-id", default="", help="Backward-compatible alias for --release-id")
    parser.add_argument(
        "--max-plots", type=int, default=None, help="Limit GIS land-plot scrape size"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Override GIS plot-detail concurrency",
    )
    args = parser.parse_args()

    from etl.definitions import defs

    job = defs.get_job_def(args.job)
    run_config = {}
    ops_config = run_config_for_args(args)

    if ops_config:
        run_config = {"ops": ops_config}
        print(f"Using run config: {json.dumps(run_config, indent=2, sort_keys=True)}")

    instance = DagsterInstance.get()
    result = job.execute_in_process(run_config=run_config, instance=instance)

    if result.success:
        print(f"Job {args.job} succeeded.")
        sys.exit(0)
    else:
        print(f"Job {args.job} FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    main()
