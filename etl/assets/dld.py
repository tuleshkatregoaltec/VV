"""DLD batch ingestion assets.

Flow:
  raw_dld_files → ch_transactions, ch_rent_contracts, ch_buildings,
                  ch_units, ch_projects, ch_developers, ch_land_registry
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dagster import AssetExecutionContext, Config, Output, asset

from etl.lib.dataset_specs import DLD_FILES, DLD_BY_FILENAME
from etl.lib.manifests import Manifest, build_file_entry, new_run_id
from etl.lib.paths import dld_manifest_key, dld_raw_key
from etl.lib.scrapers.dld import download_all as dld_download_all
from etl.resources.clickhouse import ClickHouseResource
from etl.resources.s3 import S3Resource


class DLDConfig(Config):
    batch_id: str = ""
    download_workers: int = 4
    skip_preflight: bool = False


@asset(group_name="dld")
def raw_dld_files(
    context: AssetExecutionContext,
    config: DLDConfig,
    s3: S3Resource,
) -> Output[dict]:
    """Download DLD CSVs from Dubai Pulse, upload to S3, write manifest."""
    batch_id = config.batch_id or new_run_id()
    context.log.info(f"DLD ingest batch_id={batch_id}")

    file_entries = []

    with tempfile.TemporaryDirectory() as tmpdir:
        results = dld_download_all(
            dest_dir=Path(tmpdir),
            workers=config.download_workers,
            skip_preflight=config.skip_preflight,
        )

        for result in results:
            spec = DLD_BY_FILENAME.get(result.canonical_name)
            if spec is None:
                context.log.warning(f"No dataset spec for {result.canonical_name}, skipping")
                continue
            s3_key = dld_raw_key(batch_id, spec.filename)
            s3.upload_file(result.local_path, s3_key)
            entry = build_file_entry(result.local_path, s3_key)
            file_entries.append(entry)
            context.log.info(f"Uploaded {spec.filename} ({entry.size_bytes:,} bytes)")

        manifest = Manifest(
            dataset="dld",
            run_id=batch_id,
            source="dubaipulse.gov.ae",
            created_at=datetime.now(timezone.utc).isoformat(),
            files=file_entries,
        )
        s3.put_json(dld_manifest_key(batch_id), manifest.to_json())

    return Output(
        value={
            "batch_id": batch_id,
            "file_count": len(file_entries),
            "files": [
                {"name": e.name, "s3_key": e.s3_key, "size_bytes": e.size_bytes}
                for e in file_entries
            ],
        },
        metadata={"batch_id": batch_id, "file_count": len(file_entries)},
    )


# ---------------------------------------------------------------------------
# ClickHouse load assets — asset name = ClickHouse table name
# ---------------------------------------------------------------------------


def _make_ch_dld_asset(filename: str, ch_table: str):
    @asset(name=ch_table, group_name="dld")
    def _asset(
        context: AssetExecutionContext,
        raw_dld_files: dict,
        s3: S3Resource,
        clickhouse: ClickHouseResource,
    ) -> Output[int]:
        batch_id = raw_dld_files["batch_id"]
        s3_key = dld_raw_key(batch_id, filename)
        url = s3.s3_url(s3_key)
        context.log.info(f"Loading {ch_table} from {url}")
        count = clickhouse.load_table_from_s3(
            table=ch_table,
            s3_url=url,
            aws_access_key_id=s3.aws_access_key_id,
            aws_secret_access_key=s3.aws_secret_access_key,
        )
        return Output(value=count, metadata={"row_count": count, "batch_id": batch_id})

    return _asset


DLD_CH_ASSETS = [_make_ch_dld_asset(spec.filename, spec.ch_table) for spec in DLD_FILES]
