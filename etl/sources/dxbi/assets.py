"""DXBI release assets."""

import tempfile
from pathlib import Path

from dagster import AssetExecutionContext, Config, Output, asset

from etl.core.dataset_registry import DATASET_SPECS, DXBI_TABLES, table_by_filename
from etl.core.load_strategies import load_table_from_release
from etl.core.releases import ReleaseManifest, build_file_artifact, new_release_id, utc_now_iso
from etl.lib.paths import dxbi_manifest_key, dxbi_raw_key
from etl.lib.scrapers.dxbi import download_all as dxbi_download_all
from etl.resources.clickhouse import ClickHouseResource
from etl.resources.s3 import S3Resource


class DXBIConfig(Config):
    release_id: str = ""


_DXBI_SPEC = DATASET_SPECS["dxbi"]
_DXBI_BY_FILENAME = table_by_filename("dxbi")


@asset(group_name="dxbi")
def raw_dxbi_files(
    context: AssetExecutionContext,
    config: DXBIConfig,
    s3: S3Resource,
) -> Output[dict]:
    release_id = config.release_id or new_release_id()
    context.log.info(f"DXBI release_id={release_id}")

    artifacts = []
    with tempfile.TemporaryDirectory() as tmpdir:
        results = dxbi_download_all(dest_dir=Path(tmpdir), run_id=release_id)
        for result in results:
            table_spec = _DXBI_BY_FILENAME.get(result.canonical_name)
            if table_spec is None:
                context.log.warning(f"No table spec for {result.canonical_name}, skipping")
                continue
            s3_key = dxbi_raw_key(release_id, table_spec.filename)
            s3.upload_file(result.local_path, s3_key)
            artifact = build_file_artifact(
                result.local_path,
                s3_key=s3_key,
                table_name=table_spec.table_name,
            )
            artifacts.append(artifact)
            context.log.info(
                f"Uploaded {table_spec.filename} ({artifact.size_bytes:,} bytes, {artifact.row_count:,} rows)"
            )

    manifest = ReleaseManifest(
        dataset=_DXBI_SPEC.dataset,
        release_id=release_id,
        mode=_DXBI_SPEC.mode,
        source=_DXBI_SPEC.source,
        created_at=utc_now_iso(),
        files=artifacts,
    )
    s3.put_json(dxbi_manifest_key(release_id), manifest.to_json())
    return Output(
        value=manifest.model_dump(mode="json"),
        metadata={"release_id": release_id, "file_count": len(artifacts)},
    )


def _make_dxbi_asset(table_spec):
    @asset(name=table_spec.table_name, group_name="dxbi")
    def _asset(
        context: AssetExecutionContext,
        raw_dxbi_files: dict,
        s3: S3Resource,
        clickhouse: ClickHouseResource,
    ) -> Output[int]:
        release_id = raw_dxbi_files["release_id"]
        s3_key = dxbi_raw_key(release_id, table_spec.filename)
        count = load_table_from_release(
            clickhouse=clickhouse,
            s3=s3,
            table_spec=table_spec,
            s3_key=s3_key,
            release_id=release_id,
        )
        return Output(value=count, metadata={"row_count": count, "release_id": release_id})

    return _asset


DXBI_TABLE_ASSETS = [_make_dxbi_asset(table_spec) for table_spec in DXBI_TABLES]
