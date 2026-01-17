from pydantic import BaseModel
from datetime import datetime


class NewsArticleResponse(BaseModel):
    id: int
    url: str
    headline: str
    thumbnail_url: str
    thumbnail_base64: str | None
    publish_date: datetime | None


class NewsListResponse(BaseModel):
    articles: list[NewsArticleResponse]
    total: int
    limit: int
    offset: int
