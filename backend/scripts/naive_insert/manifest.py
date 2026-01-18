"""Manifest management for run-based ETL."""

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime

from .s3_client import S3Client

logger = logging.getLogger(__name__)

MANIFEST_KEY = "etl/manifests/latest.json"


def generate_run_id() -> str:
    """Generate unique run ID: YYYYMMDD_HHMMSS_uuid8"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique = uuid.uuid4().hex[:8]
    return f"{timestamp}_{unique}"


@dataclass
class Manifest:
    """Current manifest state."""

    current_run_id: str
    updated_at: str
    previous_run_id: str | None = None


def load_manifest(s3: S3Client) -> Manifest | None:
    """Load current manifest from S3."""
    try:
        data = json.loads(s3.download_bytes(MANIFEST_KEY).decode("utf-8"))
        return Manifest(
            current_run_id=data["current_run_id"],
            updated_at=data["updated_at"],
            previous_run_id=data.get("previous_run_id"),
        )
    except Exception:
        return None


def save_manifest(s3: S3Client, run_id: str, previous_run_id: str | None) -> None:
    """Update manifest to point to new run."""
    manifest = Manifest(
        current_run_id=run_id,
        updated_at=datetime.now().isoformat(),
        previous_run_id=previous_run_id,
    )
    s3.upload_bytes(MANIFEST_KEY, json.dumps(asdict(manifest)).encode("utf-8"))
    logger.info(f"✓ Manifest updated: {run_id}")


def get_previous_run_id(s3: S3Client) -> str | None:
    """Get the previous run ID from manifest."""
    manifest = load_manifest(s3)
    return manifest.current_run_id if manifest else None
