import hashlib
import importlib
import json
from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest

from tests.fakes import FakeS3

_CATEGORIES = (
    "transactions rents projects valuations lands buildings units brokers developers".split()
)
SOURCE_MODULES = tuple(
    (f"dld_od_{c}", f"dld_od_{c}_rows.jsonl", f"dld_od_{c}_bronze") for c in _CATEGORIES
)


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


def _release(source: str, row_file: str, payload: bytes, *, sha256: str | None = None) -> dict:
    return {
        "source": source,
        "run_id": "run-1",
        "files": [
            {
                "path": row_file,
                "s3_key": f"raw/{source}/{row_file}",
                "sha256": sha256 or hashlib.sha256(payload).hexdigest(),
                "row_count": 1,
            }
        ],
    }


@pytest.mark.parametrize(("source", "row_file", "table"), SOURCE_MODULES)
def test_dld_open_data_bronze_loaders_map_rows(source: str, row_file: str, table: str) -> None:
    payload = _jsonl_payload(
        [
            {
                "endpoint": source.removeprefix("dld_od_"),
                "category": source.removeprefix("dld_od_"),
                "scraped_at": "2026-05-06T12:00:00+00:00",
                "mode": "incremental",
                "date_window": {"start_date": "2026-05-05", "end_date": "2026-05-06"},
                "page_index": 1,
                "row_index": 3,
                "raw": {"TOTAL": 1, "ID": "row-1"},
            }
        ]
    )
    clickhouse = FakeClickHouse()
    module = importlib.import_module(f"holocron.sources.{source}.bronze")
    result = module.load_release_to_clickhouse(
        raw_manifest=_release(source, row_file, payload),
        s3=FakeS3({f"raw/{source}/{row_file}": payload}),
        clickhouse=clickhouse,
    )

    assert result["table_row_counts"] == {table: 1}
    assert any(f"CREATE TABLE IF NOT EXISTS {table}" in sql for sql in clickhouse.commands)
    assert any(
        f"ALTER TABLE `{table}` DELETE WHERE run_id = 'run-1'" in sql for sql in clickhouse.commands
    )
    assert clickhouse.insert_calls[0]["table"] == table
    # All sources share the same envelope layout at positions 1–7.
    row = clickhouse.insert_calls[0]["rows"][0]
    assert row[1:8] == (
        "run-1",
        "2026-05-06T12:00:00+00:00",
        "incremental",
        date(2026, 5, 5),
        date(2026, 5, 6),
        1,
        3,
    )


@pytest.mark.parametrize(("source", "row_file", "_table"), SOURCE_MODULES)
def test_dld_open_data_bronze_rejects_checksum_before_mutation(
    source: str,
    row_file: str,
    _table: str,
) -> None:
    payload = _jsonl_payload([{"raw": {"ID": "row-1"}}])
    clickhouse = FakeClickHouse()
    module = importlib.import_module(f"holocron.sources.{source}.bronze")

    with pytest.raises(ValueError, match="checksum mismatch"):
        module.load_release_to_clickhouse(
            raw_manifest=_release(source, row_file, payload, sha256="bad"),
            s3=FakeS3({f"raw/{source}/{row_file}": payload}),
            clickhouse=clickhouse,
        )

    assert not clickhouse.commands
    assert not clickhouse.insert_calls
