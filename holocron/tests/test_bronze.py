from collections.abc import Sequence
from typing import Any

from holocron.platform import bronze
from holocron.platform.bronze import replace_keyed_rows


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


def test_replace_keyed_rows_chunks_large_delete_predicates(
    monkeypatch,
) -> None:
    monkeypatch.setattr(bronze, "_MAX_REPLACE_KEYED_DELETE_BYTES", 35)
    clickhouse = FakeClickHouse()

    replace_keyed_rows(
        clickhouse=clickhouse,
        table="example_bronze",
        key_column="property_key",
        key_values=("alpha", "beta", "gamma"),
        rows=(("alpha", 1), ("beta", 2), ("gamma", 3)),
        column_names=("property_key", "value"),
    )

    delete_commands = [command for command in clickhouse.commands if "DELETE FROM" in command]
    assert delete_commands == [
        "DELETE FROM `example_bronze` WHERE `property_key` IN ('alpha', 'beta') "
        "SETTINGS lightweight_deletes_sync = 2",
        "DELETE FROM `example_bronze` WHERE `property_key` IN ('gamma') "
        "SETTINGS lightweight_deletes_sync = 2",
    ]
    assert clickhouse.insert_calls == [
        {
            "table": "example_bronze",
            "rows": (("alpha", 1), ("beta", 2), ("gamma", 3)),
            "column_names": ("property_key", "value"),
        }
    ]


def test_dld_times_are_stored_as_written_in_any_machine_timezone(monkeypatch) -> None:
    # A load run on a machine in London summer time stored 178,502 DLD lease start dates as
    # 23:00 the day before: the client reads a naive datetime in the machine's timezone.
    import time
    from datetime import UTC, datetime

    from holocron.platform.bronze import iso_datetime_or_default, iso_datetime_or_none

    monkeypatch.setenv("TZ", "Europe/London")
    time.tzset()
    try:
        midnight = datetime(2026, 6, 1, tzinfo=UTC).timestamp()
        assert iso_datetime_or_default("2026-06-01T00:00:00").timestamp() == midnight
        assert iso_datetime_or_none("2026-06-01T00:00:00").timestamp() == midnight
        assert iso_datetime_or_default("").timestamp() == 0
    finally:
        monkeypatch.undo()
        time.tzset()
