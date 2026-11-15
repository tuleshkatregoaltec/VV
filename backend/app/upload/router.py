import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.dependencies import require_api_key
from app.news.ingestion import create_news_article
from app.news.models import NewsArticleUploadRequest, NewsArticleUploadResponse
from app.postgres import get_db_session
from app.upload.models import ChunkedUploadResponse, UploadHealthResponse
from app.upload.service import process_chunked_upload

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/upload",
    tags=["upload"],
    dependencies=[Depends(require_api_key)],
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
    expected_hash: Annotated[str | None, Query()] = None,
) -> ChunkedUploadResponse:
    """
    Upload file chunks. Stores chunks to object storage for ETL node assembly.

    When all chunks are received, saves metadata.json with upload info.
    The ETL node is responsible for downloading, assembling, and verifying.
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
            expected_hash=expected_hash,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to process chunked upload")
        raise HTTPException(500, "Failed to process chunked upload")


@router.post("/news/article", response_model=NewsArticleUploadResponse)
async def upload_news_article(
    request: NewsArticleUploadRequest,
    db: AsyncSession = Depends(get_db_session),
) -> NewsArticleUploadResponse:
    try:
        return await create_news_article(db, request.article)
    except Exception:
        logger.exception("Failed to upload news article")
        raise HTTPException(500, "Failed to upload news article")


@router.get("/health", response_model=UploadHealthResponse)
async def health():
    """Service-key-only dependency check. Read-only: no object is written, and failures
    are logged server-side, never echoed to the caller."""
    from app.upload.service import cache, object_storage_client

    s3_ok = False
    try:
        async with object_storage_client.client() as s3:
            await s3.head_bucket(Bucket=object_storage_client.bucket_name)
        s3_ok = True
    except Exception:
        logger.exception("Object storage health check failed")

    redis_ok = await cache.ping()
    healthy = s3_ok and redis_ok
    return JSONResponse(
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "healthy" if healthy else "degraded", "s3": s3_ok, "redis": redis_ok},
    )
