"""Feasibility prices studies from DXBI's listed records, as Analytics does.

The DLD register behind ch_transactions / ch_rent_contracts stops being current (procedure,
plot and coverage rows end at 2026-10-13/14; ~300 sales a day after against ~1,000 in DXBI), so
study pricing read from it was about a month stale. Market pricing, areas, rental bands and the
chat tools read the floored DXBI sources. What DXBI cannot give (a project's handover date, the
project register, plot land area) stays on DLD and the study says as of when it is.
"""

from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.analytics.dxbi import RENTALS_SOURCE, SALES_SOURCE
from app.feasibility import generation, queries, research
from app.feasibility.models import PlotResearch


@pytest.fixture
def sql(monkeypatch):
    """Every statement a query function sends, with its parameters."""
    sent = []

    async def fake(statement, parameters=None):
        sent.append((statement, parameters))
        return []

    monkeypatch.setattr(queries, "query", fake)
    return sent


@pytest.mark.parametrize("usage", ["residential", "commercial", "mixed_use", "unknown"])
@pytest.mark.parametrize("stage", ["existing", "off_plan", "any"])
async def test_market_pricing_reads_the_dxbi_sales_source(sql, usage, stage):
    await queries.fetch_market_pricing("Marsa Dubai", 365, stage, usage)
    statement = sql[0][0]
    assert SALES_SOURCE in statement
    assert "ch_transactions" not in statement
    assert "FROM ch_" not in statement


async def test_market_pricing_asks_for_the_latest_trade_per_unit_type(sql):
    await queries.fetch_market_pricing("Marsa Dubai", 365, "existing", "residential")
    assert "max(instance_date)" in sql[0][0]


async def test_dxbi_usage_has_no_mixed_use_so_mixed_use_prices_residential_and_commercial():
    clause = queries.transaction_usage_clause("mixed_use")
    assert clause == "(property_usage_en IN ('Residential', 'Commercial'))"
    assert queries.transaction_usage_clause("residential") == "(property_usage_en = 'Residential')"
    assert queries.transaction_usage_clause("commercial") == "(property_usage_en = 'Commercial')"


@pytest.mark.parametrize(
    ("function", "arguments"),
    [
        (queries.fetch_areas, ({},)),
        (queries.fetch_market_area, ({"name": "x", "pattern": "%x%"},)),
        (queries.fetch_chat_area, ({"area": "x", "pattern": "%x%"},)),
        (queries.fetch_tool_market_area, ({"area": "x", "pattern": "%x%"},)),
        (queries.fetch_chat_transactions, ("x", 365, 10, "existing", "", "residential")),
        (queries.fetch_chat_analytics, ("x", 365, "", "existing", "residential")),
    ],
)
async def test_sales_lookups_and_chat_tools_read_the_dxbi_sales_source(sql, function, arguments):
    await function(*arguments)
    assert sql
    for statement, _ in sql:
        assert SALES_SOURCE in statement
        assert "ch_transactions" not in statement


async def test_rental_size_bands_read_the_dxbi_lease_source(sql):
    await queries.fetch_rental_size_band(
        {"area_name": "Marsa Dubai", "lo": 0.0, "hi": 55.0, "days": 365}
    )
    statement = sql[0][0]
    assert RENTALS_SOURCE in statement
    assert "ch_rent_contracts" not in statement


async def test_off_plan_curve_stays_on_dld_because_dxbi_has_no_handover_date(sql):
    """DXBI names an off-plan sale but not when the project completes; only 5% of its off-plan
    sales match a DLD project by name. The curve keeps DLD and the study says as of when."""
    await queries.fetch_off_plan_pricing_curve("Marsa Dubai", 1095, 24, "residential")
    statement = sql[0][0]
    assert "ch_projects" in statement and "completion_date" in statement
    assert "ch_transactions" in statement


async def test_off_plan_curve_filters_dld_by_the_dld_usage_names(sql):
    await queries.fetch_off_plan_pricing_curve("Marsa Dubai", 1095, 24, "residential")
    assert "'Hospitality'" in sql[0][0]  # DLD's property_usage_en spelling, not DXBI's


async def test_data_as_of_asks_each_source_for_its_own_latest_date(sql):
    await queries.fetch_data_as_of({"area_name": "Marsa Dubai"})
    statement, parameters = sql[0]
    assert parameters == {"area_name": "Marsa Dubai"}
    assert SALES_SOURCE in statement and RENTALS_SOURCE in statement
    assert "ch_transactions" in statement


async def test_data_as_of_labels_dxbi_and_dld_sources(monkeypatch):
    monkeypatch.setattr(
        queries,
        "fetch_data_as_of",
        AsyncMock(
            return_value=[
                {
                    "sales_as_of": date(2026, 11, 14),
                    "rentals_as_of": date(2026, 11, 15),
                    "off_plan_curve_as_of": date(2026, 10, 14),
                    "comparables_as_of": date(2026, 10, 13),
                }
            ]
        ),
    )
    rows = await research.get_data_as_of("Marsa Dubai")
    by_key = {row.key: row for row in rows}
    assert by_key["market_pricing"].source == "dxbi"
    assert by_key["market_pricing"].as_of == "2026-11-14"
    assert by_key["rental_rates"].source == "dxbi"
    assert by_key["rental_rates"].as_of == "2026-11-15"
    assert by_key["off_plan_pricing"].source == "dld"
    assert by_key["off_plan_pricing"].as_of == "2026-10-14"
    assert "handover" in by_key["off_plan_pricing"].note
    assert by_key["comparable_projects"].source == "dld"
    assert by_key["comparable_projects"].as_of == "2026-10-13"


async def test_data_as_of_says_so_when_a_source_has_no_rows(monkeypatch):
    monkeypatch.setattr(
        queries,
        "fetch_data_as_of",
        AsyncMock(
            return_value=[
                {
                    "sales_as_of": None,
                    "rentals_as_of": None,
                    "off_plan_curve_as_of": None,
                    "comparables_as_of": None,
                }
            ]
        ),
    )
    rows = await research.get_data_as_of("Nowhere")
    assert {row.as_of for row in rows} == {None}


def test_the_hbu_cache_does_not_serve_studies_priced_from_dld():
    assert generation.HBU_CACHE_PREFIX == "feasibility:hbu:v2"


def test_a_study_stored_before_data_as_of_existed_still_loads():
    field = PlotResearch.model_fields["data_as_of"]
    assert field.default_factory() == []


@pytest.mark.parametrize(
    ("function", "arguments"),
    [
        (queries.fetch_market_pricing, ("Jumeirah Village Circle", 365, "existing", "residential")),
        (
            queries.fetch_rental_size_band,
            ({"area_name": "Jumeirah Village Circle", "lo": 0.0, "hi": 55.0, "days": 365},),
        ),
        (queries.fetch_data_as_of, ({"area_name": "Jumeirah Village Circle"},)),
    ],
)
async def test_an_area_is_matched_by_its_dld_area_or_its_dxbi_community(sql, function, arguments):
    """DXBI prints JVC's DLD area as 'Al Barsha South Fourth' on a quarter of its sales and on
    nearly every lease (32,524 leases in a year, none under 'Jumeirah Village Circle'), so a
    study for JVC found no rents. The Plots evidence already matches either."""
    await function(*arguments)
    statement = sql[0][0]
    assert "lower(location_name) = lower(" in statement


async def test_chat_tools_match_an_area_by_dld_area_or_dxbi_community(sql):
    await queries.fetch_chat_transactions("x", 365, 10, "existing", "", "residential")
    await queries.fetch_chat_analytics("x", 365, "", "existing", "residential")
    assert all("lower(location_name) = lower(" in statement for statement, _ in sql)


async def test_comparable_projects_match_the_area_case_insensitively(sql):
    """DXBI spells a DLD area 'BUSINESS BAY' as often as 'Business Bay'; the project register
    spells it one way."""
    await queries.fetch_comparable_projects({"market_area": "BUSINESS BAY"})
    assert "lower(p.area_name_en) = lower({market_area:String})" in sql[0][0]


async def test_the_area_list_names_each_area_once_whatever_its_spelling(sql):
    await queries.fetch_areas({})
    assert "GROUP BY lower(spelling)" in sql[0][0]


@pytest.mark.parametrize(
    ("function", "arguments"),
    [
        (queries.fetch_comparable_prices, ({"market_area": "Marsa Dubai"}, "residential")),
        (queries.fetch_comparable_unit_prices, ({"project_names": ["Marina Gate"]},)),
    ],
)
async def test_comparable_prices_stay_on_the_dld_register_the_projects_come_from(
    sql, function, arguments
):
    """Comparables are the project register's projects (DLD names). DXBI names a building its
    own way: of Marsa Dubai's 5 register projects with a DLD price, DXBI priced 2. The study
    says as of when those prices are."""
    await function(*arguments)
    statement = sql[0][0]
    assert "FROM ch_transactions" in statement
    assert SALES_SOURCE not in statement
