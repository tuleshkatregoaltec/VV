from pydantic import BaseModel
from datetime import datetime
from app.schemas.news import NewsArticleResponse


class NewsArticleCreate(BaseModel):
    url: str
    headline: str
    thumbnail_url: str | None = None
    thumbnail_base64: str | None = None
    publish_date: datetime | None = None


class NewsArticleUploadResponse(BaseModel):
    created: bool
    article: NewsArticleResponse | None = None
    message: str


class NewsArticleUploadRequest(BaseModel):
    article: NewsArticleCreate


class ChunkedUploadResponse(BaseModel):
    status: str
    chunk_index: int | None = None
    total_chunks: int | None = None
    filename: str | None = None
    size: int | None = None
    hash: str | None = None
    path: str | None = None
    source_url: str | None = None
    uploaded_at: str | None = None
