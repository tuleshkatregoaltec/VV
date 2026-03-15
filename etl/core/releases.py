"""Release and manifest models shared across datasets."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from etl.lib.csv_utils import count_csv_rows


class FileArtifact(BaseModel):
    name: str
    s3_key: str
    size_bytes: int
    sha256: str
    row_count: int | None = None
    table_name: str | None = None


class ReleaseManifest(BaseModel):
    dataset: str
    release_id: str
    mode: str
    source: str
    created_at: str
    files: list[FileArtifact]
    schema_version: int = 2
    validation: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "ReleaseManifest":
        return cls.model_validate_json(raw)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_release_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def checksum_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_file_artifact(
    local_path: Path, *, s3_key: str, table_name: str | None = None
) -> FileArtifact:
    row_count = count_csv_rows(local_path) if local_path.suffix.lower() == ".csv" else None
    return FileArtifact(
        name=local_path.name,
        s3_key=s3_key,
        size_bytes=local_path.stat().st_size,
        sha256=checksum_file(local_path),
        row_count=row_count,
        table_name=table_name,
    )
