import logging
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.models.news import NewsArticle
from app.schemas.news import NewsArticleCreate, NewsUploadResponse

logger = logging.getLogger(__name__)


async def bulk_create_news_articles(
    db: AsyncSession,
    articles: list[NewsArticleCreate],
) -> NewsUploadResponse:
    if not articles:
        return NewsUploadResponse(created=0, skipped=0, total=0)

    # Get existing URLs to skip duplicates
    urls = [article.url for article in articles]
    stmt = select(NewsArticle.url).where(NewsArticle.url.in_(urls))
    result = await db.exec(stmt)
    existing_urls = set(result.all())

    created_count = 0
    skipped_count = 0

    for article_data in articles:
        if article_data.url in existing_urls:
            skipped_count += 1
            continue

        news_article = NewsArticle(**article_data.model_dump())
        db.add(news_article)
        created_count += 1

    await db.commit()

    logger.info(
        f"Bulk news upload: {created_count} created, {skipped_count} skipped, "
        f"{len(articles)} total"
    )

    return NewsUploadResponse(
        created=created_count,
        skipped=skipped_count,
        total=len(articles),
    )
