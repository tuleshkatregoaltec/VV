from __future__ import annotations

from dagster import Definitions

from holocron.orchestration.factory import (
    build_assets_for_source,
    build_operational_jobs,
    build_operational_schedules,
    build_pf_listing_media_assets,
    build_reelly_document_assets,
)
from holocron.orchestration.news import news_sync_asset, news_sync_job
from holocron.platform.resources import ClickHouseResource, S3Resource
from holocron.sources import registry

_assets = []
for _source in registry.all():
    _assets.extend(build_assets_for_source(_source))
_assets.extend(build_pf_listing_media_assets())
_assets.extend(build_reelly_document_assets())
_sources_by_name = {_source.name: _source for _source in registry.all()}
_jobs = build_operational_jobs(_sources_by_name)
_schedules = build_operational_schedules({_job.name: _job for _job in _jobs})
_assets.append(news_sync_asset)
_jobs.append(news_sync_job)

defs = Definitions(
    assets=_assets,
    jobs=_jobs,
    schedules=_schedules,
    resources={
        "s3": S3Resource(),
        "clickhouse": ClickHouseResource(),
    },
)
