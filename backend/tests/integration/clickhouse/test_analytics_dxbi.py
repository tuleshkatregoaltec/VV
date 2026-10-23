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
    rows = await query(
        queries.project_sales_summary("project"),
        {"project_name": "DLD Label", "usage": "Residential"},
    )
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


async def test_configuration_periods_end_on_the_newest_sale_and_keep_old_sparse_bedrooms(
    dxbi,  # noqa: F811
):
    """Recent periods end on the newest recorded sale, not today: days not loaded yet are no days
    without sales. An old off-plan launch is not current activity; sparse homes must not
    disappear; a future-dated record does not move the end."""
    from datetime import date, timedelta

    await dxbi(
        sales=[
            sale(
                "ready",
                project_name="Mixed Tower",
                transaction_date=date.today() - timedelta(days=10),
            ),
            sale(
                "year-old",
                project_name="Mixed Tower",
                transaction_date=date.today() - timedelta(days=370),
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
    assert summary.recent_periods_end == date.today() - timedelta(days=10)
    # 370 days before today is within the 12 months that end 10 days ago.
    assert rows["all", "1 B/R"].sales_last_12m == 2
    for segment in ("all", "off_plan"):
        assert rows[segment, "4 B/R"].sale_count == 1
        assert rows[segment, "4 B/R"].sales_last_12m == 0
        assert rows[segment, "5 B/R"].sales_last_12m == 0
        assert rows[segment, "4 B/R"].price_change_yoy_pct is None
        assert rows[segment, "4 B/R"].sales_momentum_pct is None
    narrow = await queries.fetch_project_configuration_sales(
        {
            "project_name": "Mixed Tower",
            "reg_type_en": "Off-Plan Properties",
            "usage": "Residential",
        },
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
    # The building keeps its place; it is its own scope and names its project.
    buildings = [p for p in found if p.filter_type == "building"]
    assert [(p.name, p.project, p.scope_kind) for p in buildings] == [
        ("Lake Shore Tower", "JLT Cluster X", "Building")
    ]
    assert buildings[0].building_id == "lakeshoretower|downtowndubai"
    # An empty search lists scopes only.
    assert not any(
        p.filter_type == "building" for p in (await service.get_project_search("")).projects
    )


async def test_a_project_header_names_its_sources(dxbi, warehouse):  # noqa: F811
    """DXBI transactions hold no developer, handover or unit count: DXBInteract's building list
    gives the developer and handover; Holocron's unit stock the units, naming its source."""
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
    # Holocron's unit stock counts the units (holocron.market.analytics_hierarchy).
    await warehouse.command(
        "INSERT INTO analytics_unit_stock (scope_level, scope_id, units, units_source,"
        " units_at_least, units_traded, buildings, mix_rooms, mix_units, mix_median_sqft)"
        " VALUES ('project', 'lakeshoretower', 477, 'dxbi_buildings', 0, 1, 1,"
        " ['1 B/R', 'Studio'], [400, 77], [820, 450])"
    )
    summary = await service.get_project_summary("Lake Shore Tower", "project")
    meta = summary.project
    assert (meta.developer_name, str(meta.completion_date), meta.no_of_units) == (
        "Al Bodor",
        "2012-01-21",
        477,
    )
    assert meta.no_of_buildings == 1 and meta.units_traded == 1 and not meta.units_at_least
    assert meta.field_sources["developer_name"] == "dxbi_buildings"
    assert meta.field_sources["completion_date"] == "dxbi_buildings"
    assert meta.field_sources["no_of_units"] == "dxbi_buildings"
    assert [(u.rooms, u.count) for u in summary.unit_composition] == [
        ("Studio", 77),
        ("1 B/R", 400),
    ]


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


async def test_an_office_tower_shows_its_commercial_records_not_zeros(dxbi):  # noqa: F811
    """014 TOWER (offices and shops) showed 0 under the residential-only view: 'auto' shows the
    usage the scope has, reports both usages' counts, and groups offices by type."""
    await dxbi(
        sales=[
            sale("o1", building_name="Office Tower", property_type="Office", bedrooms=""),
            sale(
                "o2",
                building_name="Office Tower",
                property_type="Office",
                bedrooms="",
                unit_number="102",
            ),
            sale(
                "s1",
                building_name="Office Tower",
                property_type="Shop",
                bedrooms="",
                unit_number="G01",
            ),
            sale("h1", building_name="Mixed Tower", unit_number="201"),
            sale(
                "h2",
                building_name="Mixed Tower",
                property_type="Office",
                bedrooms="",
                unit_number="202",
            ),
        ],  # fmt: skip
        leases=[lease("l1", building_name="Office Tower", property_type="Office", bedrooms="")],
    )
    auto = await service.get_project_summary("Office Tower", "project")
    assert auto.usage == "Commercial"
    assert auto.usage_counts["Commercial"].sales == 3
    assert auto.usage_counts["Commercial"].leases == 1
    assert auto.usage_counts["Residential"].sales == 0
    assert auto.sales.transaction_count == 3
    assert {row.rooms for row in auto.by_rooms} >= {"Office", "Shop"}
    # Configuration Analysis groups offices and shops by type (bedrooms do not apply).
    assert {row.rooms for row in auto.configuration_analysis} == {"Office", "Shop"}
    # A mixed tower shows its homes; its office is one click away, and counted.
    mixed = await service.get_project_summary("Mixed Tower", "project")
    assert (mixed.usage, mixed.sales.transaction_count) == ("Residential", 1)
    assert mixed.usage_counts["Commercial"].sales == 1
    office = await service.get_project_summary("Mixed Tower", "project", usage="Commercial")
    assert (office.usage, office.sales.transaction_count) == ("Commercial", 1)
    # A usage asked for explicitly is shown even when empty (no silent switch).
    empty = await service.get_project_summary("Office Tower", "project", usage="Residential")
    assert (empty.usage, empty.sales.transaction_count) == ("Residential", 0)
    # The charts follow the same resolution.
    trends = await service.get_project_trends("Office Tower", 365)
    assert sum(point.transaction_count for point in trends.data) == 3
    distribution = await service.get_project_price_distribution("Office Tower")
    assert distribution.all.sale_count == 3


async def test_commercial_leases_line_up_with_sales_by_their_dld_type(dxbi):  # noqa: F811
    """DXBI lists every office lease as "Commercial"; the profile takes Office from the matched
    DLD contract, so the tower's offices show sales, leases and a yield in one row."""
    await dxbi(
        sales=[sale("o1", building_name="Office Tower", property_type="Office", bedrooms="")],
        leases=[
            lease("l1", building_name="Office Tower", property_type="Commercial", bedrooms=""),
            lease(
                "l2",
                building_name="Office Tower",
                property_type="Commercial",
                bedrooms="",
                unit_number="1102",
            ),
        ],  # fmt: skip
        lease_profiles=[
            {"contract_key": "l1", "property_type": "Office", "property_type_source": "dld_pair"},
        ],
    )
    summary = await service.get_project_summary("Office Tower", "project")
    rows = {row.rooms: row for row in summary.by_rooms}
    assert (rows["Office"].sale_count, rows["Office"].rental_count) == (1, 1)
    # A lease no source types stays apart, and says so.
    assert rows["Commercial (type not recorded)"].rental_count == 1


async def test_a_building_is_its_own_scope_inside_its_project(dxbi, warehouse):  # noqa: F811
    """Selecting a building scopes every figure to it; its project still covers all its
    buildings, lists them with their units, and an old spelling of the project finds it."""
    await dxbi(
        sales=[
            *(
                sale(f"a{i}", building_name="Skyrise Tower A", project_name="Skyrise",
                     unit_number=f"A{i}", sale_amount_aed=1_000_000)
                for i in range(3)
            ),
            *(
                sale(f"b{i}", building_name="Skyrise Tower B", project_name="Skyrise",
                     unit_number=f"B{i}", sale_amount_aed=2_000_000)
                for i in range(2)
            ),
        ]
    )  # fmt: skip
    await warehouse.command(
        "INSERT INTO analytics_project_keys (raw_key, project_key) VALUES ('skyrisetowers', 'skyrise')"
    )
    await warehouse.command(
        "INSERT INTO analytics_unit_stock (scope_level, scope_id, units, units_source,"
        " units_at_least, units_traded, buildings, mix_rooms, mix_units, mix_median_sqft) VALUES"
        " ('building', 'skyrisetowera|downtowndubai', 1078, 'dld_units', 0, 3, 1, ['Studio'],"
        " [1078], [400]),"
        " ('project', 'skyrise', 1080, 'buildings', 0, 5, 2, [], [], [])"
    )
    search = await service.get_project_search("skyrise tower a")
    building = next(p for p in search.projects if p.filter_type == "building")
    assert (building.name, building.project) == ("Skyrise Tower A", "Skyrise")

    tower = await service.get_project_summary(building.building_id, "building")
    assert tower.sales.transaction_count == 3
    assert tower.sales.total_volume == 3_000_000
    meta = tower.project
    assert (meta.scope_level, meta.parent_project, meta.no_of_units, meta.units_source) == (
        "building",
        "Skyrise",
        1078,
        "dld_units",
    )
    trends = await service.get_project_trends(building.building_id, 365, "building")
    assert sum(p.transaction_count for p in trends.data) == 3

    # The project by an old spelling: both buildings, listed with their units.
    project = await service.get_project_summary("Skyrise Towers", "project")
    assert project.sales.transaction_count == 5
    assert project.project.no_of_units == 1080 and project.project.no_of_buildings == 2
    assert [(b.name, b.sales, b.units) for b in project.buildings] == [
        ("Skyrise Tower A", 3, 1078),
        ("Skyrise Tower B", 2, None),
    ]


async def test_a_master_adds_up_its_projects_registered_units(dxbi, warehouse):  # noqa: F811
    """A master shows its projects' register counts added up and how many projects have one;
    a project known only by its traded units adds nothing to the register total."""
    await dxbi(
        sales=[
            sale("a", project_name="Tower One", building_name="Tower One"),
            sale("b", project_name="Tower Two", building_name="Tower Two"),
        ]
    )
    await warehouse.command(
        "INSERT INTO analytics_unit_stock (scope_level, scope_id, units, units_source,"
        " units_at_least, units_traded, buildings) VALUES"
        " ('project', 'towerone', 300, 'dxbi_buildings', 0, 1, 1),"
        " ('project', 'towertwo', 12, 'units_traded', 1, 12, 1)"
    )
    master = (await service.get_project_summary("Downtown Dubai", "master")).project
    assert (master.no_of_units, master.no_of_projects, master.projects_with_units) == (300, 2, 1)
    assert master.units_source == "projects_rollup"


async def test_summary_window_bounds_counts_prices_rent_and_yield_without_truncating_history(dxbi):  # noqa: F811
    """Headline metrics share a window; historical comparisons retain their older evidence."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Asia/Dubai")).date()
    await dxbi(
        sales=[
            sale(
                key,
                project_name="Window Tower",
                unit_number=key,
                transaction_date=today - timedelta(days=age),
                sale_amount_aed=price,
                market_status=status,
            )
            for key, age, price, status in [
                ("today", 0, 1000000, "Ready"),
                ("offplan", 0, 2000000, "Offplan"),
                ("first-day", 364, 3000000, "Ready"),
                ("before-window", 365, 9000000, "Ready"),
                ("future", -1, 9000000, "Ready"),
            ]
        ]
        + [sale("office", project_name="Window Tower", property_type="Office")],
        leases=[
            lease(
                key,
                building_name="Window Tower",
                location_name="Window Tower, Downtown Dubai",
                area_name="Downtown Dubai",
                lease_start=today - timedelta(days=age),
                annual_rent_aed=rent,
            )
            for key, age, rent in [
                ("today", 0, 120000),
                ("first-day", 364, 180000),
                ("before-window", 365, 900000),
                ("future", -1, 900000),
            ]
        ],
    )
    all_dates = await service.get_project_summary("Window Tower")
    year = await service.get_project_summary("Window Tower", summary_days=365)
    month = await service.get_project_summary("Window Tower", summary_days=30)
    assert year.sales.transaction_count == 3
    assert year.sales.total_volume == 6000000
    assert year.sales.avg_price == 2000000
    assert year.sales.median_price == 2000000
    assert year.sales.avg_price_sqft == 2500
    assert year.rentals.contract_count == 2
    assert year.rentals.median_annual_rent == 180000
    assert year.rentals.total_annual_value == 300000
    # Secondary median is 3M. The off-plan price must not enter the yield denominator.
    assert year.overall_gross_yield_pct == 6
    assert month.sales.transaction_count == 2
    assert month.sales.avg_price == 1500000
    assert month.rentals.contract_count == 1
    assert month.rentals.median_annual_rent == 120000
    assert month.overall_gross_yield_pct == 12
    for result in (year, month):
        assert result.usage_counts["Residential"].sales == result.sales.transaction_count
        assert result.usage_counts["Residential"].leases == result.rentals.contract_count
        assert result.usage_counts["Commercial"].sales == 1
        assert result.configuration_analysis == all_dates.configuration_analysis
        assert result.by_rooms == all_dates.by_rooms
        json.dumps(result.model_dump(mode="json"), allow_nan=False)
    assert all_dates.sales.transaction_count == 5
    assert all_dates.rentals.contract_count == 4
    market = await service.get_project_summary("Dubai", "market", summary_days=365)
    assert market.sales == year.sales
    commercial = await service.get_project_summary(
        "Window Tower", usage="Commercial", summary_days=365
    )
    assert commercial.sales.transaction_count == 1
    assert commercial.rentals.contract_count == 0
    assert commercial.overall_gross_yield_pct is None


async def test_empty_summary_window_is_json_safe_and_does_not_change_scope_usage(dxbi):  # noqa: F811
    from datetime import date, timedelta

    await dxbi(
        sales=[
            sale(
                "old-home",
                project_name="Mixed Tower",
                transaction_date=date.today() - timedelta(days=800),
            ),
            sale("office", project_name="Mixed Tower", property_type="Office"),
        ]
    )
    summary = await service.get_project_summary("Mixed Tower", summary_days=365)
    assert summary.usage == "Residential"
    assert summary.sales.transaction_count == 0
    assert summary.sales.avg_price == 0
    assert summary.sales.median_price == 0
    assert summary.rentals.contract_count == 0
    assert summary.overall_gross_yield_pct is None
    assert summary.usage_counts["Residential"].sales == 0
    assert summary.usage_counts["Commercial"].sales == 1
    assert summary.configuration_analysis[0].sale_count == 1
    json.dumps(summary.model_dump(mode="json"), allow_nan=False)
