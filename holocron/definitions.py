"""Top-level Dagster definitions for Holocron."""

from __future__ import annotations

import os

from dagster import Definitions, EnvVar

from holocron.assets.pf_locations import pf_location_hierarchy
from holocron.framework.dagster_factory import (
    build_assets_for_source,
    build_cleanup_job_for_source,
    build_job_for_source,
    build_schedule_for_source,
)
from holocron.resources.clickhouse import ClickHouseResource
from holocron.resources.http import HttpClientResource
from holocron.resources.local_release import LocalReleaseStorageResource
from holocron.resources.s3 import S3Resource
from holocron.sources import SOURCES

all_assets = []
jobs = []
schedules = []

for source in SOURCES:
    all_assets.extend(build_assets_for_source(source))
    job = build_job_for_source(source)
    jobs.append(job)
    jobs.append(build_cleanup_job_for_source(source))
    schedule = build_schedule_for_source(source, job)
    if schedule:
        schedules.append(schedule)

defs = Definitions(
    assets=[*all_assets, pf_location_hierarchy],
    jobs=jobs,
    schedules=schedules,
    resources={
        "s3": S3Resource(
            bucket=EnvVar("S3_BUCKET"),
            region=EnvVar("AWS_REGION"),
            endpoint_url=os.environ.get("S3_ENDPOINT_URL", ""),
            use_path_style=os.environ.get("S3_USE_PATH_STYLE", "false").lower() == "true",
            aws_access_key_id=EnvVar("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=EnvVar("AWS_SECRET_ACCESS_KEY"),
        ),
        "clickhouse": ClickHouseResource(
            host=EnvVar("CLICKHOUSE_HOST"),
            port=int(os.environ.get("CLICKHOUSE_PORT", "8443")),
            user=EnvVar("CLICKHOUSE_USER"),
            password=EnvVar("CLICKHOUSE_PASSWORD"),
            database=EnvVar("CLICKHOUSE_DATABASE"),
            secure=os.environ.get("CLICKHOUSE_SECURE", "true").lower() == "true",
        ),
        "http": HttpClientResource(),
        "local_storage": LocalReleaseStorageResource(
            root_dir=os.environ.get("LOCAL_RELEASES_DIR", "/var/lib/holocron/releases")
        ),
    },
)
