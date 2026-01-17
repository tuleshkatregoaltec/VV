from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.models.news import NewsArticle
from app.schemas.news import NewsListResponse, NewsArticleResponse


async def fetch_news_articles(
    db: AsyncSession,
    limit: int = 20,
    offset: int = 0,
) -> NewsListResponse:
    """Fetch paginated news articles sorted by publish date."""
    stmt = (
        select(NewsArticle)
        .order_by(NewsArticle.publish_date.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.exec(stmt)
    articles = result.all()

    count_result = await db.exec(select(func.count()).select_from(NewsArticle))
    total = count_result.one()

    return NewsListResponse(
        articles=[NewsArticleResponse(**a.model_dump()) for a in articles],
        total=total,
        limit=limit,
        offset=offset,
    )
