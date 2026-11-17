import hashlib
import logging
import re
from datetime import datetime

from fastapi import HTTPException, UploadFile

from app.config import settings
from app.core.cache import RedisCache
from app.core.object_storage import ObjectStorageClient
from app.upload.models import ChunkedUploadResponse

logger = logging.getLogger(__name__)

object_storage_client = ObjectStorageClient(
    endpoint_url=(
        str(settings.OBJECT_STORAGE_ENDPOINT_URL) if settings.OBJECT_STORAGE_ENDPOINT_URL else None
    ),
    access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
    secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    bucket_name=settings.OBJECT_STORAGE_BUCKET,
    region=settings.OBJECT_STORAGE_REGION,
    use_path_style=settings.OBJECT_STORAGE_USE_PATH_STYLE,
)

cache = RedisCache(settings.REDIS_URL, settings.REDIS_PASSWORD)


# Chunk keys are etl/uploads/<session>/chunk_NNNN, so the session id must stay one safe path
# segment and the index must fit four digits.
SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{8,64}")
MAX_TOTAL_CHUNKS = 9999
MAX_CHUNK_SIZE = 64 * 1024 * 1024  # 64 MiB
MAX_TOTAL_FILE_SIZE = 20 * 1024**3  # 20 GiB


def validate_upload_parameters(
    *,
    upload_session_id: str,
    chunk_index: int,
    total_chunks: int,
    total_file_size: int,
    chunk_size: int,
) -> None:
    if not SESSION_ID_PATTERN.fullmatch(upload_session_id):
        raise HTTPException(400, "Invalid upload_session_id")
    if not 1 <= total_chunks <= MAX_TOTAL_CHUNKS:
        raise HTTPException(400, f"total_chunks must be between 1 and {MAX_TOTAL_CHUNKS}")
    if not 1 <= chunk_index <= total_chunks:
        raise HTTPException(400, f"Invalid chunk_index: {chunk_index}")
    if not 1 <= chunk_size <= MAX_CHUNK_SIZE:
        raise HTTPException(400, f"chunk_size must be between 1 and {MAX_CHUNK_SIZE}")
    if not 1 <= total_file_size <= MAX_TOTAL_FILE_SIZE:
        raise HTTPException(400, f"total_file_size must be between 1 and {MAX_TOTAL_FILE_SIZE}")
    if total_file_size > chunk_size * total_chunks:
        raise HTTPException(400, "total_file_size does not fit in total_chunks of chunk_size")


def sanitize_filename(filename: str) -> str:
    safe = "".join(c for c in filename if c.isalnum() or c in "._-")
    if not safe or ".." in safe:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return safe


def calculate_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def process_chunked_upload(
    chunk: UploadFile,
    source_url: str,
    upload_session_id: str,
    chunk_index: int,
    total_chunks: int,
    original_filename: str,
    total_file_size: int,
    chunk_size: int,
    expected_hash: str | None = None,
) -> ChunkedUploadResponse:
    """
    Store chunk to object storage. Assembly is handled by the ETL node, not here.

    When all chunks are received, saves metadata.json with upload info
    for the ETL node to use during assembly.
    """
    validate_upload_parameters(
        upload_session_id=upload_session_id,
        chunk_index=chunk_index,
        total_chunks=total_chunks,
        total_file_size=total_file_size,
        chunk_size=chunk_size,
    )
    safe_filename = sanitize_filename(original_filename)

    # Read one byte past the declared size so an oversized chunk is detected without
    # buffering an unbounded body.
    chunk_data = await chunk.read(chunk_size + 1)
    if len(chunk_data) > chunk_size:
        raise HTTPException(413, "Chunk is larger than the declared chunk_size")

    if not cache.redis:
        raise HTTPException(503, "Redis unavailable")

    redis_key = f"upload:{upload_session_id}"
    if await cache.redis.sismember(redis_key, chunk_index):  # type: ignore
        raise HTTPException(409, f"Chunk {chunk_index} was already received")

    # Store chunk in etl/uploads/ path for ETL node to access
    s3_key = f"etl/uploads/{upload_session_id}/chunk_{chunk_index:04d}"
    await object_storage_client.upload(s3_key, chunk_data)

    await cache.redis.sadd(redis_key, chunk_index)  # type: ignore
    await cache.redis.expire(redis_key, 3600)  # type: ignore

    logger.info(
        f"Chunk {chunk_index}/{total_chunks} uploaded to object storage for {safe_filename}"
    )

    received_count = await cache.redis.scard(redis_key)  # type: ignore

    if received_count < total_chunks:
        return ChunkedUploadResponse(
            status="chunk_received",
            chunk_index=chunk_index,
            total_chunks=total_chunks,
        )

    # All chunks received - save metadata for ETL node (no assembly here)
    logger.info(f"All {total_chunks} chunks received for {safe_filename}, saving metadata")

    try:
        import json

        metadata = {
            "session_id": upload_session_id,
            "filename": safe_filename,
            "source_url": source_url,
            "total_chunks": total_chunks,
            "total_size": total_file_size,
            "chunk_size": chunk_size,
            "expected_hash": expected_hash,
            "uploaded_at": datetime.now().isoformat(),
            "status": "pending",
        }

        metadata_key = f"etl/uploads/{upload_session_id}/metadata.json"
        await object_storage_client.upload(metadata_key, json.dumps(metadata).encode())

        await cache.delete(redis_key)

        logger.info(
            f"Metadata saved for {safe_filename} ({total_file_size:,} bytes, {total_chunks} chunks)"
        )

        return ChunkedUploadResponse(
            status="completed",
            filename=safe_filename,
            size=total_file_size,
            hash=expected_hash,
            source_url=source_url,
            uploaded_at=datetime.now().isoformat(),
            session_id=upload_session_id,
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Failed to save metadata for {safe_filename}")
        raise HTTPException(500, "Metadata save failed")
