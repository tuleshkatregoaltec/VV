import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_db_session
from app.routers.dependencies import require_api_key
from app.schemas.upload import (
    NewsArticleUploadRequest,
    NewsArticleUploadResponse,
    ChunkedUploadResponse,
)
from app.services.upload_service import create_news_article, process_chunked_upload

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/upload",
    tags=["upload"],
    dependencies=[Depends(require_api_key)],
)

health_router = APIRouter(
    prefix="/api/v1/upload",
    tags=["upload"],
)


@router.post("/chunked", response_model=ChunkedUploadResponse)
async def upload_chunked(
    chunk: UploadFile,
    source_url: Annotated[str, Query()],
    upload_session_id: Annotated[str, Query()],
    chunk_index: Annotated[int, Query()],
    total_chunks: Annotated[int, Query()],
    original_filename: Annotated[str, Query()],
    total_file_size: Annotated[int, Query()],
    chunk_size: Annotated[int, Query()],
) -> ChunkedUploadResponse:
    """
    Upload file chunks. Assembles final file when all chunks are received.
    """
    try:
        return await process_chunked_upload(
            chunk=chunk,
            source_url=source_url,
            upload_session_id=upload_session_id,
            chunk_index=chunk_index,
            total_chunks=total_chunks,
            original_filename=original_filename,
            total_file_size=total_file_size,
            chunk_size=chunk_size,
        )
    except Exception as e:
        logger.exception("Failed to process chunked upload")
        raise HTTPException(500, f"Failed to process chunked upload: {e}")


@router.post("/news/article", response_model=NewsArticleUploadResponse)
async def upload_news_article(
    request: NewsArticleUploadRequest,
    db: AsyncSession = Depends(get_db_session),
) -> NewsArticleUploadResponse:

    try:
        return await create_news_article(db, request.article)
    except Exception as e:
        logger.exception("Failed to upload news article")
        raise HTTPException(500, f"Failed to upload news article: {e}")


@health_router.get("/health")
async def health():
    from app.services.upload_service import s3_client, cache

    try:
        # Test S3 connection by uploading and deleting a test file
        test_key = ".health_check"
        test_data = b"health_check"
        await s3_client.upload(test_key, test_data)
        await s3_client.delete_many([test_key])

        # Test Redis connection
        redis_ok = False
        if cache.redis:
            await cache.redis.ping()
            redis_ok = True

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "healthy", "s3": True, "redis": redis_ok},
        )
    except Exception as e:
        logger.exception("Health check failed")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "error": str(e)},
        )
