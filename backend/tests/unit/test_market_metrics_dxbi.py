"""POST /analytics/market-metrics reads the records the rest of Analytics reads.

It read the combined DXBI + DLD market layer (ch_transactions / ch_rent_contracts) while
/analytics/sales read DXBI's listed sales: for Residential over 365 days one answered 157,385
sales averaging AED 2,658,390 and the other 155,568 averaging AED 2,504,507. Its coverage came
from DLD load windows that stopped on 2026-10-13, so every DXBI day loaded since was
"unverified", and its first record date was a 1975 DLD registration.
"""

from datetime import date

from app.analytics import dxbi, market_metric_queries, market_metrics, queries
from app.analytics.models import MarketMetricsRequest


def test_metrics_read_the_analytics_sources():
    assert market_metric_queries.SALES.table is dxbi.SALES_SOURCE
    assert market_metric_queries.RENTALS.table is dxbi.RENTALS_SOURCE


def _capture(monkeypatch):
    statements: list[tuple[str, dict]] = []

    async def fake_query(sql, params):
        statements.append((sql, params))
        return [{"count": 0.0}]

    monkeypatch.setattr(market_metric_queries, "query", fake_query)
    return statements


async def test_residential_metrics_select_the_sales_summary_rows(monkeypatch):
    """The same period and usage select the same rows as /analytics/sales: its WHERE, here."""
    statements = _capture(monkeypatch)
    filters = market_metric_queries.MetricFilters(
        start=date(2025, 11, 15), end=date(2026, 11, 15), usage="residential"
    )

    await market_metric_queries.fetch_metric_rows("sales", filters, ("mean_aed",))

    ((sql, params),) = statements
    assert f"FROM {dxbi.SALES_SOURCE}" in sql
    assert "property_usage_en = {usage:String}" in sql
    assert params["usage"] == "Residential"
    assert "toDate(instance_date) BETWEEN {start:Date} AND {end:Date}" in sql
    summary = queries.sales_summary("Residential", "2025-11-15", "2026-11-15")
    assert "trans_group_en = 'Sales'" in summary and "trans_group_en = 'Sales'" in sql


async def test_coverage_comes_from_the_dxbi_load_windows(monkeypatch):
    statements = _capture(monkeypatch)

    async def fake_query(sql, params):
        statements.append((sql, params))
        if "source_load_windows" in sql:
            return [
                {"window_start": date(2026, 11, 8), "window_end": date(2026, 11, 14),
                 "status": "complete", "first_row": 0, "loaded_at": "2026-11-15 04:02:00"},
            ]  # fmt: skip
        return [{"release_id": "dxbi-20261115040727", "eligible_count": 10,
                 "data_from": date(2014, 1, 2), "data_to": date(2026, 11, 14),
                 "built_at": "2026-11-15 04:07:27"}]  # fmt: skip

    monkeypatch.setattr(market_metric_queries, "query", fake_query)

    release = await market_metric_queries.fetch_release("sales")

    window_sql, window_params = next(s for s in statements if "source_load_windows" in s[0])
    assert window_params == {"bronze_table": "dxbi_sales_unit_events",
                             "date_field": "transaction_date"}  # fmt: skip
    assert release["coverage"]["ranges"] == [
        {"from": "2026-11-08", "to": "2026-11-14", "status": "verified"}
    ]
    assert release["coverage"]["last_loaded_at"] == "2026-11-15 04:02:00"
    request = MarketMetricsRequest(
        dataset="sales", period={"type": "range", "start": "2026-11-08", "end": "2026-11-14"}
    )
    coverage = market_metrics._coverage(market_metrics._resolve(request), release)
    assert (coverage.status, coverage.verified_days) == ("complete", 7)


def test_a_load_that_stopped_inside_its_window_is_partial_evidence():
    ranges = market_metric_queries.coverage_ranges(
        [
            {"window_start": date(2026, 11, 1), "window_end": date(2026, 11, 7),
             "status": "complete", "first_row": 0},
            {"window_start": date(2026, 11, 5), "window_end": date(2026, 11, 9),
             "status": "incomplete", "first_row": 0},
        ]
    )  # fmt: skip

    assert ranges == [
        {"from": "2026-11-01", "to": "2026-11-04", "status": "verified"},
        {"from": "2026-11-05", "to": "2026-11-09", "status": "partial"},
    ]
