from etl.orchestration.jobs import (
    dld_ingest_job,
    dxbi_ingest_job,
    full_refresh_job,
    geo_enrichment_job,
    gis_ingest_job,
    gis_smoke_job,
)
from etl.orchestration.source_registry import schedule_defs_by_job_name

_JOBS_BY_NAME = {
    "dld_ingest": dld_ingest_job,
    "dxbi_ingest": dxbi_ingest_job,
    "gis_ingest": gis_ingest_job,
    "gis_smoke": gis_smoke_job,
    "geo_enrichment": geo_enrichment_job,
    "full_refresh": full_refresh_job,
}

schedules = schedule_defs_by_job_name(_JOBS_BY_NAME)
