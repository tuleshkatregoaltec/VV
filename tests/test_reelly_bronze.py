import hashlib
import json
from collections.abc import Sequence
from typing import Any

import pytest

from holocron.sources.reelly_supply.bronze import load_release_to_clickhouse
from tests.fakes import FakeS3


class FakeClickHouse:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.insert_calls: list[dict[str, Any]] = []

    def command(self, sql: str) -> None:
        self.commands.append(sql)

    def insert_rows(
        self,
        *,
        table: str,
        rows: Sequence[tuple[Any, ...]],
        column_names: Sequence[str],
    ) -> None:
        self.insert_calls.append({"table": table, "rows": rows, "column_names": column_names})


def _jsonl_payload(rows: list[dict[str, Any]]) -> bytes:
    return ("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n").encode()


def _file(path: str, key: str, payload: bytes, *, sha256: str | None = None) -> dict:
    return {
        "path": path,
        "s3_key": key,
        "sha256": sha256 or hashlib.sha256(payload).hexdigest(),
        "row_count": len(payload.splitlines()),
    }


def test_reelly_bronze_loads_projects_documents_and_availability() -> None:
    projects = _jsonl_payload(
        [
            {
                "scraped_at": "2026-05-05T00:00:00+00:00",
                "project_id": 123,
                "delta_reason": "new",
                "list_item": {"id": 123},
                "raw": {"id": 123, "name": "Project"},
            }
        ]
    )
    documents = _jsonl_payload(
        [
            {
                "scraped_at": "2026-05-05T00:00:00+00:00",
                "project_id": 123,
                "endpoint": "projects",
                "field_path": "brochure",
                "name": "Brochure",
                "url": "https://api.reelly.io/file.pdf",
                "normalized_url": "https://api.reelly.io/file.pdf",
                "status": "download_skipped",
                "raw": {"url": "https://api.reelly.io/file.pdf"},
            }
        ]
    )
    availability = _jsonl_payload(
        [
            {
                "scraped_at": "2026-05-05T00:00:00+00:00",
                "project_id": 123,
                "endpoint": "evolutions/availability/floors",
                "candidate": 999,
                "status": "success",
                "raw": {"floors": []},
            }
        ]
    )
    clickhouse = FakeClickHouse()

    result = load_release_to_clickhouse(
        raw_manifest={
            "source": "reelly_supply",
            "run_id": "run-1",
            "files": [
                _file("reelly_supply_project_details.jsonl", "raw/projects.jsonl", projects),
                _file("reelly_supply_project_documents.jsonl", "raw/documents.jsonl", documents),
                _file(
                    "reelly_supply_matrix_availability.jsonl",
                    "raw/availability.jsonl",
                    availability,
                ),
            ],
        },
        s3=FakeS3(
            {
                "raw/projects.jsonl": projects,
                "raw/documents.jsonl": documents,
                "raw/availability.jsonl": availability,
            }
        ),
        clickhouse=clickhouse,
    )

    assert result["table_row_counts"] == {
        "reelly_projects_bronze": 1,
        "reelly_documents_bronze": 1,
        "reelly_matrix_availability_bronze": 1,
    }
    assert {call["table"] for call in clickhouse.insert_calls} == {
        "reelly_projects_bronze",
        "reelly_documents_bronze",
        "reelly_matrix_availability_bronze",
    }
    project_call = next(
        call for call in clickhouse.insert_calls if call["table"] == "reelly_projects_bronze"
    )
    assert project_call["rows"][0][1:5] == (
        "run-1",
        "2026-05-05T00:00:00+00:00",
        "123",
        "new",
    )


def test_reelly_bronze_rejects_checksum_before_mutation() -> None:
    projects = _jsonl_payload([{"project_id": 123}])
    clickhouse = FakeClickHouse()

    with pytest.raises(ValueError, match="checksum mismatch"):
        load_release_to_clickhouse(
            raw_manifest={
                "source": "reelly_supply",
                "run_id": "run-1",
                "files": [
                    _file(
                        "reelly_supply_project_details.jsonl",
                        "raw/projects.jsonl",
                        projects,
                        sha256="bad",
                    )
                ],
            },
            s3=FakeS3({"raw/projects.jsonl": projects}),
            clickhouse=clickhouse,
        )

    assert not clickhouse.commands
    assert not clickhouse.insert_calls
