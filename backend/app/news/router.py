from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession
from app.core.dependencies import require_active_subscription, AuthContext
from app.postgres import get_db_session
from app.core.decorators import cached_endpoint
from app.news.service import fetch_news_articles
from app.news.models import NewsListResponse

router = APIRouter(prefix="/api/v1/news", tags=["news"])


@router.get("/articles", response_model=NewsListResponse)
@cached_endpoint(prefix="news", expire=600)
async def get_news(
    context: AuthContext = Depends(require_active_subscription),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    return await fetch_news_articles(db, limit, offset)
