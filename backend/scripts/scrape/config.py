"""Configuration and metadata management for file downloader."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class FileMetadata:
    """Metadata for a downloaded file."""

    source_url: str
    filename: str
    download_url: str
    downloaded_at: str
    file_hash: str
    file_size: int


def calculate_file_hash(filepath: Path) -> str:
    """Calculate SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def load_metadata(metadata_file: Path) -> dict[str, FileMetadata]:
    """Load metadata from JSON file."""
    if not metadata_file.exists():
        return {}

    try:
        with open(metadata_file, "r") as f:
            data = json.load(f)
        return {url: FileMetadata(**meta) for url, meta in data.items()}
    except Exception:
        return {}


def save_metadata(metadata_file: Path, metadata: dict[str, FileMetadata]):
    """Save metadata to JSON file."""
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    with open(metadata_file, "w") as f:
        json.dump({url: asdict(meta) for url, meta in metadata.items()}, f, indent=2)


def get_data_paths(base_dir: Path | None = None) -> tuple[Path, Path]:
    """Get current and previous data directory paths.

    Default: backend/scripts/scrape -> project_root/data
    """
    if base_dir is None:
        # From backend/scripts/scrape -> go up 3 levels to project root
        script_dir = Path(__file__).parent
        project_root = script_dir.parent.parent.parent
        base_dir = project_root / "data"

    return base_dir / "current", base_dir / "previous"


def get_sources_file() -> Path:
    """Get default sources.txt path (same directory as this module)."""
    return Path(__file__).parent / "sources.txt"
