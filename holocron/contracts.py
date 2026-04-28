from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


Extractor = Callable[..., Any]
Check = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class RawFile:
    path: str
    sha256: str
    size_bytes: int
    row_count: int | None = None
    content_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawRelease:
    source: str
    run_id: str
    extract_date: str
    created_at: str
    files: tuple[RawFile, ...]
    manifest_version: int = 1
    schema_version: int = 1
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BronzeTable:
    name: str
    source_key: str | None = None


@dataclass(frozen=True, slots=True)
class SilverTable:
    name: str


@dataclass(frozen=True, slots=True)
class SourceSpec:
    name: str
    provider: str
    extractor: Extractor
    bronze_tables: Sequence[BronzeTable] = ()
    silver_tables: Sequence[SilverTable] = ()
    checks: Sequence[Check] = ()
    checkpoint_strategy: str = "full_refresh"
    cadence: str | None = None
    description: str | None = None

