#!/usr/bin/env python3
"""
Reload ClickHouse tables from existing S3 manifests.

Usage:
    python -m etl.scripts.backfill --dataset dld --batch-id 2026-03-13T06-00-00Z
"""

import argparse
import os
import sys

from etl.resources.clickhouse import ClickHouseResource
from etl.resources.s3 import S3Resource
from etl.lib.manifests import Manifest
from etl.lib.paths import dld_manifest_key, dld_raw_key, gis_manifest_key, geo_manifest_key
from etl.lib.dataset_specs import DLD_FILES, GIS_FILES, GEO_FILES


def get_resources():
    s3 = S3Resource(
        bucket=os.environ["S3_BUCKET"],
        region=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", ""),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
    )
    ch = ClickHouseResource(
        host=os.environ["CLICKHOUSE_HOST"],
        port=int(os.environ.get("CLICKHOUSE_PORT", "8443")),
        user=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        database=os.environ.get("CLICKHOUSE_DATABASE", "default"),
        secure=os.environ.get("CLICKHOUSE_SECURE", "true").lower() == "true",
    )
    return s3, ch


def backfill_dld(s3: S3Resource, ch: ClickHouseResource, batch_id: str):
    raw = s3.get_json(dld_manifest_key(batch_id))
    manifest = Manifest.from_dict(raw)
    print(f"Loaded manifest for batch {batch_id} with {len(manifest.files)} files")

    for spec in DLD_FILES:
        url = s3.s3_url(dld_raw_key(batch_id, spec.filename))
        print(f"Loading {spec.ch_table} from {url}")
        count = ch.load_table_from_s3(
            table=spec.ch_table,
            s3_url=url,
            aws_access_key_id=s3.aws_access_key_id,
            aws_secret_access_key=s3.aws_secret_access_key,
        )
        print(f"  → {count:,} rows")


def main():
    parser = argparse.ArgumentParser(description="Backfill ClickHouse from S3")
    parser.add_argument("--dataset", required=True, choices=["dld", "gis", "geo"])
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()

    s3, ch = get_resources()

    if args.dataset == "dld":
        backfill_dld(s3, ch, args.batch_id)
    else:
        print(f"Backfill for {args.dataset} not yet implemented.")
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
