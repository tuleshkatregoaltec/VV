from dagster import define_asset_job, AssetSelection

dld_ingest_job = define_asset_job(
    name="dld_ingest",
    selection=AssetSelection.groups("dld") | AssetSelection.assets("validate_dld"),
    description="Fetch DLD CSVs → S3 → ClickHouse → validate.",
)
