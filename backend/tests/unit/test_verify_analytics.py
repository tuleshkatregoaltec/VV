"""The Analytics verifier computes its expected values from the raw DXBI listed tables.

Each test encodes a rule the Analytics API documents (and the live API follows), so a verifier
that drifts back to the old ch_transactions layer, or to a market type the API rejects, fails.
"""

from datetime import date, timedelta

import pandas as pd
import pytest

from scripts.clickhouse import verify_analytics as v

TODAY = date(2026, 11, 15)


def sale(**over) -> dict:
    row = {
        "transaction_date": TODAY - timedelta(days=1),
        "property_type": "Apartment",
        "bedrooms": "2 Bed",
        "profile_bedrooms": "",
        "market_status": "Ready",
        "profile_status": "",
        "size_sqft": 1000.0,
        "profile_size": 0.0,
        "sale_amount_aed": 1_500_000,
        "price_per_sqft_aed": 1500.0,
        "master_key": "businessbay",
        "master_name": "Business Bay",
        "area_name": "Business Bay",
    }
    row.update(over)
    return row


def lease(**over) -> dict:
    row = {
        "lease_start": TODAY - timedelta(days=1),
        "property_type": "Apartment",
        "bedrooms": "1 Bed",
        "profile_bedrooms": "",
        "size_sqft": 800.0,
        "profile_size": 0.0,
        "annual_rent_aed": 90_000,
        "master_key": "businessbay",
        "master_name": "Business Bay",
        "area_name": "Business Bay",
    }
    row.update(over)
    return row


def sales_frame(*rows: dict) -> pd.DataFrame:
    return v.derive_sales(pd.DataFrame(list(rows)))


def lease_frame(*rows: dict) -> pd.DataFrame:
    return v.derive_leases(pd.DataFrame(list(rows)))


# -- the API's usage rule: by property type, not by a stored usage column ----------------------
@pytest.mark.parametrize(
    ("kind", "usage"),
    [
        ("Apartment", "Residential"),
        ("Villa", "Residential"),
        ("Townhouse", "Residential"),
        ("Hotel Apartment", "Residential"),
        ("Office", "Commercial"),
        ("Shop", "Commercial"),
        ("Building", "Commercial"),
        ("Commercial", "Commercial"),
        ("Plot", ""),
        ("", ""),
    ],
)
def test_usage_follows_the_property_type_lists(kind, usage):
    assert v.usage_of(pd.Series([kind])).iloc[0] == usage


def test_residential_expectation_counts_villas_and_townhouses():
    """The stale verifier read a usage column that put villas elsewhere (6,197 vs 10,249)."""
    verifier = v.Verifier("http://api", "t", today=TODAY)
    verifier.sales = sales_frame(
        sale(property_type="Apartment"),
        sale(property_type="Villa"),
        sale(property_type="Townhouse"),
        sale(property_type="Office"),
        sale(property_type="Plot"),
    )
    assert len(verifier.expected_sales(30, "Residential")) == 3
    assert len(verifier.expected_sales(30, "Commercial")) == 1


def test_a_plot_is_in_neither_usage_but_is_the_land_market_type():
    verifier = v.Verifier("http://api", "t", today=TODAY)
    verifier.sales = sales_frame(sale(property_type="Plot"), sale(property_type=""))
    assert len(verifier.expected_sales(30, "Residential")) == 0
    assert len(verifier.expected_sales(30, "Commercial")) == 0
    assert len(verifier.expected_sales(30, market_type="land")) == 1


def test_market_types_are_exactly_the_ones_the_api_accepts():
    """The API answers 422 to mortgages and gifts: they are DLD registrations, not DXBI sales."""
    assert set(v.MARKET_TYPES) == {
        "residential_units",
        "villas",
        "commercial_units",
        "bulk_building",
        "land",
    }


def test_market_types_split_the_property_types():
    frame = sales_frame(
        *[
            sale(property_type=kind)
            for kind in (
                "Apartment",
                "Hotel Apartment",
                "Villa",
                "Townhouse",
                "Office",
                "Building",
                "Plot",
            )
        ]
    )
    held = {m: set(frame[v.MARKET_TYPES[m](frame)].property_type) for m in v.MARKET_TYPES}
    assert held["residential_units"] == {"Apartment", "Hotel Apartment"}
    assert held["villas"] == {"Villa", "Townhouse"}
    assert held["commercial_units"] == {"Office"}  # not a villa, plot or whole building
    assert held["bulk_building"] == {"Building"}
    assert held["land"] == {"Plot"}


# -- derived values follow the listed tables' documented rules -----------------------------------
def test_rooms_label_is_the_bedroom_count_for_homes_and_the_type_for_offices():
    frame = sales_frame(
        sale(bedrooms="2 Bed"),
        sale(bedrooms="Studio"),
        sale(bedrooms="", profile_bedrooms="3 Beds"),
        sale(property_type="Office", bedrooms=""),
        sale(property_type="Commercial", bedrooms=""),
    )
    assert list(frame.rooms) == [
        "2 B/R",
        "Studio",
        "3 B/R",
        "Office",
        "Commercial (type not recorded)",
    ]


def test_registration_type_uses_dxbi_status_then_the_profiles():
    frame = sales_frame(
        sale(market_status="Offplan"),
        sale(market_status="Ready"),
        sale(market_status="", profile_status="Off-Plan"),
        sale(market_status="", profile_status="Ready"),
        sale(market_status="", profile_status=""),
    )
    assert list(frame.reg_type) == [
        "Off-Plan Properties",
        "Existing Properties",
        "Off-Plan Properties",
        "Existing Properties",
        "",
    ]


def test_area_falls_back_to_the_profiles_when_dxbi_has_none():
    frame = sales_frame(
        sale(size_sqft=900.0, profile_size=1200.0),
        sale(size_sqft=0.0, profile_size=1200.0),
        sale(size_sqft=0.0, profile_size=0.0),
    )
    assert frame.sqft.iloc[0] == 900.0
    assert frame.sqft.iloc[1] == 1200.0
    assert pd.isna(frame.sqft.iloc[2])


def test_price_per_sqft_is_dxbis_rounded_then_price_over_size():
    frame = sales_frame(
        sale(price_per_sqft_aed=1499.5),
        sale(price_per_sqft_aed=None, sale_amount_aed=1_000_000, size_sqft=800.0),
        sale(price_per_sqft_aed=None, size_sqft=0.0),
    )
    assert frame.ppsf.iloc[0] == 1500.0  # halves round up, as ClickHouse round does
    assert frame.ppsf.iloc[1] == 1250.0
    assert pd.isna(frame.ppsf.iloc[2])


def test_master_key_falls_back_to_the_dxbi_community_when_dld_has_none():
    frame = sales_frame(
        sale(master_key="", master_name="", area_name="Dubai Hills Estate"),
        sale(master_key="", master_name="", area_name="Marina Dubai"),
    )
    assert frame.master_key.iloc[0] == "dubaihillsestate"
    assert frame.master_key.iloc[1] == "marinadubai"


def test_clickhouse_median_is_the_upper_middle_of_an_even_count():
    """medianExact returns the n/2-th sorted value; pandas would average the middle two."""
    assert v.ch_median(pd.Series([1.0, 2.0, 3.0, 4.0])) == 3.0
    assert v.ch_median(pd.Series([5.0, 1.0, 3.0])) == 3.0
    assert v.ch_median(pd.Series([None, 2.0])) == 2.0
    assert v.ch_median(pd.Series([], dtype=float)) is None


# -- windows and buckets -----------------------------------------------------------------------
def test_period_runs_from_today_minus_n_days_to_today_inclusive():
    verifier = v.Verifier("http://api", "t", today=TODAY)
    verifier.sales = sales_frame(
        sale(transaction_date=TODAY - timedelta(days=30)),
        sale(transaction_date=TODAY - timedelta(days=31)),
        sale(transaction_date=TODAY),
        sale(transaction_date=TODAY + timedelta(days=1)),
    )
    assert len(verifier.expected_sales(30, "Residential")) == 2


def test_buckets_are_half_open():
    verifier = v.Verifier("http://api", "t", today=TODAY)
    verifier.sales = sales_frame(
        sale(sale_amount_aed=999_999),
        sale(sale_amount_aed=1_000_000),
        sale(sale_amount_aed=1_999_999),
        sale(sale_amount_aed=2_000_000),
    )
    assert len(verifier.expected_sales(30, "Residential", price_bucket="1M-2M")) == 2


def test_master_project_matches_any_spelling_the_hierarchy_resolves():
    verifier = v.Verifier("http://api", "t", today=TODAY)
    verifier.aliases = {"marinadubai": ["dubaimarina"]}
    verifier.sales = sales_frame(
        sale(master_key="dubaimarina", master_name="Dubai Marina"),
        sale(master_key="marinadubai", master_name="Marina Dubai"),
        sale(master_key="businessbay"),
    )
    assert len(verifier.expected_sales(30, "Residential", master_project="Marina Dubai")) == 2


# -- comparing with the API ------------------------------------------------------------------
class FakeApi:
    """Stands in for the HTTP API: answers from a table of canned bodies."""

    def __init__(self, bodies):
        self.bodies = bodies
        self.calls = []

    def __call__(self, path, **params):
        self.calls.append((path, params))
        body = self.bodies[path]
        if isinstance(body, Exception):
            raise body
        return body(params) if callable(body) else body


def summary(count, volume, avg, mn, mx, sqft):
    return {
        "summary": {
            "transaction_count": count,
            "total_volume": volume,
            "avg_price": avg,
            "min_price": mn,
            "max_price": mx,
            "avg_price_sqft": sqft,
        }
    }


def test_sales_comparison_passes_when_the_api_matches_the_listed_rows():
    verifier = v.Verifier("http://api", "t", today=TODAY)
    verifier.sales = sales_frame(sale(), sale(sale_amount_aed=2_500_000, size_sqft=1250.0))
    verifier.api = FakeApi(
        {"analytics/sales": summary(2, 4_000_000.0, 2_000_000.0, 1_500_000.0, 2_500_000.0, 1_750.0)}
    )
    verifier.compare_sales(30)
    assert verifier.checks == 6
    assert verifier.failures == []


def test_sales_comparison_fails_when_the_api_count_differs():
    verifier = v.Verifier("http://api", "t", today=TODAY)
    verifier.sales = sales_frame(sale(), sale())
    verifier.api = FakeApi({"analytics/sales": summary(1, 1.0, 1.0, 1.0, 1.0, 1.0)})
    verifier.compare_sales(30)
    assert any("count" in failure for failure in verifier.failures)


def test_an_unaccepted_market_type_is_a_pass_when_the_api_rejects_it():
    verifier = v.Verifier("http://api", "t", today=TODAY)
    verifier.api = FakeApi({"analytics/sales": v.Failed("HTTP 422")})
    verifier.check_rejected_market_types()
    assert verifier.failures == []
    assert verifier.checks == 2  # mortgages and gifts


def test_an_unaccepted_market_type_fails_when_the_api_answers_it():
    verifier = v.Verifier("http://api", "t", today=TODAY)
    verifier.api = FakeApi({"analytics/sales": summary(0, 0, 0, 0, 0, 0)})
    verifier.check_rejected_market_types()
    assert len(verifier.failures) == 2


def test_the_parts_of_the_listed_sales_add_up_to_all_of_them():
    """A sale is Residential, Commercial, a Plot (land) or has no type: nothing else is left."""
    verifier = v.Verifier("http://api", "t", today=TODAY)
    verifier.sales = sales_frame(
        sale(),
        sale(property_type="Villa"),
        sale(property_type="Office"),
        sale(property_type="Plot"),
        sale(property_type=""),
    )

    def answer(params):
        counts = {("Residential", None): 2, ("Commercial", None): 1, (None, "land"): 1}
        key = (
            params.get("property_usage") if not params.get("market_type") else None,
            params.get("market_type"),
        )
        return summary(counts.get(key, 0), 1, 1, 1, 1, 1)

    verifier.api = FakeApi({"analytics/sales": answer})
    verifier.reconcile_sales(30)
    assert verifier.failures == []
    assert verifier.notes["sales 30d without a type"] == 1


def test_the_parts_of_the_listed_leases_add_up_to_all_of_them():
    verifier = v.Verifier("http://api", "t", today=TODAY)
    verifier.rents = lease_frame(lease(), lease(property_type="Office"), lease(property_type=""))

    def answer(params):
        return {
            "summary": {"contract_count": 1 if params["property_usage"] == "Residential" else 1}
        }

    verifier.api = FakeApi({"analytics/rentals": answer})
    verifier.reconcile_leases(30)
    assert verifier.failures == []
    assert verifier.notes["leases 30d without a type"] == 1


def test_trend_weeks_start_on_sunday():
    verifier = v.Verifier("http://api", "t", today=TODAY)
    saturday = date(2026, 11, 14)
    sunday = date(2026, 11, 8)
    assert saturday.weekday() == 5
    assert v.period_start(saturday, 90) == sunday
    assert v.period_start(sunday, 90) == sunday
    assert v.period_start(saturday, 30) == saturday
    assert v.period_start(saturday, 365) == date(2026, 11, 1)
    assert verifier.today == TODAY


def test_main_needs_a_token(monkeypatch, capsys):
    monkeypatch.delenv("VERIFY_API_TOKEN", raising=False)
    assert v.main() == 2


def test_expected_values_never_read_the_stale_combined_layer():
    """The API reads dxbi_sales_listed / dxbi_leases_listed since 10-14, not ch_transactions."""
    for sql in (v.SALES_SQL, v.LEASES_SQL, v.DUBAI_SALES_SQL, v.DUBAI_LEASES_SQL):
        assert "ch_transactions" not in sql
        assert "ch_rent_contracts" not in sql
    assert "dxbi_sales_listed" in v.SALES_SQL
    assert "dxbi_leases_listed" in v.LEASES_SQL


# -- price floors, trends, breakdowns and market metrics (2026-11-15) -------------------------
def test_expected_rows_apply_the_api_price_floors():
    """Sales under AED 50,000 and rents under AED 1,000 a year are not Analytics records."""
    assert "sale_amount_aed >= 50000" in v.SALES_SQL
    assert "sale_amount_aed >= 50000" in v.DUBAI_SALES_SQL
    assert "annual_rent_aed >= 1000 AND lease_end > lease_start" in v.LEASES_SQL
    assert "annual_rent_aed >= 1000 AND lease_end > lease_start" in v.DUBAI_LEASES_SQL


def _sales_body(today=TODAY):
    """What the API answers for two sales yesterday (Saturday 14 Nov) and one in the prior 30."""
    return {
        "summary": {"transaction_count": 2, "total_volume": 4_000_000.0,
                    "count_change_pct": 100.0, "volume_change_pct": 166.7},
        "trends": [{"date": "2026-11-14", "count": 2, "total_value": 4_000_000.0,
                    "avg_value": 2_000_000.0, "avg_sqft": 1750.0, "partial": False}],
        "by_property_type": [{"dimension_value": "Apartment", "transaction_count": 2,
                              "total_volume": 4_000_000.0, "avg_price_sqft": 1750.0,
                              "pct_of_total": 100.0}],
        "by_rooms": [{"dimension_value": "2 B/R", "transaction_count": 1, "total_volume": 1.5e6,
                      "avg_price_sqft": 1500.0, "pct_of_total": 50.0},
                     {"dimension_value": "Not recorded", "transaction_count": 1,
                      "total_volume": 2.5e6, "avg_price_sqft": 2000.0, "pct_of_total": 50.0}],
        "by_reg_type": [{"dimension_value": "Existing Properties", "transaction_count": 2,
                         "total_volume": 4e6, "avg_price_sqft": 1750.0, "pct_of_total": 100.0}],
        "by_master_project": [{"dimension_value": "Business Bay", "transaction_count": 2,
                               "total_volume": 4e6, "avg_price_sqft": 1750.0,
                               "pct_of_total": 100.0}],
    }  # fmt: skip


def _breakdown_verifier():
    verifier = v.Verifier("http://api", "t", today=TODAY)
    verifier.sales = sales_frame(
        sale(),
        sale(sale_amount_aed=2_500_000, size_sqft=1250.0, bedrooms=""),
        sale(transaction_date=TODAY - timedelta(days=40), sale_amount_aed=1_500_000),
    )
    return verifier


def test_sales_trend_breakdowns_and_changes_pass_when_the_api_matches():
    verifier = _breakdown_verifier()
    verifier.api = FakeApi({"analytics/sales": _sales_body()})
    verifier.compare_sales_breakdowns(30)
    assert verifier.failures == []
    assert verifier.checks > 20


def test_sales_breakdowns_fail_when_the_api_answers_them_empty():
    """The stub the API used to be: trends and every breakdown [], changes null."""
    verifier = _breakdown_verifier()
    body = _sales_body()
    body.update(trends=[], by_property_type=[], by_rooms=[], by_reg_type=[], by_master_project=[])
    body["summary"].update(count_change_pct=None, volume_change_pct=None)
    verifier.api = FakeApi({"analytics/sales": body})
    verifier.compare_sales_breakdowns(30)
    assert any("trend" in failure for failure in verifier.failures)
    assert any("by_rooms" in failure for failure in verifier.failures)
    assert any("change" in failure for failure in verifier.failures)


def test_market_metrics_must_equal_the_listed_rows_and_the_sales_page():
    verifier = _breakdown_verifier()
    metrics = {
        "total": {"count": 2, "values": {"mean_aed": 2_000_000.0, "total_aed": 4_000_000.0}},
        "coverage": {"data_from": "2014-01-02", "data_to": "2026-11-14"},
        "release_id": "dxbi-20261115040727",
    }
    verifier.api = FakeApi({"analytics/sales": summary(2, 4e6, 2e6, 1.5e6, 2.5e6, 1750.0)})
    verifier.api_post = FakeApi({"analytics/market-metrics": metrics})
    verifier.compare_market_metrics("sales", 30)
    assert verifier.failures == []

    metrics["total"]["count"] = 3  # the combined DLD layer's count
    verifier.compare_market_metrics("sales", 30)
    assert any("market-metrics" in failure and "count" in failure for failure in verifier.failures)
