"""GIS ingestion assets.

Flow: raw_gis_plots → ch_gis_land_plots
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dagster import AssetExecutionContext, Config, Output, asset

from etl.lib.manifests import Manifest, build_file_entry, new_run_id
from etl.lib.paths import gis_manifest_key, gis_raw_key
from etl.lib.scrapers.dda_gis import scrape as scrape_dda_plots
from etl.resources.clickhouse import ClickHouseResource
from etl.resources.s3 import S3Resource


class GISConfig(Config):
    run_id: str = ""
    concurrency: int = 15


@asset(group_name="gis")
def raw_gis_plots(
    context: AssetExecutionContext,
    config: GISConfig,
    s3: S3Resource,
) -> Output[dict]:
    """Scrape DDA GIS plots, upload CSV to S3, write manifest."""
    run_id = config.run_id or new_run_id()
    context.log.info(f"GIS ingest run_id={run_id}")

    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "dda_plots.csv"
        asyncio.run(scrape_dda_plots(output=output, concurrency=config.concurrency))

        s3_key = gis_raw_key(run_id, "dda_plots.csv")
        s3.upload_file(output, s3_key)
        entry = build_file_entry(output, s3_key)
        context.log.info(f"Uploaded dda_plots.csv ({entry.size_bytes:,} bytes)")

        manifest = Manifest(
            dataset="gis",
            run_id=run_id,
            source="gis.dda.gov.ae",
            created_at=datetime.now(timezone.utc).isoformat(),
            files=[entry],
        )
        s3.put_json(gis_manifest_key(run_id), manifest.to_json())

    return Output(
        value={"run_id": run_id, "s3_key": s3_key, "size_bytes": entry.size_bytes},
        metadata={"run_id": run_id, "size_bytes": entry.size_bytes},
    )


@asset(group_name="gis")
def ch_gis_land_plots(
    context: AssetExecutionContext,
    raw_gis_plots: dict,  # receives output value from raw_gis_plots asset
    s3: S3Resource,
    clickhouse: ClickHouseResource,
) -> Output[int]:
    """Load GIS land plots into ClickHouse from S3."""
    run_id = raw_gis_plots["run_id"]
    s3_key = gis_raw_key(run_id, "dda_plots.csv")
    url = s3.s3_url(s3_key)
    context.log.info(f"Loading gis_land_plots from {url}")
    count = clickhouse.load_table_from_s3(
        table="ch_gis_land_plots",
        s3_url=url,
        aws_access_key_id=s3.aws_access_key_id,
        aws_secret_access_key=s3.aws_secret_access_key,
    )
    return Output(value=count, metadata={"row_count": count, "run_id": run_id})
