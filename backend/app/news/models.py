from typing import LiteralString, Optional
from datetime import datetime
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime


class NewsArticle(SQLModel, table=True):
    __tablename__: LiteralString = "news_articles"

    id: int = Field(primary_key=True)

    url: str = Field(max_length=255)
    headline: str = Field(max_length=255)
    thumbnail_url: Optional[str] = Field(default=None, max_length=255)
    thumbnail_base64: Optional[str] = Field(default=None)
    publish_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


from pydantic import BaseModel, AwareDatetime


class NewsArticleResponse(BaseModel):
    id: int
    url: str
    headline: str
    thumbnail_url: str
    thumbnail_base64: str | None
    publish_date: AwareDatetime | None


class NewsListResponse(BaseModel):
    articles: list[NewsArticleResponse]
    total: int
    limit: int
    offset: int
