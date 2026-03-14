from dagster import define_asset_job, AssetSelection

full_refresh_job = define_asset_job(
    name="full_refresh",
    selection=(AssetSelection.groups("dld", "gis", "geo", "validations")),
    description="Run all ingest pipelines in dependency order.",
)
