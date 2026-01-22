from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession
from app.routers.dependencies import require_auth
from app.postgres import get_db_session
from app.core.decorators import cached_endpoint
from app.services.news_service import fetch_news_articles
from app.schemas.news import NewsListResponse

router = APIRouter(
    prefix="/api/v1/news", tags=["news"], dependencies=[Depends(require_auth)]
)


@router.get("/articles", response_model=NewsListResponse)
@cached_endpoint(prefix="news", expire=600)
async def get_news(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    return await fetch_news_articles(db, limit, offset)
