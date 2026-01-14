import hashlib
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_db_session
from app.routers.dependencies import require_api_key
from app.schemas.news import NewsUploadRequest, NewsUploadResponse
from app.services.upload_service import bulk_create_news_articles

UPLOAD_DIR = Path("/data/uploads")
CHUNK_DIR = Path("/data/uploads/chunks")
CHUNK_SIZE = 1024 * 1024

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


def sanitize_filename(filename: str) -> str:
    safe = "".join(c for c in filename if c.isalnum() or c in "._-")
    if not safe or ".." in safe:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return safe


async def calculate_hash(filepath: Path) -> str:
    """Calculate SHA256 hash of file."""
    sha256 = hashlib.sha256()
    async with aiofiles.open(filepath, "rb") as f:
        while chunk := await f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


@router.post("/chunked")
async def upload_chunked(
    chunk: UploadFile,
    source_url: Annotated[str, Query()],
    upload_session_id: Annotated[str, Query()],
    chunk_index: Annotated[int, Query()],
    total_chunks: Annotated[int, Query()],
    original_filename: Annotated[str, Query()],
    total_file_size: Annotated[int, Query()],
    chunk_size: Annotated[int, Query()],
):
    if not 1 <= chunk_index <= total_chunks:
        raise HTTPException(400, f"Invalid chunk_index: {chunk_index}")

    safe_filename = sanitize_filename(original_filename)
    session_dir = CHUNK_DIR / sanitize_filename(upload_session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    chunk_path = session_dir / f"chunk_{chunk_index:04d}"

    async with aiofiles.open(chunk_path, "wb") as f:
        while data := await chunk.read(CHUNK_SIZE):
            await f.write(data)

    logger.info(f"Chunk {chunk_index}/{total_chunks} received for {safe_filename}")

    if chunk_index != total_chunks:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "chunk_received",
                "chunk_index": chunk_index,
                "total_chunks": total_chunks,
            },
        )

    missing = [
        i
        for i in range(1, total_chunks + 1)
        if not (session_dir / f"chunk_{i:04d}").exists()
    ]
    if missing:
        raise HTTPException(400, f"Missing chunks: {missing}")

    date_dir = UPLOAD_DIR / datetime.now().strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    final_path = date_dir / safe_filename
    temp_path = final_path.with_suffix(final_path.suffix + ".tmp")

    try:
        async with aiofiles.open(temp_path, "wb") as out:
            for i in range(1, total_chunks + 1):
                async with aiofiles.open(
                    session_dir / f"chunk_{i:04d}", "rb"
                ) as chunk_file:
                    while data := await chunk_file.read(CHUNK_SIZE):
                        await out.write(data)

        actual_size = temp_path.stat().st_size
        if actual_size != total_file_size:
            temp_path.unlink()
            raise HTTPException(
                500, f"Size mismatch: expected {total_file_size}, got {actual_size}"
            )

        file_hash = await calculate_hash(temp_path)
        shutil.move(str(temp_path), str(final_path))
        shutil.rmtree(session_dir, ignore_errors=True)

        logger.info(
            f"Assembled {safe_filename} ({actual_size:,} bytes) from {total_chunks} chunks"
        )

        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "completed",
                "filename": safe_filename,
                "size": actual_size,
                "hash": file_hash,
                "path": str(final_path.relative_to(UPLOAD_DIR)),
                "source_url": source_url,
                "uploaded_at": datetime.now().isoformat(),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        temp_path.unlink(missing_ok=True)
        logger.exception(f"Failed to assemble {safe_filename}")
        raise HTTPException(500, f"Assembly failed: {e}")


@router.post("/news", response_model=NewsUploadResponse)
async def upload_news_articles(
    request: NewsUploadRequest,
    db: AsyncSession = Depends(get_db_session),
) -> NewsUploadResponse:
    try:
        return await bulk_create_news_articles(db, request.articles)
    except Exception as e:
        logger.exception("Failed to upload news articles")
        raise HTTPException(500, f"Failed to upload news articles: {e}")


@health_router.get("/health")
async def health():
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        test = UPLOAD_DIR / ".health"
        test.touch()
        test.unlink()
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "healthy", "writable": True},
        )
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "writable": False},
        )
