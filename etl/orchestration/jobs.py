from dagster import define_asset_job

from etl.orchestration.source_registry import registered_job_specs

_JOB_DEFS = {
    job_name: define_asset_job(name=job_name, selection=selection, description=description)
    for job_name, selection, description in registered_job_specs()
}

dld_ingest_job = _JOB_DEFS["dld_ingest"]
dxbi_ingest_job = _JOB_DEFS["dxbi_ingest"]
gis_ingest_job = _JOB_DEFS["gis_ingest"]
gis_smoke_job = _JOB_DEFS["gis_smoke"]
geo_enrichment_job = _JOB_DEFS["geo_enrichment"]
full_refresh_job = _JOB_DEFS["full_refresh"]
