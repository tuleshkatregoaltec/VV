"""The comparable-sales query must use the same window and outlier bounds valuation relies on."""

from datetime import date

from app.crm import valuation_queries
from app.crm.import_models import CrmPropertyContactClaim


async def test_comparable_stats_sql_uses_window_and_bounds(monkeypatch):
    captured = {}

    async def fake_query(sql, params):
        captured["sql"], captured["params"] = sql, params
        return []

    monkeypatch.setattr(valuation_queries, "query", fake_query)
    await valuation_queries.fetch_comparable_stats(
        ["b1"], ["a1"], date(2025, 11, 5), date(2026, 11, 6)
    )
    sql = captured["sql"]
    for level in ("building_type_beds", "building_type", "area_type_beds", "area_type"):
        assert f"'{level}' AS level" in sql
    assert "BETWEEN 200 AND 12000" in sql
    assert "size_sqft > 0" in sql
    assert captured["params"] == {
        "building_keys": ["b1"],
        "area_keys": ["a1"],
        "since": "2025-11-05",
        "until": "2026-11-06",
    }


def test_claim_model_has_valuation_columns():
    columns = CrmPropertyContactClaim.__table__.c
    for name in ("estimated_value_aed", "estimated_value_low_aed", "estimated_value_high_aed"):
        assert columns[name].nullable
    assert columns["valuation"].nullable is False


async def test_bulk_deal_counts_once(monkeypatch):
    # Units sold together on one day at one price per sqft are one piece of evidence, not many.
    captured = {}

    async def fake_query(sql, params):
        captured["sql"] = sql
        return []

    monkeypatch.setattr(valuation_queries, "query", fake_query)
    await valuation_queries.fetch_comparable_stats(
        ["b"], ["a"], date(2025, 11, 5), date(2026, 11, 6)
    )
    sql = captured["sql"]
    assert sql.count("transaction_date, round(log(price_per_sqft_aed) * 100)") == 4
    assert "count() AS count" in sql and "sum(sales) AS sales" in sql
