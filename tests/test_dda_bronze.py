import hashlib
from pathlib import Path
from typing import Any

import pytest

from holocron.sources.dda.bronze import _TABLE_SPECS, load_release_to_clickhouse


class _FakeS3:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self._objects = objects

    def download_file(self, *, key: str, path: str | Path) -> None:
        payload = self._objects[key]
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)


class _FakeClickHouse:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.replace_calls: list[dict[str, Any]] = []

    def command(self, sql: str) -> None:
        self.commands.append(sql)

    def replace_table_rows(
        self,
        *,
        table: str,
        rows: list[tuple],
        column_names: tuple[str, ...] | list[str],
        staging_suffix: str,
    ) -> int:
        self.replace_calls.append(
            {
                "table": table,
                "rows": rows,
                "column_names": tuple(column_names),
                "staging_suffix": staging_suffix,
            }
        )
        return len(rows)


def _csv_payload(columns: tuple[str, ...]) -> bytes:
    return (",".join(columns) + "\n").encode("utf-8")


def _valid_empty_release() -> tuple[dict[str, Any], dict[str, bytes]]:
    objects: dict[str, bytes] = {}
    files: list[dict[str, Any]] = []
    for spec in _TABLE_SPECS:
        payload = _csv_payload(spec.column_names)
        key = f"raw/{spec.csv_name}"
        objects[key] = payload
        files.append(
            {
                "path": spec.csv_name,
                "s3_key": key,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "row_count": 0,
            }
        )
    return {"source": "dda_planning_layers", "run_id": "release-run-1", "files": files}, objects


def test_load_release_to_clickhouse_rejects_checksum_mismatch_before_mutation() -> None:
    raw_release, objects = _valid_empty_release()
    raw_release["files"][0]["sha256"] = "bad"
    clickhouse = _FakeClickHouse()

    with pytest.raises(ValueError, match="checksum mismatch"):
        load_release_to_clickhouse(
            raw_release=raw_release,
            s3=_FakeS3(objects),  # type: ignore[arg-type]
            clickhouse=clickhouse,  # type: ignore[arg-type]
        )

    assert not clickhouse.commands
    assert not clickhouse.replace_calls


def test_load_release_to_clickhouse_rejects_row_count_mismatch_before_mutation() -> None:
    raw_release, objects = _valid_empty_release()
    raw_release["files"][0]["row_count"] = 1
    clickhouse = _FakeClickHouse()

    with pytest.raises(ValueError, match="row_count mismatch"):
        load_release_to_clickhouse(
            raw_release=raw_release,
            s3=_FakeS3(objects),  # type: ignore[arg-type]
            clickhouse=clickhouse,  # type: ignore[arg-type]
        )

    assert not clickhouse.commands
    assert not clickhouse.replace_calls
