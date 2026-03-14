from dagster import define_asset_job, AssetSelection

geo_enrichment_job = define_asset_job(
    name="geo_enrichment",
    selection=AssetSelection.groups("geo") | AssetSelection.assets("validate_geo"),
    description="Fetch building coordinates + project polygons → S3 → ClickHouse → validate.",
)
