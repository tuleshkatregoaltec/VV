"""Chunk assembly and hash verification."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .s3_client import S3Client
from .utils import compute_file_hash

logger = logging.getLogger(__name__)


@dataclass
class AssemblyResult:
    """Result of chunk assembly."""
    local_path: Path
    filename: str
    computed_hash: str
    expected_hash: str | None
    verified: bool


def assemble_chunks(
    s3: S3Client,
    session_id: str,
    output_dir: Path,
    expected_hash: str | None = None,
) -> AssemblyResult:
    """Download chunks from S3 and assemble into a single file.

    Args:
        s3: S3 client instance
        session_id: Upload session ID
        output_dir: Local directory for assembled file
        expected_hash: Optional expected SHA256 hash for verification

    Returns:
        AssemblyResult with local path, computed hash, and verification status
    """
    # Load metadata
    metadata_key = f"etl/uploads/{session_id}/metadata.json"
    metadata = json.loads(s3.download_bytes(metadata_key).decode("utf-8"))

    filename = metadata["filename"]
    total_chunks = metadata["total_chunks"]
    expected = expected_hash or metadata.get("expected_hash")

    output_path = output_dir / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Assembling {filename} from {total_chunks} chunks...")

    # Download and assemble chunks (1-indexed to match upload service)
    with open(output_path, "wb") as f:
        for i in range(1, total_chunks + 1):
            chunk_key = f"etl/uploads/{session_id}/chunk_{i:04d}"
            chunk_data = s3.download_bytes(chunk_key)
            f.write(chunk_data)
            if i % 10 == 0:
                logger.debug(f"  Downloaded chunk {i}/{total_chunks}")

    # Compute and verify hash
    computed = compute_file_hash(output_path)
    verified = computed == expected if expected else True

    if expected and not verified:
        logger.error(f"Hash mismatch! Expected: {expected}, Got: {computed}")
    else:
        logger.info(f"✓ Assembled {filename} ({output_path.stat().st_size:,} bytes)")

    return AssemblyResult(
        local_path=output_path,
        filename=filename,
        computed_hash=computed,
        expected_hash=expected,
        verified=verified,
    )


def cleanup_session(s3: S3Client, session_id: str) -> None:
    """Delete all objects for an upload session."""
    prefix = f"etl/uploads/{session_id}/"
    keys = s3.list_objects(prefix)
    for key in keys:
        s3.delete_object(key)
    logger.info(f"Cleaned up {len(keys)} objects from session {session_id}")
