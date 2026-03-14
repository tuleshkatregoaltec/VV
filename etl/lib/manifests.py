"""Manifest creation and serialisation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class FileEntry:
    name: str
    s3_key: str
    size_bytes: int
    sha256: str
    row_count: Optional[int] = None


@dataclass
class Manifest:
    dataset: str
    run_id: str
    source: str
    created_at: str
    files: list[FileEntry]
    schema_version: int = 1
    validation: Optional[dict] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "Manifest":
        data = {**data, "files": [FileEntry(**f) for f in data["files"]]}
        return cls(**data)

    @classmethod
    def from_json(cls, raw: str) -> "Manifest":
        return cls.from_dict(json.loads(raw))


def checksum_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_file_entry(local_path: Path, s3_key: str) -> FileEntry:
    return FileEntry(
        name=local_path.name,
        s3_key=s3_key,
        size_bytes=local_path.stat().st_size,
        sha256=checksum_file(local_path),
    )


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
