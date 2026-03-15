#!/usr/bin/env python3
"""Reload ClickHouse tables from existing release manifests."""

import os
import argparse

from etl.core.dataset_registry import DATASET_SPECS, table_by_filename
from etl.core.load_strategies import load_table_from_release
from etl.core.releases import ReleaseManifest
from etl.lib.paths import manifest_key
from etl.orchestration.source_registry import SOURCE_BY_DATASET
from etl.resources.clickhouse import ClickHouseResource
from etl.resources.s3 import S3Resource


def get_resources():
    s3 = S3Resource(
        bucket=os.environ["S3_BUCKET"],
        region=os.environ.get("AWS_REGION", "us-east-1"),
        endpoint_url=os.environ.get("S3_ENDPOINT_URL", ""),
        use_path_style=os.environ.get("S3_USE_PATH_STYLE", "false").lower() == "true",
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


def backfill_dataset(s3: S3Resource, ch: ClickHouseResource, dataset: str, release_id: str) -> None:
    manifest = ReleaseManifest.model_validate(s3.get_json(manifest_key(dataset, release_id)))
    if dataset not in SOURCE_BY_DATASET:
        raise ValueError(f"Dataset {dataset} is not registered to any source")
    files_by_name = table_by_filename(dataset)
    print(f"Loaded {dataset} release {release_id} with {len(manifest.files)} files")

    for artifact in manifest.files:
        table_spec = files_by_name.get(artifact.name)
        if table_spec is None:
            print(f"Skipping unregistered artifact {artifact.name}")
            continue
        print(f"Loading {table_spec.table_name} from s3://{s3.bucket}/{artifact.s3_key}")
        count = load_table_from_release(
            clickhouse=ch,
            s3=s3,
            table_spec=table_spec,
            s3_key=artifact.s3_key,
            release_id=release_id,
        )
        print(f"  -> {count:,} rows")


def main():
    parser = argparse.ArgumentParser(description="Backfill ClickHouse from S3")
    parser.add_argument("--dataset", required=True, choices=sorted(DATASET_SPECS))
    parser.add_argument("--release-id", default="", help="Release ID to replay")
    parser.add_argument(
        "--batch-id", default="", help="Backward-compatible alias for DLD release IDs"
    )
    args = parser.parse_args()
    release_id = args.release_id or args.batch_id
    if not release_id:
        parser.error("One of --release-id or --batch-id is required")

    s3, ch = get_resources()
    backfill_dataset(s3, ch, args.dataset, release_id)
    print("Done.")


if __name__ == "__main__":
    main()
