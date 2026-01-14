from pydantic import BaseModel
from datetime import date


class NewsArticleCreate(BaseModel):
    url: str
    headline: str
    thumbnail_url: str | None = None
    thumbnail_base64: str | None = None
    publish_date: date | None = None


class NewsArticleResponse(BaseModel):
    id: int
    url: str
    headline: str
    thumbnail_url: str
    thumbnail_base64: str | None
    publish_date: date | None


class NewsListResponse(BaseModel):
    articles: list[NewsArticleResponse]
    total: int
    limit: int
    offset: int


class NewsUploadRequest(BaseModel):
    articles: list[NewsArticleCreate]


class NewsUploadResponse(BaseModel):
    created: int
    skipped: int
    total: int
