"""Core models for Holocron release pipelines."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Literal

from dagster import Field, Noneable
from pydantic import BaseModel, Field as PydanticField

from holocron.framework.csv_utils import count_csv_rows

FULL_SNAPSHOT = "full_snapshot"
REFERENCE_REPLACE = "reference_replace"

FULL_SWAP = "full_swap"
APPEND = "append"

GROUPED = "grouped"
PER_TABLE = "per_table"

PublishMode = Literal["grouped", "per_table"]


@dataclass(frozen=True)
class TableSpec:
    csv_name: str
    table_name: str
    load_strategy: str = FULL_SWAP
    min_rows: int = 1
    unique_key: tuple[str, ...] = ()
    non_empty_columns: tuple[str, ...] = ()
    nonzero_columns: tuple[str, ...] = ()
    file_format: str = "CSVWithNames"


@dataclass(frozen=True)
class CheckOutcome:
    name: str
    passed: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)
    description: str | None = None


@dataclass(frozen=True)
class DownloadResult:
    canonical_name: str
    local_path: Path


class FileArtifact(BaseModel):
    name: str
    s3_key: str
    size_bytes: int
    sha256: str
    row_count: int | None = None
    table_name: str | None = None


class LocalFileArtifact(BaseModel):
    name: str
    local_path: str
    size_bytes: int
    sha256: str
    row_count: int | None = None
    table_name: str | None = None


class LocalReleaseManifest(BaseModel):
    dataset: str
    release_id: str
    mode: str
    source: str
    created_at: str
    root_path: str
    files: list[LocalFileArtifact]
    schema_version: int = 1
    metadata: dict[str, Any] = PydanticField(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)


class ReleaseManifest(BaseModel):
    dataset: str
    release_id: str
    mode: str
    source: str
    created_at: str
    files: list[FileArtifact]
    schema_version: int = 1
    metadata: dict[str, Any] = PydanticField(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)


ExtraChecksFn = Callable[[Any, Any, ReleaseManifest, TableSpec], Sequence[CheckOutcome]]
ExtractFn = Callable[[Path], Sequence[Path]]


@dataclass(frozen=True)
class SourceSpec:
    name: str
    source: str
    mode: str
    tables: tuple[TableSpec, ...]
    extract_fn: Callable[..., Sequence[Path]]
    provider: str | None = None
    publish_mode: PublishMode = PER_TABLE
    schedule: str | None = None
    description: str = ""
    config_schema: Mapping[str, Any] = field(default_factory=dict)
    default_config: Mapping[str, Any] = field(default_factory=dict)
    extra_check_names: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    extra_checks_fn: ExtraChecksFn | None = None

    @property
    def local_release_asset_name(self) -> str:
        return f"{self.name}_local_release"

    @property
    def raw_release_asset_name(self) -> str:
        return f"{self.name}_raw_release"

    @property
    def ingest_job_name(self) -> str:
        return f"{self.name}_ingest"

    @property
    def cleanup_job_name(self) -> str:
        return f"{self.name}_cleanup"

    @property
    def schedule_name(self) -> str | None:
        return f"{self.name}_schedule" if self.schedule else None

    @property
    def provider_name(self) -> str:
        return self.provider or self.name

    @property
    def asset_group_name(self) -> str:
        return self.provider_name


def optional_str(default: str = "", description: str = "") -> Field:
    return Field(str, default_value=default, is_required=False, description=description)


def optional_int(default: int | None = None, description: str = "") -> Field:
    return Field(Noneable(int), default_value=default, is_required=False, description=description)


def optional_bool(default: bool = False, description: str = "") -> Field:
    return Field(bool, default_value=default, is_required=False, description=description)


def release_id_field(default: str = "") -> Field:
    return optional_str(
        default,
        description=(
            "Optional stable release identifier. Reuse this to rerun later stages against the "
            "same staged release."
        ),
    )


def batch_id_field(default: str = "") -> Field:
    return optional_str(
        default,
        description=(
            "Optional batch or release identifier. If provided, this is used as the stable "
            "release id for staging, upload, publish, and cleanup."
        ),
    )


def worker_count_field(default: int, description: str) -> Field:
    return optional_int(default, description=description)


def testing_limit_field(description: str) -> Field:
    return optional_int(
        None,
        description=description,
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_now_sql() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def new_release_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def checksum_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_for_table(manifest: ReleaseManifest, table_spec: TableSpec) -> FileArtifact:
    for artifact in manifest.files:
        if artifact.name == table_spec.csv_name:
            return artifact
    raise KeyError(
        f"Manifest for {manifest.dataset} release {manifest.release_id} "
        f"is missing {table_spec.csv_name}"
    )


def build_local_file_artifact(
    local_path: Path, *, table_name: str | None = None
) -> LocalFileArtifact:
    row_count = count_csv_rows(local_path) if local_path.suffix.lower() == ".csv" else None
    return LocalFileArtifact(
        name=local_path.name,
        local_path=str(local_path),
        size_bytes=local_path.stat().st_size,
        sha256=checksum_file(local_path),
        row_count=row_count,
        table_name=table_name,
    )
