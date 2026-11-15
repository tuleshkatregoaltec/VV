"""The Transactions pages read page tables built once per DXBI load, not the live source.

Every cold page load used to de-duplicate and place all 1M DXBI sales three times (count, page,
filter options): about 1.1 + 1.7 + 1.3 GiB of ClickHouse memory and 8-12 s (2026-11-15 audit).
dxbi_sales_page / dxbi_leases_page hold the same rows, built by build_page_tables after each
release; the pages filter them.
"""

from datetime import date

import pytest
from clickhouse_connect.driver.exceptions import DatabaseError

from app.transaction import page_tables, queries
from app.transaction.models import RentalFilters, SalesFilters

DUBAI_TODAY = date(2026, 11, 16)


@pytest.fixture(autouse=True)
def dubai_today(monkeypatch):
    monkeypatch.setattr("app.transaction.queries.business_today", lambda: DUBAI_TODAY)


def _recording(monkeypatch, results):
    calls = []

    async def fake_query(sql, params):
        calls.append((sql, dict(params)))
        result = results[len(calls) - 1] if len(calls) <= len(results) else []
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(queries, "query", fake_query)
    return calls


async def test_sales_page_and_total_read_the_page_table(monkeypatch):
    calls = _recording(monkeypatch, [[{"total": 3}], [{"transaction_id": "T-1"}]])

    rows, total = await queries.fetch_sales_rows(
        SalesFilters(property_usage="Residential", timeframe_days=30), 30, 60
    )

    assert (rows, total) == ([{"transaction_id": "T-1"}], 3)
    for sql, params in calls:
        assert "FROM dxbi_sales_page" in sql
        assert "dxbi_sales_unit_events" not in sql
        assert "transaction_date > {today:Date} - {timeframe_days:Int32}" in sql
        assert params["today"] == DUBAI_TODAY
    # Both keys descending: the page table's own order read backwards, so ClickHouse reads only
    # the newest granules instead of every row on or before the page (2026-11-16: 24k vs 967k).
    assert "ORDER BY transaction_date DESC, transaction_id DESC" in calls[1][0]
    assert calls[1][1]["offset"] == 60


async def test_rental_page_and_total_read_the_page_table(monkeypatch):
    calls = _recording(monkeypatch, [[{"total": 1}], [{"contract_id": "R-1"}]])

    rows, total = await queries.fetch_rental_rows(RentalFilters(timeframe_days=7), 10, 0)

    assert total == 1
    assert all("FROM dxbi_leases_page" in sql for sql, _ in calls)
    assert all("dxbi_rental_events" not in sql for sql, _ in calls)


async def test_without_a_page_table_the_pages_read_the_live_source(monkeypatch):
    # Before the first build after a deploy the table does not exist yet: slower, never broken.
    missing = DatabaseError(
        "Code: 60. DB::Exception: Table vitevue.dxbi_sales_page does not exist. (UNKNOWN_TABLE)"
    )
    calls = _recording(monkeypatch, [missing, [{"total": 2}], [{"transaction_id": "T-1"}]])

    rows, total = await queries.fetch_sales_rows(SalesFilters(timeframe_days=30), 30, 0)

    assert total == 2
    assert "FROM dxbi_sales_page" in calls[0][0]
    assert "dxbi_sales_unit_events FINAL" in calls[1][0]
    # The live source is de-duplicated over all dates, as the page table is, then windowed.
    assert "transaction_date > {today:Date} - {timeframe_days:Int32}" in calls[1][0]


async def test_other_warehouse_errors_are_not_hidden_by_the_fallback(monkeypatch):
    _recording(monkeypatch, [DatabaseError("Code: 241. MEMORY_LIMIT_EXCEEDED")])

    with pytest.raises(DatabaseError):
        await queries.fetch_sales_rows(SalesFilters(), 30, 0)


def test_the_date_window_ends_today_in_dubai(monkeypatch):
    # 22:30 UTC on 15 November is 02:30 on 16 November in Dubai.
    from datetime import UTC, datetime

    from app.market import periods

    assert periods.business_today(datetime(2026, 11, 15, 22, 30, tzinfo=UTC)) == DUBAI_TODAY
    params: dict = {}
    clause = queries._date_window("transaction_date", 1, params)
    assert (
        clause == "transaction_date > {today:Date} - {timeframe_days:Int32} "
        "AND transaction_date <= {today:Date}"
    )
    assert params == {"today": DUBAI_TODAY, "timeframe_days": 1}


class FakeWarehouse:
    def __init__(self, *, rows: int, existing: bool = True):
        self.commands: list[str] = []
        self.rows = rows
        self.existing = existing

    async def command(self, sql, *args, **kwargs):
        self.commands.append(" ".join(sql.split()))
        return self.existing if sql.startswith("EXISTS") else None

    async def query(self, sql, *args, **kwargs):
        class Result:
            result_rows = [[self.rows]]

        return Result()


async def test_a_build_fills_a_staging_copy_then_swaps_it_in():
    warehouse = FakeWarehouse(rows=1_006_773)

    rows = await page_tables.build_page_tables(warehouse)

    assert rows == {"dxbi_sales_page": 1_006_773, "dxbi_leases_page": 1_006_773}
    sales = [c for c in warehouse.commands if "dxbi_sales_page" in c]
    assert sales[0] == "DROP TABLE IF EXISTS dxbi_sales_page__staging"
    assert sales[1].startswith(
        "CREATE TABLE dxbi_sales_page__staging ENGINE = MergeTree "
        "ORDER BY (transaction_date, transaction_id) AS SELECT"
    )
    assert "dxbi_sales_unit_events FINAL" in sales[1]
    assert "EXCHANGE TABLES dxbi_sales_page__staging AND dxbi_sales_page" in sales
    assert sales[-1] == "DROP TABLE IF EXISTS dxbi_sales_page__staging"


async def test_the_first_build_renames_the_staging_copy_into_place():
    warehouse = FakeWarehouse(rows=5, existing=False)

    await page_tables.build_page_tables(warehouse)

    assert "RENAME TABLE dxbi_leases_page__staging TO dxbi_leases_page" in warehouse.commands


async def test_an_empty_build_leaves_the_served_table_unchanged():
    warehouse = FakeWarehouse(rows=0)

    with pytest.raises(RuntimeError, match="no rows"):
        await page_tables.build_page_tables(warehouse)

    assert not any(c.startswith(("EXCHANGE", "RENAME")) for c in warehouse.commands)
