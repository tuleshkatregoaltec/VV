from sqlmodel import SQLModel, Field
from typing import LiteralString, Optional
from datetime import date


class NewsArticle(SQLModel, table=True):
    __tablename__: LiteralString = "news_articles"

    id: int = Field(primary_key=True)

    url: str = Field(max_length=255)
    headline: str = Field(max_length=255)
    thumbnail_url: Optional[str] = Field(default=None, max_length=255)
    thumbnail_base64: Optional[str] = Field(default=None)
    publish_date: Optional[date] = None
