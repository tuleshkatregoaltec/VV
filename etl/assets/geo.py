"""Geo enrichment assets.

Flow: raw_building_coordinates → ch_geo_buildings
      raw_project_polygons     → ch_geo_projects

raw_building_coordinates: URL-based stub (set GEO_BUILDINGS_URL env var).
raw_project_polygons: scraped from gis.dda.gov.ae layer 10.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dagster import AssetExecutionContext, Config, Output, asset

from etl.lib.manifests import Manifest, build_file_entry, new_run_id
from etl.lib.paths import geo_manifest_key, geo_raw_key
from etl.lib.scrapers.dda_gis import scrape_projects
from etl.resources.clickhouse import ClickHouseResource
from etl.resources.http import HttpClientResource
from etl.resources.s3 import S3Resource


class GeoConfig(Config):
    run_id: str = ""


def _make_raw_geo_asset(
    asset_name: str,
    filename: str,
    url_env_var: str,
    source: str,
    log_label: str,
):
    @asset(name=asset_name, group_name="geo")
    def _asset(
        context: AssetExecutionContext,
        config: GeoConfig,
        s3: S3Resource,
        http: HttpClientResource,
    ) -> Output[dict]:
        run_id = config.run_id or new_run_id()
        context.log.info(f"Geo {log_label} run_id={run_id}")
        url = os.environ.get(url_env_var, "")
        if not url:
            raise NotImplementedError(f"{url_env_var} not set.")
        with tempfile.TemporaryDirectory() as tmpdir:
            resp = http.get(url)
            path = Path(tmpdir) / filename
            path.write_bytes(resp.content)
            s3_key = geo_raw_key(run_id, filename)
            s3.upload_file(path, s3_key)
            entry = build_file_entry(path, s3_key)
            manifest = Manifest(
                dataset="geo",
                run_id=run_id,
                source=source,
                created_at=datetime.now(timezone.utc).isoformat(),
                files=[entry],
            )
            s3.put_json(geo_manifest_key(run_id), manifest.to_json())
        return Output(value={"run_id": run_id, "s3_key": s3_key}, metadata={"run_id": run_id})

    return _asset


raw_building_coordinates = _make_raw_geo_asset(
    "raw_building_coordinates",
    "building_coordinates.csv",
    "GEO_BUILDINGS_URL",
    "geo_api_buildings",
    "building coordinates",
)


@asset(group_name="geo")
def raw_project_polygons(
    context: AssetExecutionContext,
    config: GeoConfig,
    s3: S3Resource,
) -> Output[dict]:
    """Scrape DDA GIS project polygons (layer 10), upload CSV to S3, write manifest."""
    run_id = config.run_id or new_run_id()
    context.log.info(f"Geo project polygons run_id={run_id}")

    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "project_polygons.csv"
        asyncio.run(scrape_projects(output=output))

        s3_key = geo_raw_key(run_id, "project_polygons.csv")
        s3.upload_file(output, s3_key)
        entry = build_file_entry(output, s3_key)
        context.log.info(f"Uploaded project_polygons.csv ({entry.size_bytes:,} bytes)")

        manifest = Manifest(
            dataset="geo",
            run_id=run_id,
            source="gis.dda.gov.ae",
            created_at=datetime.now(timezone.utc).isoformat(),
            files=[entry],
        )
        s3.put_json(geo_manifest_key(run_id), manifest.to_json())

    return Output(
        value={"run_id": run_id, "s3_key": s3_key, "size_bytes": entry.size_bytes},
        metadata={"run_id": run_id, "size_bytes": entry.size_bytes},
    )


@asset(group_name="geo")
def ch_geo_buildings(
    context: AssetExecutionContext,
    raw_building_coordinates: dict,
    s3: S3Resource,
    clickhouse: ClickHouseResource,
) -> Output[int]:
    run_id = raw_building_coordinates["run_id"]
    s3_key = geo_raw_key(run_id, "building_coordinates.csv")
    count = clickhouse.load_table_from_s3(
        table="ch_geo_buildings",
        s3_url=s3.s3_url(s3_key),
        aws_access_key_id=s3.aws_access_key_id,
        aws_secret_access_key=s3.aws_secret_access_key,
    )
    return Output(value=count, metadata={"row_count": count, "run_id": run_id})


@asset(group_name="geo")
def ch_geo_projects(
    context: AssetExecutionContext,
    raw_project_polygons: dict,
    s3: S3Resource,
    clickhouse: ClickHouseResource,
) -> Output[int]:
    run_id = raw_project_polygons["run_id"]
    s3_key = geo_raw_key(run_id, "project_polygons.csv")
    count = clickhouse.load_table_from_s3(
        table="ch_geo_projects",
        s3_url=s3.s3_url(s3_key),
        aws_access_key_id=s3.aws_access_key_id,
        aws_secret_access_key=s3.aws_secret_access_key,
    )
    return Output(value=count, metadata={"row_count": count, "run_id": run_id})
