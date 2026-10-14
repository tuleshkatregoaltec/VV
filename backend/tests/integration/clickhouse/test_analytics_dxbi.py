"""Analytics must not fall back to DLD prices, labels, stock or search entries."""

import json

import pytest
from test_transactions import (  # noqa: F401
    LOADED,
    dxbi,
    lease,
    sale,
)

from app.analytics import queries, service
from app.clickhouse.client import query


async def test_summary_search_and_charts_are_dxbi_only(dxbi, warehouse):  # noqa: F811
    await dxbi(
        sales=[
            sale("a", project_name="DXBI Tower", dld_transaction_number="verified-id"),
            sale("b", project_name="DXBI Tower", unit_number="102", sale_amount_aed=2400000),
            sale("c", project_name="DXBI Tower", unit_number="103", market_status="Offplan"),
            sale("office", project_name="DXBI Tower", property_type="Office"),
        ],
        leases=[
            lease(
                "rent",
                location_name="DXBI Tower, Downtown Dubai",
                building_name="DXBI Tower",
                area_name="Downtown Dubai",
                bedrooms="1 Bed",
                annual_rent_aed=120000,
            )
        ],
    )
    await warehouse.command("""CREATE TABLE IF NOT EXISTS market_dxbi_sale_enrichment (
        sale_key String, dxbi_loaded_at DateTime64(3, 'UTC'),
        requested_transaction_number String, match_status String,
        dld_transaction_number String, dld_line_id String, project_name String
    ) ENGINE=Memory""")
    # A fully eligible enrichment patch must still not affect Analytics.
    await warehouse.insert(
        "market_dxbi_sale_enrichment",
        [["a", LOADED, "verified-id", "matched", "verified-id", "dld-line", "DLD Label"]],
        column_names=[
            "sale_key",
            "dxbi_loaded_at",
            "requested_transaction_number",
            "match_status",
            "dld_transaction_number",
            "dld_line_id",
            "project_name",
        ],
    )
    for table in ("ch_transactions", "ch_rent_contracts", "ch_projects", "ch_units"):
        await warehouse.command(f"CREATE TABLE {table} (project_name_en String) ENGINE=Memory")
        await warehouse.insert(table, [["DLD Only"]])
    summary = await service.get_project_summary("DXBI Tower", "project")
    assert summary.sales.transaction_count == 3
    assert summary.sales.total_volume == 5600000
    assert summary.sales.avg_price_sqft == pytest.approx(2333.33)
    assert summary.rentals.contract_count == 1
    assert summary.rentals.median_annual_rent == 120000
    assert summary.unit_composition == []
    assert summary.project.no_of_units is None
    assert summary.project.developer_name is None
    assert {row.rooms for row in summary.by_rooms} == {"1 B/R"}
    assert summary.configuration_analysis[0].avg_unit_size_sqft == pytest.approx(800)
    json.dumps(summary.model_dump(mode="json"), allow_nan=False)
    search = await service.get_project_search("")
    assert {p.name for p in search.projects} == {"DXBI Tower", "Downtown Dubai"}
    trends = await service.get_project_trends("DXBI Tower", 365)
    assert sum(p.transaction_count for p in trends.data) == 3
    distro = await service.get_project_price_distribution("DXBI Tower")
    assert distro.all.sale_count == 3
    assert distro.all.mean_price == pytest.approx(summary.sales.avg_price)
    forecast = await service.get_project_forecast("DXBI Tower", 365)
    assert forecast.data == [] and forecast.delivery_date is None
    rows = await query(queries.project_sales_summary("project"), {"project_name": "DLD Label"})
    assert rows[0]["transaction_count"] == 0


async def test_rental_only_scope_is_searchable_and_empty_sales_are_json_safe(dxbi):  # noqa: F811
    await dxbi(leases=[lease("rental-only")])
    search = await service.get_project_search("Iris")
    assert [(p.name, p.filter_type) for p in search.projects] == [("Iris Blue", "project")]
    children = await service.get_sub_project_list("Dubai Marina")
    assert [(p.name, p.transaction_count) for p in children.sub_projects] == [("Iris Blue", 0)]
    summary = await service.get_project_summary("Iris Blue")
    assert summary.sales.transaction_count == 0
    assert summary.rentals.contract_count == 1
    assert summary.overall_gross_yield_pct is None
    json.dumps(summary.model_dump(mode="json"), allow_nan=False)


async def test_configuration_periods_share_today_and_keep_old_sparse_bedrooms(dxbi):  # noqa: F811
    """An old off-plan launch is not current activity; sparse homes must not disappear."""
    from datetime import date, timedelta

    await dxbi(
        sales=[
            sale(
                "ready",
                project_name="Mixed Tower",
                transaction_date=date.today() - timedelta(days=10),
            ),
            sale(
                "old-offplan",
                project_name="Mixed Tower",
                bedrooms="4 Beds",
                transaction_date=date.today() - timedelta(days=800),
                market_status="Offplan",
            ),
            sale(
                "future",
                project_name="Mixed Tower",
                bedrooms="5 Beds",
                transaction_date=date.today() + timedelta(days=30),
                market_status="Offplan",
            ),
        ]
    )
    summary = await service.get_project_summary("Mixed Tower")
    rows = {(row.market_segment, row.rooms): row for row in summary.configuration_analysis}
    assert rows["all", "1 B/R"].sales_last_12m == 1
    for segment in ("all", "off_plan"):
        assert rows[segment, "4 B/R"].sale_count == 1
        assert rows[segment, "4 B/R"].sales_last_12m == 0
        assert rows[segment, "5 B/R"].sales_last_12m == 0
        assert rows[segment, "4 B/R"].price_change_yoy_pct is None
        assert rows[segment, "4 B/R"].sales_momentum_pct is None
    narrow = await queries.fetch_project_configuration_sales(
        {"project_name": "Mixed Tower", "reg_type_en": "Off-Plan Properties"},
        "project",
        "Off-Plan Properties",
    )
    assert all(row["sales_last_12m"] == 0 for row in narrow)


async def test_search_labels_building_fallback_and_preserves_numbered_scopes(dxbi):  # noqa: F811
    await dxbi(
        sales=[
            sale(
                "scope08",
                building_name="08 Life Residences",
                building_key="08life",
                project_name="",
                area_name="Warsan Fourth",
            ),
            sale(
                "scope09",
                building_name="09 Life Residences",
                building_key="09life",
                project_name="",
                area_name="Wadi Al Safa 5",
            ),
        ]
    )
    result = await service.get_project_search("08 LIFE warsan")
    assert [(r.name, r.scope_kind) for r in result.projects] == [("08 Life Residences", "Building")]


async def test_scopes_group_by_the_profiles_dld_master_and_project(dxbi):  # noqa: F811
    """DXBI prints a community ('Dubai Marina'); its profile names DLD's master and project.
    A DXBI 'building' that is a place's name is no project; an unprofiled sale keeps DXBI's."""
    await dxbi(
        sales=[
            sale("paired", building_name="Marina Gate 1", area_name="Dubai Marina"),
            sale("villa", building_name="Mirdif", area_name="Mirdif", unit_number="7"),
            sale("new", building_name="Brand New Tower", project_name="New Launch"),
        ],
        sale_profiles=[
            {
                "sale_key": "paired",
                "master_project": "DUBAI MARINA",
                "area_name": "MARSA DUBAI",
                "project_name": "MARINA GATE",
                "project_source": "dld_pair",
            },
            {
                "sale_key": "villa",
                "master_project": "",
                "area_name": "MIRDIF",
                "project_name": "Mirdif",
                "project_source": "place_name",
            },
        ],  # fmt: skip
    )
    project = await service.get_project_summary("MARINA GATE", "project")
    assert project.sales.transaction_count == 1
    master = await service.get_project_summary("DUBAI MARINA", "master")
    assert master.sales.transaction_count == 1
    # The place-name villa counts under its area's community, never as a project.
    assert (await service.get_project_summary("Mirdif", "project")).sales.transaction_count == 0
    assert (await service.get_project_summary("Mirdif", "master")).sales.transaction_count == 1
    # Loaded since the last profile build: DXBI's own project until the next build.
    assert (await service.get_project_summary("New Launch", "project")).sales.transaction_count == 1


async def test_search_keeps_buildings_beside_many_project_names(dxbi):  # noqa: F811
    await dxbi(
        sales=[
            *(
                sale(f"p{i}", project_name=f"Lake Project {i:02}", building_name="")
                for i in range(60)
            ),
            *(
                sale(
                    f"b{i}",
                    building_name="Lake Shore Tower",
                    project_name="JLT Cluster X",
                    unit_number=f"20{i}",
                )
                for i in range(3)
            ),
            # One record is no evidence of a building's project (a stray pairing).
            sale("stray", building_name="Lakeside Stray", project_name="Other Project"),
        ]
    )
    found = (await service.get_project_search("lake", limit=50)).projects
    assert len(found) == 50
    # The building keeps its place and opens its project.
    assert [(p.name, p.building) for p in found if p.building] == [
        ("JLT Cluster X", "Lake Shore Tower")
    ]
    # An empty search lists scopes only.
    assert not any(p.building for p in (await service.get_project_search("")).projects)


async def test_a_project_header_names_its_sources(dxbi, warehouse):  # noqa: F811
    """DXBI transactions hold no developer, handover or unit count: DXBInteract's building list
    does. Its project card repeats the totals of the building cards it lists."""
    await dxbi(
        sales=[sale("s", building_name="Lakeshore Tower 1", project_name="Lake Shore Tower")]
    )

    def card(location_id, name, units, kind="B", kids=()):
        building = {
            "location": name, "project": "Lake Shore Tower", "area_name": "Al Thanyah Fifth",
            "dev": "Al Bodor", "completion_date": "2012-01-21T20:00:00Z",
            "completion_percent": 100, "unit_count": units, "display_as": kind,
            "building_csv": list(kids),
        }  # fmt: skip
        return [location_id, 200, json.dumps({"Building": building})]

    await warehouse.insert(
        "dxbi_heatmap_buildings_bronze",
        [card("1", "Lake Shore Tower", 477, "P", kids=[2]), card("2", "Lakeshore Tower 1", 477)],
        column_names=["location_id", "status", "payload_json"],
    )
    meta = (await service.get_project_summary("Lake Shore Tower", "project")).project
    assert (meta.developer_name, str(meta.completion_date), meta.no_of_units) == (
        "Al Bodor",
        "2012-01-21",
        477,
    )
    assert meta.no_of_buildings == 1
    assert set(meta.field_sources) >= {"developer_name", "completion_date", "no_of_units"}
    assert set(meta.field_sources.values()) == {"dxbi_buildings"}


async def test_an_abbreviation_finds_the_master_it_stands_for(dxbi):  # noqa: F811
    """DXBI and DLD write "Jumeirah Village Circle"; people type "JVC"."""
    await dxbi(
        sales=[sale("jvc", building_name="Bloom Towers", area_name="Jumeirah Village Circle")],
        sale_profiles=[
            {
                "sale_key": "jvc",
                "master_project": "Jumeirah Village Circle",
                "area_name": "AL BARSHA SOUTH FOURTH",
                "project_name": "BLOOM TOWERS",
                "project_source": "dld_pair",
            },
        ],  # fmt: skip
    )
    found = (await service.get_project_search("JVC")).projects
    assert ("Jumeirah Village Circle", "master") in {(p.name, p.filter_type) for p in found}
    # A word that starts its place's name is not expanded: "downtown" still finds Downtown Views.
    assert service._expand_abbreviations("downtown views") == "downtown views"
