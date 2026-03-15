"""Geo reference release assets."""

import os
import tempfile
from pathlib import Path

from dagster import AssetExecutionContext, Config, Output, asset

from etl.core.dataset_registry import DATASET_SPECS, GEO_TABLES
from etl.core.load_strategies import load_table_from_release
from etl.core.releases import ReleaseManifest, build_file_artifact, new_release_id, utc_now_iso
from etl.lib.paths import geo_manifest_key, geo_raw_key
from etl.resources.clickhouse import ClickHouseResource
from etl.resources.http import HttpClientResource
from etl.resources.s3 import S3Resource


class GeoConfig(Config):
    release_id: str = ""


@asset(group_name="geo")
def raw_building_coordinates(
    context: AssetExecutionContext,
    config: GeoConfig,
    s3: S3Resource,
    http: HttpClientResource,
) -> Output[dict]:
    release_id = config.release_id or new_release_id()
    url = os.environ.get("GEO_BUILDINGS_URL", "")
    if not url:
        raise NotImplementedError("GEO_BUILDINGS_URL not set.")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / GEO_TABLES[0].filename
        response = http.get(url)
        path.write_bytes(response.content)
        s3_key = geo_raw_key(release_id, GEO_TABLES[0].filename)
        s3.upload_file(path, s3_key)
        artifact = build_file_artifact(path, s3_key=s3_key, table_name=GEO_TABLES[0].table_name)

    dataset_spec = DATASET_SPECS["geo"]
    manifest = ReleaseManifest(
        dataset=dataset_spec.dataset,
        release_id=release_id,
        mode=dataset_spec.mode,
        source=dataset_spec.source,
        created_at=utc_now_iso(),
        files=[artifact],
    )
    s3.put_json(geo_manifest_key(release_id), manifest.to_json())
    return Output(value=manifest.model_dump(mode="json"), metadata={"release_id": release_id})


@asset(name="geo_buildings", group_name="geo")
def geo_buildings(
    context: AssetExecutionContext,
    raw_building_coordinates: dict,
    s3: S3Resource,
    clickhouse: ClickHouseResource,
) -> Output[int]:
    release_id = raw_building_coordinates["release_id"]
    count = load_table_from_release(
        clickhouse=clickhouse,
        s3=s3,
        table_spec=GEO_TABLES[0],
        s3_key=geo_raw_key(release_id, GEO_TABLES[0].filename),
        release_id=release_id,
    )
    return Output(value=count, metadata={"row_count": count, "release_id": release_id})
