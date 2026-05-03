from dagster import (
    AssetExecutionContext,
    Config,
    Failure,
    MaterializeResult,
    MetadataValue,
    asset,
    define_asset_job,
)
from pydantic import Field

from holocron.domain.news import NewsSyncService, resolve_feed_urls
from holocron.platform.settings import Settings


class NewsSyncConfig(Config):
    feed_urls: list[str] = Field(
        default_factory=list,
        description="Optional feed URLs to prepend before NEWS_FEED_URLS.",
    )
    feed_urls_file: str = Field(
        default="",
        description="Optional file path with one feed URL per line.",
    )
    skip_thumbnail_upload: bool = Field(
        default=False,
        description="Use source thumbnail URLs instead of mirroring to object storage.",
    )


@asset(name="news_sync", group_name="news")
def news_sync_asset(
    context: AssetExecutionContext,
    config: NewsSyncConfig,
) -> MaterializeResult:
    runtime_settings = Settings()
    feed_urls = resolve_feed_urls(
        settings=runtime_settings,
        cli_urls=config.feed_urls,
        feed_urls_file=config.feed_urls_file,
    )
    if not feed_urls:
        raise Failure(
            "No feed URLs configured. Set NEWS_FEED_URLS or provide feed_urls/feed_urls_file in run config."
        )

    result = NewsSyncService(
        runtime_settings,
        skip_thumbnail_upload=config.skip_thumbnail_upload,
    ).sync(feed_urls)
    metadata = {
        "feeds_processed": result.feeds_processed,
        "articles_seen": result.articles_seen,
        "created": result.created,
        "skipped_existing": result.skipped_existing,
        "failed": result.failed,
        "feed_urls": MetadataValue.json(list(feed_urls)),
    }
    if result.failed:
        raise Failure(description="News sync completed with failures.", metadata=metadata)

    context.log.info(
        "news: sync complete feeds=%s seen=%s created=%s skipped_existing=%s failed=%s",
        result.feeds_processed,
        result.articles_seen,
        result.created,
        result.skipped_existing,
        result.failed,
    )
    return MaterializeResult(metadata=metadata)


news_sync_job = define_asset_job(
    name="news_sync_pipeline",
    selection=["news_sync"],
)
