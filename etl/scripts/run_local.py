#!/usr/bin/env python3
"""
Run a single Dagster job locally without the webserver.

Usage:
    python -m etl.scripts.run_local --job dld_ingest
    python -m etl.scripts.run_local --job gis_ingest
    python -m etl.scripts.run_local --job full_refresh
"""

import argparse
import sys

from dagster import DagsterInstance


def main():
    parser = argparse.ArgumentParser(description="Run a Dagster job locally")
    parser.add_argument(
        "--job",
        required=True,
        choices=["dld_ingest", "gis_ingest", "geo_enrichment", "full_refresh"],
    )
    parser.add_argument("--batch-id", default="", help="Override batch/run ID")
    args = parser.parse_args()

    from etl.definitions import defs

    job = defs.get_job_def(args.job)
    run_config = {}
    if args.batch_id:
        run_config = {"ops": {"config": {"batch_id": args.batch_id}}}

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
