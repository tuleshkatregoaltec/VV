import hashlib
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse

from app.routers.dependencies import require_api_key

UPLOAD_DIR = Path("/data/uploads")
CHUNK_SIZE = 1024 * 1024

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/upload",
    tags=["upload"],
    dependencies=[Depends(require_api_key)],
)


async def calculate_file_hash(filepath: Path) -> str:
    sha256_hash = hashlib.sha256()
    async with aiofiles.open(filepath, "rb") as f:
        while chunk := await f.read(8192):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


@router.post("/file")
async def upload_file(
    file: UploadFile,
    source_url: Annotated[str | None, Query()] = None,
):
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Filename is required"
        )

    base_filename = os.path.basename(file.filename)
    safe_filename = "".join(c for c in base_filename if c.isalnum() or c in "._-")

    if not safe_filename or ".." in safe_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename"
        )

    date_str = datetime.now().strftime("%Y-%m-%d")
    upload_dir = UPLOAD_DIR / date_str
    upload_dir.mkdir(parents=True, exist_ok=True)

    filepath = upload_dir / safe_filename
    temp_filepath = filepath.with_suffix(filepath.suffix + ".tmp")

    try:
        total_size = 0
        async with aiofiles.open(temp_filepath, "wb") as out_file:
            while chunk := await file.read(CHUNK_SIZE):
                await out_file.write(chunk)
                total_size += len(chunk)

        file_hash = await calculate_file_hash(temp_filepath)
        shutil.move(str(temp_filepath), str(filepath))

        logger.info(
            f"File uploaded: {safe_filename} ({total_size:,} bytes) from {source_url or 'unknown'}"
        )

        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "filename": safe_filename,
                "size": total_size,
                "hash": file_hash,
                "path": str(filepath.relative_to(UPLOAD_DIR)),
                "source_url": source_url,
                "uploaded_at": datetime.now().isoformat(),
            },
        )

    except Exception as e:
        if temp_filepath.exists():
            temp_filepath.unlink()
        logger.exception(f"Failed to upload file: {safe_filename}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}",
        )


health_router = APIRouter(prefix="/api/v1/upload", tags=["upload"])


@health_router.get("/health")
async def upload_health():
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        test_file = UPLOAD_DIR / ".health_check"
        test_file.touch()
        test_file.unlink()
        writable = True
    except Exception:
        writable = False

    return {
        "status": "healthy" if writable else "degraded",
        "upload_dir": str(UPLOAD_DIR),
        "writable": writable,
    }
