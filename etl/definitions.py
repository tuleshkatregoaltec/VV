"""Top-level Dagster definitions."""

from __future__ import annotations

import os

from dagster import Definitions, EnvVar

from etl.orchestration.jobs import (
    dld_ingest_job,
    dxbi_ingest_job,
    full_refresh_job,
    geo_enrichment_job,
    gis_ingest_job,
    gis_smoke_job,
)
from etl.orchestration.schedules import schedules
from etl.orchestration.source_registry import all_source_assets
from etl.resources.s3 import S3Resource
from etl.resources.clickhouse import ClickHouseResource
from etl.resources.http import HttpClientResource

all_assets = all_source_assets()

defs = Definitions(
    assets=all_assets,
    jobs=[
        dld_ingest_job,
        dxbi_ingest_job,
        gis_ingest_job,
        gis_smoke_job,
        geo_enrichment_job,
        full_refresh_job,
    ],
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
    },
)
