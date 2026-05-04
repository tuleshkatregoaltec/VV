from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def manifest_files_by_name(raw_release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files = raw_release.get("files")
    if not isinstance(files, list):
        raise ValueError("raw_release.files must be a list")
    mapped: dict[str, dict[str, Any]] = {}
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("raw_release.files must only contain objects")
        path_value = string_value(item.get("path"))
        if not path_value:
            raise ValueError("raw_release file is missing path")
        mapped[Path(path_value).name] = item
    return mapped


def require_manifest_file(
    files_by_name: dict[str, dict[str, Any]], file_name: str
) -> dict[str, Any]:
    file_entry = files_by_name.get(file_name)
    if file_entry is None:
        raise KeyError(f"raw_release is missing expected file: {file_name}")
    return file_entry


def download_manifest_file(
    *,
    file_name: str,
    file_entry: dict[str, Any],
    s3: Any,
    scratch_path: Path,
    source_label: str,
) -> Path:
    s3_key = string_value(file_entry.get("s3_key"))
    if not s3_key:
        raise ValueError(f"raw_release entry for {file_name} is missing s3_key")
    local_path = scratch_path / file_name
    s3.download_file(key=s3_key, path=local_path)
    validate_file_sha256(path=local_path, file_entry=file_entry, source_label=source_label)
    return local_path


def validate_file_sha256(
    *,
    path: Path,
    file_entry: dict[str, Any],
    source_label: str,
) -> None:
    expected_sha = string_value(file_entry.get("sha256"))
    if not expected_sha:
        return
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError(f"{source_label} raw file checksum mismatch: {path.name}")


def read_jsonl_manifest_rows(
    *,
    path: Path,
    file_entry: dict[str, Any],
    source_label: str,
) -> list[dict[str, Any]]:
    rows = read_jsonl_rows(path=path, source_label=source_label)
    validate_manifest_row_count(
        file_name=path.name,
        file_entry=file_entry,
        actual_row_count=len(rows),
        source_label=source_label,
    )
    return rows


def read_jsonl_rows(*, path: Path, source_label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError(f"{source_label} raw row must be an object in {path.name}")
        rows.append(payload)
    return rows


def read_csv_manifest_rows(
    *,
    path: Path,
    file_entry: dict[str, Any],
    source_label: str,
) -> list[dict[str, str]]:
    _allow_large_csv_fields()
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    validate_manifest_row_count(
        file_name=path.name,
        file_entry=file_entry,
        actual_row_count=len(rows),
        source_label=source_label,
    )
    return rows


def count_csv_rows(path: Path) -> int:
    _allow_large_csv_fields()
    with path.open(encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _allow_large_csv_fields() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def validate_manifest_row_count(
    *,
    file_name: str,
    file_entry: dict[str, Any],
    actual_row_count: int,
    source_label: str,
) -> None:
    expected = file_entry.get("row_count")
    if expected is None:
        return
    expected_count = int(expected)
    if expected_count != actual_row_count:
        raise ValueError(
            f"{source_label} raw file row_count mismatch for {file_name}: "
            f"manifest={expected_count} actual={actual_row_count}"
        )
