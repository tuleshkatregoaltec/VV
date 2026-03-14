"""Top-level Dagster Definitions — loaded by workspace.yaml."""

from __future__ import annotations

import os

from dagster import Definitions, EnvVar, ScheduleDefinition

from etl.assets.dld import raw_dld_files, DLD_CH_ASSETS
from etl.assets.gis import raw_gis_plots, ch_gis_land_plots
from etl.assets.geo import (
    raw_building_coordinates,
    ch_geo_buildings,
    raw_project_polygons,
    ch_geo_projects,
)
from etl.assets.validations import validate_dld, validate_gis, validate_geo
from etl.jobs.dld_job import dld_ingest_job
from etl.jobs.gis_job import gis_ingest_job
from etl.jobs.geo_job import geo_enrichment_job
from etl.jobs.full_refresh_job import full_refresh_job
from etl.resources.s3 import S3Resource
from etl.resources.clickhouse import ClickHouseResource
from etl.resources.http import HttpClientResource

all_assets = [
    raw_dld_files,
    *DLD_CH_ASSETS,
    raw_gis_plots,
    ch_gis_land_plots,
    raw_building_coordinates,
    ch_geo_buildings,
    raw_project_polygons,
    ch_geo_projects,
    validate_dld,
    validate_gis,
    validate_geo,
]

schedules = [
    ScheduleDefinition(
        job=dld_ingest_job,
        cron_schedule="0 6 * * *",  # daily 06:00 UTC
        name="dld_daily",
    ),
    ScheduleDefinition(
        job=gis_ingest_job,
        cron_schedule="0 7 * * 1",  # weekly Monday 07:00 UTC
        name="gis_weekly",
    ),
]

defs = Definitions(
    assets=all_assets,
    jobs=[dld_ingest_job, gis_ingest_job, geo_enrichment_job, full_refresh_job],
    schedules=schedules,
    resources={
        "s3": S3Resource(
            bucket=EnvVar("S3_BUCKET"),
            region=EnvVar("AWS_REGION"),
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
