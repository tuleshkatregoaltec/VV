import hashlib
import logging
from datetime import datetime
from io import BytesIO

from fastapi import HTTPException, UploadFile
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.core.cache import RedisCache
from app.core.s3 import S3Client
from app.db.models.news import NewsArticle
from app.schemas.news import NewsArticleResponse
from app.schemas.upload import (
    NewsArticleCreate,
    NewsArticleUploadResponse,
    ChunkedUploadResponse,
)

logger = logging.getLogger(__name__)


s3_client = S3Client(
    endpoint_url=settings.R2_ENDPOINT_URL,
    access_key_id=settings.R2_ACCESS_KEY_ID,
    secret_access_key=settings.R2_SECRET_ACCESS_KEY,
    bucket_name=settings.R2_BUCKET_NAME,
    region=settings.R2_REGION,
)


cache = RedisCache(settings.REDIS_URL, settings.REDIS_PASSWORD)


def sanitize_filename(filename: str) -> str:
    safe = "".join(c for c in filename if c.isalnum() or c in "._-")
    if not safe or ".." in safe:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return safe


def calculate_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def create_news_article(
    db: AsyncSession,
    article_data: NewsArticleCreate,
) -> NewsArticleUploadResponse:
    stmt = select(NewsArticle).where(NewsArticle.url == article_data.url)
    result = await db.exec(stmt)
    existing_article = result.first()

    if existing_article:
        return NewsArticleUploadResponse(
            created=False,
            article=NewsArticleResponse(
                id=existing_article.id,
                url=existing_article.url,
                headline=existing_article.headline,
                thumbnail_url=existing_article.thumbnail_url or "",
                thumbnail_base64=existing_article.thumbnail_base64,
                publish_date=existing_article.publish_date,
            ),
            message="Article already exists in database",
        )

    news_article = NewsArticle(**article_data.model_dump())
    db.add(news_article)
    await db.commit()
    await db.refresh(news_article)

    return NewsArticleUploadResponse(
        created=True,
        article=NewsArticleResponse(
            id=news_article.id,
            url=news_article.url,
            headline=news_article.headline,
            thumbnail_url=news_article.thumbnail_url or "",
            thumbnail_base64=news_article.thumbnail_base64,
            publish_date=news_article.publish_date,
        ),
        message="Article created successfully",
    )


async def process_chunked_upload(
    chunk: UploadFile,
    source_url: str,
    upload_session_id: str,
    chunk_index: int,
    total_chunks: int,
    original_filename: str,
    total_file_size: int,
    chunk_size: int,
) -> ChunkedUploadResponse:
    if not 1 <= chunk_index <= total_chunks:
        raise HTTPException(400, f"Invalid chunk_index: {chunk_index}")

    safe_filename = sanitize_filename(original_filename)

    chunk_data = await chunk.read()

    s3_key = f"uploads/{upload_session_id}/chunk_{chunk_index:04d}"
    await s3_client.upload(s3_key, chunk_data)

    if not cache.redis:
        raise HTTPException(503, "Redis unavailable")

    redis_key = f"upload:{upload_session_id}"
    await cache.ensure_auth()
    await cache.redis.sadd(redis_key, chunk_index)  # type: ignore
    await cache.redis.expire(redis_key, 3600)  # type: ignore

    logger.info(
        f"Chunk {chunk_index}/{total_chunks} uploaded to S3 for {safe_filename}"
    )

    received_count = await cache.redis.scard(redis_key)  # type: ignore

    if received_count < total_chunks:
        return ChunkedUploadResponse(
            status="chunk_received",
            chunk_index=chunk_index,
            total_chunks=total_chunks,
        )

    logger.info(f"All {total_chunks} chunks received, assembling {safe_filename}")

    try:
        assembled_data = BytesIO()
        for i in range(1, total_chunks + 1):
            chunk_key = f"uploads/{upload_session_id}/chunk_{i:04d}"
            chunk_bytes = await s3_client.download(chunk_key)
            if chunk_bytes is None:
                raise HTTPException(500, f"Missing chunk {i} from S3")
            assembled_data.write(chunk_bytes)

        final_data = assembled_data.getvalue()
        actual_size = len(final_data)

        if actual_size != total_file_size:
            raise HTTPException(
                500, f"Size mismatch: expected {total_file_size}, got {actual_size}"
            )

        file_hash = calculate_hash(final_data)

        date_prefix = datetime.now().strftime("%Y-%m-%d")
        final_key = f"files/{date_prefix}/{safe_filename}"
        await s3_client.upload(final_key, final_data)

        chunk_keys = [
            f"uploads/{upload_session_id}/chunk_{i:04d}"
            for i in range(1, total_chunks + 1)
        ]
        await s3_client.delete_many(chunk_keys)

        await cache.delete(redis_key)

        logger.info(
            f"Assembled {safe_filename} ({actual_size:,} bytes) from {total_chunks} chunks"
        )

        return ChunkedUploadResponse(
            status="completed",
            filename=safe_filename,
            size=actual_size,
            hash=file_hash,
            path=f"{date_prefix}/{safe_filename}",
            source_url=source_url,
            uploaded_at=datetime.now().isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to assemble {safe_filename}")
        raise HTTPException(500, f"Assembly failed: {e}")
