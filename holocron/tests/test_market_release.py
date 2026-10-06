"""The canonical market layer validates a staged release before it replaces the served one."""

from __future__ import annotations

import os
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from holocron.market import release
from holocron.market.checks import MarketCheck


def test_render_retargets_whole_table_names_only() -> None:
    names = {"market_sale_events": "market_sale_events__staging_x"}
    assert (
        release.render("FROM `market_sale_events` JOIN market_sale_events_old", names)
        == "FROM `market_sale_events__staging_x` JOIN market_sale_events_old"
    )


class _Recorder:
    """Answers every check with one value and records the statements sent."""

    def __init__(self, check_value: float, live_served: int = 10, staged_served: int = 10):
        self.check_value = check_value
        self.live_served = live_served
        self.staged_served = staged_served
        self.commands: list[str] = []
        self.queries: list[str] = []

    def command(self, sql: str) -> None:
        self.commands.append(sql)

    def query(self, sql: str) -> Any:
        self.queries.append(sql)
        if "WHERE is_served = 1" in sql:
            value = self.staged_served if "__staging_" in sql else self.live_served
        elif "GROUP BY match_status" in sql:
            return SimpleNamespace(result_rows=[("dld_only", self.live_served)])
        else:
            value = self.check_value
        return SimpleNamespace(result_rows=[(value,)])


_CHECK = MarketCheck(
    name="served_unique",
    asset="t",
    description="",
    sql="SELECT count() - uniqExact(id) FROM t WHERE is_served = 0",
    op="==",
    threshold=0,
)


def _publish(client: _Recorder) -> dict:
    return release.publish_validated(
        clickhouse=cast(Any, client),
        builds={"t": ("INSERT INTO `t` SELECT 1",)},
        served_table="t",
        checks=(_CHECK,),
    )


def test_failing_blocking_check_never_reaches_the_served_table() -> None:
    client = _Recorder(check_value=3)
    with pytest.raises(release.MarketReleaseRejected, match="served_unique=3"):
        _publish(client)
    assert not any("EXCHANGE" in sql for sql in client.commands)
    # The check ran against staging, not against what the backend serves.
    assert any("__staging_" in sql and "uniqExact" in sql for sql in client.queries)
    assert client.commands[-1].startswith("DROP TABLE IF EXISTS `t__staging_")


def test_partial_release_below_the_served_row_floor_is_rejected() -> None:
    client = _Recorder(check_value=0, live_served=1000, staged_served=500)
    with pytest.raises(release.MarketReleaseRejected, match="served_rows=500"):
        _publish(client)
    assert not any("EXCHANGE" in sql for sql in client.commands)


def test_valid_release_is_exchanged_after_validation_and_previous_is_kept() -> None:
    client = _Recorder(check_value=0)
    result = _publish(client)
    exchange = next(i for i, sql in enumerate(client.commands) if "EXCHANGE" in sql)
    assert client.commands[exchange - 1].startswith("OPTIMIZE TABLE")
    assert client.commands[exchange + 2] == (
        f"RENAME TABLE `t__staging_{result['release_id']}` TO `t__previous`"
    )


def test_unmeasurable_ratio_does_not_block_dld_only_release() -> None:
    # No DXBI rows: ratio checks divide 0 by 0. That cannot invalidate DLD data.
    client = _Recorder(check_value=float("nan"))
    _publish(client)
    assert any("EXCHANGE" in sql for sql in client.commands)


# --- real ClickHouse -----------------------------------------------------------------------

_LIVE = os.environ.get("HOLOCRON_CLICKHOUSE_INTEGRATION") == "1"


@pytest.fixture
def warehouse():
    import clickhouse_connect

    from holocron.platform.clickhouse import ClickHouseClient

    host = os.environ.get("CLICKHOUSE_HOST", "localhost")
    port = int(os.environ.get("CLICKHOUSE_PORT", "8123"))
    user = os.environ.get("CLICKHOUSE_USER", "default")
    password = os.environ.get("CLICKHOUSE_PASSWORD", "")
    if host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("ClickHouse integration requires a local service")
    database = "holocron_release_test_" + uuid4().hex
    admin = clickhouse_connect.get_client(host=host, port=port, username=user, password=password)
    admin.command(f"CREATE DATABASE {database}")
    settings = SimpleNamespace(
        clickhouse_host=host,
        clickhouse_port=port,
        clickhouse_user=user,
        clickhouse_password=password,
        clickhouse_database=database,
        clickhouse_secure=False,
    )
    try:
        yield ClickHouseClient(cast(Any, settings))
    finally:
        admin.command(f"DROP DATABASE {database} SYNC")


def _dld_sales(client, rows: list[tuple[str, str, int]]) -> None:
    client.insert_rows(
        table="dld_od_transactions_bronze",
        column_names=[
            "row_key", "run_id", "transaction_number", "instance_date", "group_en",
            "trans_value", "procedure_area", "area_en", "is_offplan_en", "source_system",
        ],
        rows=[
            (f"r-{number}", "run", number, datetime(2026, 9, 10), group, price, 80.0, "Marsa Dubai",
             "Ready", "dld_open_data")
            for number, group, price in rows
        ],
    )  # fmt: skip


def _served(client) -> int:
    return int(
        client.query("SELECT count() FROM market_sale_events WHERE is_served = 1").result_rows[0][0]
    )


@pytest.mark.skipif(not _LIVE, reason="set HOLOCRON_CLICKHOUSE_INTEGRATION=1 with local ClickHouse")
def test_invalid_or_partial_staged_release_keeps_last_good_release(warehouse) -> None:
    from holocron.platform.clickhouse_schema import ensure_schema

    ensure_schema(clickhouse=warehouse)
    good = [(f"T{i}", "Sales", 1_000_000 + i) for i in range(100)]
    _dld_sales(warehouse, good)
    first = release.materialize_market_sale_events(clickhouse=warehouse)
    assert _served(warehouse) == 100 and first["served_rows"] == 100

    # Partial upstream: half the DLD bronze disappears. The release is refused.
    warehouse.command("TRUNCATE TABLE dld_od_transactions_bronze")
    _dld_sales(warehouse, good[:50])
    with pytest.raises(release.MarketReleaseRejected, match="served_rows=50"):
        release.materialize_market_sale_events(clickhouse=warehouse)
    assert _served(warehouse) == 100

    # Invalid vocabulary in an otherwise complete input is refused too.
    _dld_sales(warehouse, good[50:] + [("T999", "Unknown group", 5)])
    with pytest.raises(release.MarketReleaseRejected, match="sale_label_vocabulary=1"):
        release.materialize_market_sale_events(clickhouse=warehouse)
    assert _served(warehouse) == 100

    # Valid new data publishes; the replaced release is retained once; no staging is left.
    warehouse.command(
        "ALTER TABLE dld_od_transactions_bronze DELETE WHERE transaction_number = 'T999' SETTINGS mutations_sync = 1"
    )
    _dld_sales(warehouse, [("T100", "Sales", 2_000_000)])
    release.materialize_market_sale_events(clickhouse=warehouse)
    assert _served(warehouse) == 101
    tables = {
        row[0]
        for row in warehouse.query(
            "SELECT name FROM system.tables WHERE database = currentDatabase()"
        ).result_rows
    }
    assert {"market_sale_events__previous", "market_sale_matches__previous"} <= tables
    assert not any("__staging_" in name for name in tables)
    previous = warehouse.query(
        "SELECT count() FROM market_sale_events__previous WHERE is_served = 1"
    ).result_rows[0][0]
    assert previous == 100


@pytest.mark.skipif(not _LIVE, reason="set HOLOCRON_CLICKHOUSE_INTEGRATION=1 with local ClickHouse")
def test_corrections_duplicates_and_cut_over_are_served_once(warehouse) -> None:
    from holocron.platform.clickhouse_schema import ensure_schema

    ensure_schema(clickhouse=warehouse)
    columns = [
        "row_key", "run_id", "scraped_at", "transaction_number", "instance_date", "group_en",
        "trans_value", "procedure_area", "area_en", "is_offplan_en", "source_system",
    ]  # fmt: skip
    rows = [
        # T1 corrected by a later open-data extract: only the later price is served.
        ("t1-v1", "r1", "2026-09-10T00:00:00", "T1", datetime(2026, 9, 2), "Sales", 1_000_000),
        ("t1-v2", "r2", "2026-09-12T00:00:00", "T1", datetime(2026, 9, 2), "Sales", 1_100_000),
        # T2 delivered twice in one run: served once.
        ("t2-a", "r2", "2026-09-12T00:00:00", "T2", datetime(2026, 9, 3), "Sales", 2_000_000),
        ("t2-b", "r2", "2026-09-12T00:00:00", "T2", datetime(2026, 9, 3), "Sales", 2_000_000),
    ]
    warehouse.insert_rows(
        table="dld_od_transactions_bronze",
        column_names=columns,
        rows=[(*row, 80.0, "Marsa Dubai", "Ready", "dld_open_data") for row in rows],
    )
    # Pulse history: kept before the open-data start (2026-09-02), dropped from it on.
    warehouse.insert_rows(
        table="dld_od_transactions_bronze",
        column_names=columns,
        rows=[
            (
                "p-old",
                "pulse",
                "2026-05-16T00:00:00",
                "P1",
                datetime(2026, 8, 30),
                "Sales",
                900_000,
                80.0,
                "Marsa Dubai",
                "Ready",
                "dubai_pulse",
            ),
            (
                "p-overlap",
                "pulse",
                "2026-05-16T00:00:00",
                "P2",
                datetime(2026, 9, 2),
                "Sales",
                1_000_000,
                80.0,
                "Marsa Dubai",
                "Ready",
                "dubai_pulse",
            ),
        ],  # fmt: skip
    )
    release.materialize_market_sale_events(clickhouse=warehouse)
    served = warehouse.query(
        "SELECT transaction_id, actual_worth FROM market_sale_events WHERE is_served = 1 "
        "ORDER BY transaction_id"
    ).result_rows
    assert served == [("P1", 900_000), ("T1", 1_100_000), ("T2", 2_000_000)]
