import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from holocron.sources.dld.bronze import load_release_to_clickhouse


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
        self.insert_calls: list[dict[str, Any]] = []

    def command(self, sql: str) -> None:
        self.commands.append(sql)

    def insert_rows(
        self, *, table: str, rows: list[tuple], column_names: tuple[str, ...] | list[str]
    ) -> None:
        self.insert_calls.append(
            {
                "table": table,
                "rows": rows,
                "column_names": tuple(column_names),
            }
        )


def _jsonl_payload(rows: list[dict[str, Any]]) -> bytes:
    return ("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n").encode("utf-8")


def test_load_release_to_clickhouse_loads_transaction_detail_rows() -> None:
    raw_rows = [
        {
            "endpoint": "communitywise_transaction_details",
            "transaction_kind": "sales",
            "transaction_date": "2026-04-30",
            "data_mode": "Flat",
            "property_type": {
                "id": 3,
                "name": {"englishName": "Unit", "arabicName": "وحدة"},
            },
            "raw": {
                "community": {"id": "A-266", "name": {"englishName": "Al Satwa"}},
                "projects": [
                    {
                        "project": {"id": 649994953, "name": {"englishName": "ENSO JADE"}},
                    }
                ],
                "building": {"id": 650424593, "name": {"englishName": "ENSO JADE"}},
                "usage": {"id": 1, "name": {"englishName": "Residential"}},
                "propertyStatus": {"id": 0, "name": {"englishName": "Off-Plan"}},
                "propertySubType": {"id": 60, "name": {"englishName": "Flat"}},
                "saleType": {"id": 1, "name": {"englishName": "First"}},
                "value": 1623250.0,
                "size": 70.15,
                "per_Sqm": 23139.7,
                "totalTrx": 1,
            },
        }
    ]
    payload = _jsonl_payload(raw_rows)
    s3 = _FakeS3({"raw/details.jsonl": payload})
    clickhouse = _FakeClickHouse()

    result = load_release_to_clickhouse(
        raw_release={
            "source": "dld_transactions",
            "run_id": "release-run-1",
            "files": [
                {
                    "path": "dld_transactions_sales_2026-04-30.jsonl",
                    "s3_key": "raw/details.jsonl",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "row_count": 1,
                },
                {
                    "path": "dld_transaction_daily_totals_2026-04-30.jsonl",
                    "s3_key": "raw/totals.jsonl",
                    "row_count": 1,
                },
            ],
        },
        s3=s3,  # type: ignore[arg-type]
        clickhouse=clickhouse,  # type: ignore[arg-type]
    )

    assert result["table_row_counts"] == {"dld_transactions_bronze": 1}
    assert result["total_rows"] == 1
    assert result["reconciliation"] == {
        "manifest_detail_rows": 1,
        "downloaded_detail_rows": 1,
    }
    assert any(
        "CREATE TABLE IF NOT EXISTS dld_transactions_bronze" in sql for sql in clickhouse.commands
    )
    assert any(
        "ALTER TABLE dld_transactions_bronze DELETE WHERE" in sql
        and "transaction_kind = 'sales'" in sql
        and "toDate('2026-04-30')" in sql
        for sql in clickhouse.commands
    )
    assert len(clickhouse.insert_calls) == 1
    insert_call = clickhouse.insert_calls[0]
    assert insert_call["table"] == "dld_transactions_bronze"
    assert len(insert_call["rows"]) == 1
    assert insert_call["rows"][0][1:4] == ("sales", date(2026, 4, 30), "Flat")


def test_load_release_to_clickhouse_rejects_checksum_mismatch() -> None:
    payload = _jsonl_payload([])

    with pytest.raises(ValueError, match="checksum mismatch"):
        load_release_to_clickhouse(
            raw_release={
                "source": "dld_transactions",
                "run_id": "release-run-1",
                "files": [
                    {
                        "path": "dld_transactions_sales_2026-04-30.jsonl",
                        "s3_key": "raw/details.jsonl",
                        "sha256": "bad",
                        "row_count": 0,
                    }
                ],
            },
            s3=_FakeS3({"raw/details.jsonl": payload}),  # type: ignore[arg-type]
            clickhouse=_FakeClickHouse(),  # type: ignore[arg-type]
        )


def test_load_release_to_clickhouse_rejects_non_dld_release() -> None:
    with pytest.raises(ValueError, match="Expected raw_release.source=dld_transactions"):
        load_release_to_clickhouse(
            raw_release={"source": "other_source", "run_id": "run-1", "files": []},
            s3=_FakeS3({}),  # type: ignore[arg-type]
            clickhouse=_FakeClickHouse(),  # type: ignore[arg-type]
        )
