"""Coverage is evidence of complete loads per day, not the span between first and last record."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta

import pytest

from holocron.platform.load_windows import coverage, record_load_windows, window_evidence
from tests.test_market_release import database, warehouse  # noqa: F401 (fixtures)


def _page(start: str, end: str, *, skip: int, take: int, received: int, total: int | None):
    return {
        "date_window": {"start_date": start, "end_date": end},
        "skip": skip,
        "take": take,
        "api_row_count": received,
        "total": total,
    }


def test_window_evidence_reads_pagination_to_tell_complete_from_partial() -> None:
    pages = [
        # Two full pages then a short one: the end of the result set was reached.
        _page("2026-06-01", "2026-06-07", skip=0, take=2, received=2, total=5),
        _page("2026-06-01", "2026-06-07", skip=2, take=2, received=2, total=5),
        _page("2026-06-01", "2026-06-07", skip=4, take=2, received=1, total=5),
        # Capped after one full page of a larger window: stored rows are a subset.
        _page("2026-06-08", "2026-06-14", skip=0, take=2, received=2, total=9),
        # An empty window: complete, and its days are verified zeros.
        _page("2026-06-15", "2026-06-15", skip=0, take=2, received=0, total=None),
        # A resumed chunk that finishes a window an earlier chunk started.
        _page("2026-06-16", "2026-06-20", skip=4, take=2, received=1, total=5),
    ]
    rows = [{"date_window": {"start_date": "2026-06-01", "end_date": "2026-06-07"}}] * 5
    evidence = {
        (w["window_start"], w["status"], w["rows"], w["evidence"])
        for w in window_evidence(pages, rows)
    }
    assert evidence == {
        (date(2026, 6, 1), "complete", 5, ""),
        (date(2026, 6, 8), "partial", 0, ""),
        (date(2026, 6, 15), "complete", 0, ""),
        (date(2026, 6, 16), "complete", 0, "continued from skip=4"),
    }


@pytest.mark.skipif(
    os.environ.get("HOLOCRON_CLICKHOUSE_INTEGRATION") != "1",
    reason="set HOLOCRON_CLICKHOUSE_INTEGRATION=1 with local ClickHouse",
)
def test_latest_window_decides_each_day_and_releases_record_their_coverage(warehouse) -> None:  # noqa: F811
    from holocron.market import release

    def record(start: date, end: date, status: str) -> None:
        record_load_windows(
            warehouse,
            bronze_table="dld_od_transactions_bronze",
            date_field="instance_date",
            windows=[{"window_start": start, "window_end": end, "status": status, "rows": 1,
                      "evidence": ""}],
            run_id="run",
            manifest_key="",
        )  # fmt: skip

    record(date(2026, 6, 1), date(2026, 6, 14), "complete")
    # A later capped reload of 10-12 June replaced complete data with a subset: partial now.
    record(date(2026, 6, 10), date(2026, 6, 12), "partial")
    record(date(2000, 1, 1), date(2025, 12, 31), "attested")
    result = coverage(
        warehouse,
        bronze_table="dld_od_transactions_bronze",
        date_field="instance_date",
        loaded_before=datetime.now(UTC) + timedelta(minutes=1),
    )
    assert result["ranges"] == [
        {"from": "2000-01-01", "to": "2025-12-31", "status": "verified"},
        {"from": "2026-06-01", "to": "2026-06-09", "status": "verified"},
        {"from": "2026-06-10", "to": "2026-06-12", "status": "partial"},
        {"from": "2026-06-13", "to": "2026-06-14", "status": "verified"},
    ]

    # A release records what it can vouch for when it starts building; later loads do not
    # change the coverage of an already-built release.
    warehouse.insert_rows(
        table="dld_od_transactions_bronze",
        column_names=["row_key", "run_id", "transaction_number", "instance_date", "group_en",
                      "trans_value", "procedure_area", "area_en", "is_offplan_en", "source_system"],
        rows=[("r1", "run", "T1", datetime(2026, 6, 5), "Sales", 1_000_000, 80.0, "Marsa Dubai",
               "Ready", "dld_open_data")],
    )  # fmt: skip
    published = release.materialize_market_sale_events(clickhouse=warehouse)
    record(date(2026, 6, 15), date(2026, 6, 20), "complete")
    entry = release._ledger(warehouse, "market_sale_events")[str(published["release_id"])]
    assert json.loads(entry["coverage_json"])["ranges"] == result["ranges"]
