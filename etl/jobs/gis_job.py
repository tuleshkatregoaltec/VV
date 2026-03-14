from dagster import define_asset_job, AssetSelection

gis_ingest_job = define_asset_job(
    name="gis_ingest",
    selection=AssetSelection.groups("gis") | AssetSelection.assets("validate_gis"),
    description="Scrape GIS plots → S3 → ClickHouse → validate.",
)
