"""The Analytics master -> project -> building hierarchy (holocron.market.analytics_hierarchy)."""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime

from holocron.market import analytics_hierarchy as hierarchy
from holocron.market import dxbi_profile
from tests.test_market_release import database, live, warehouse  # noqa: F401  (fixtures)


def _rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_curated_lists_name_their_evidence_and_never_chain() -> None:
    for path, target in (
        (hierarchy.MASTER_ALIASES_CSV, "master"),
        (hierarchy.PROJECT_ALIASES_CSV, "project"),
        (hierarchy.PROJECT_MASTERS_CSV, "master"),
    ):
        rows = _rows(path)
        assert rows and all(row[target] and row["reason"] and row["evidence"] for row in rows)
    aliases = {hierarchy._py_key(row["alias"]) for row in _rows(hierarchy.PROJECT_ALIASES_CSV)}
    targets = {hierarchy._py_key(row["project"]) for row in _rows(hierarchy.PROJECT_ALIASES_CSV)}
    # A target is never itself an alias: one lookup reaches the project.
    assert not aliases & targets


def test_dld_sub_communities_fold_into_their_community_master() -> None:
    # Decision 2 (2026-10-21): Dubai Hills' 20 DLD sub-masters, the Springs, Meadows and Lakes.
    masters = {row["alias"]: row["master"] for row in _rows(hierarchy.MASTER_ALIASES_CSV)}
    assert masters["DUBAI HILLS - MAPLE 1"] == "Dubai Hills Estate"
    assert masters["Springs - 3"] == "The Springs"
    assert masters["Meadows 9"] == "The Meadows"
    assert masters["Lakes - Hattan II"] == "The Lakes"
    assert masters["Silicon Oasis"] == "Dubai Silicon Oasis"


def test_keys_ignore_case_punctuation_and_dxbi_project_labels() -> None:
    key = hierarchy._py_key
    assert key("MERANO TOWER") == key("Merano Tower")
    assert key("PARK VILLA\\'S 2") == key("Park Villas 2")
    assert key("INDIGO VILLE5") == key("Indigo Ville 5")
    assert key("Binghatti Skyrise (all buildings)") == key("Binghatti Skyrise")


@live
def test_one_spelling_one_master_and_merged_buildings(warehouse) -> None:  # noqa: F811
    loaded = datetime(2026, 7, 1, tzinfo=UTC)

    def sale(key, building, project="", unit="", area="Business Bay"):
        return {
            "sale_key": key, "transaction_date": date(2026, 6, 1), "unit_number": unit,
            "building_name": building, "building_key": building.lower().replace(" ", ""),
            "project_name": project, "area_name": area, "area_key": area.lower().replace(" ", ""),
            "size_sqft": 800.0, "sale_amount_aed": 1_000_000, "property_type": "Apartment",
            "bedrooms": "1 Bed", "market_status": "Ready", "loaded_at": loaded,
        }  # fmt: skip

    def profile(key, project, master, building, source="dld_pair"):
        return [key, master, "Business Bay", project, source, building, "dxbi"]

    # Merano: DLD's capitals on ten sales of "Merano" (one paired to a Dubai Hills master), DXBI's
    # spelling on "Merano Tower" sales of the same DLD building; one sale paired to another tower.
    sales = [sale(f"m{i}", "Merano", "Merano Tower", unit=f"10{i}") for i in range(10)]
    sales += [sale(f"t{i}", "Merano Tower", "Merano Tower", unit=f"20{i}") for i in range(3)]
    sales += [sale("stray", "Merano", unit="999")]
    sales += [sale("villa", "Cedre Villa 1", "Cedre Villas", area="Silicon Oasis")]
    profiles = [
        profile(f"m{i}", "MERANO TOWER", "DUBAI HILLS - MAPLE 1" if i == 0 else "Business Bay",
                "Merano")
        for i in range(10)
    ]  # fmt: skip
    profiles += [profile(f"t{i}", "Merano Tower", "Business Bay", "Merano Tower") for i in range(3)]
    profiles += [profile("stray", "SAMI Q TOWER", "Business Bay", "Merano")]
    profiles += [profile("villa", "CEDRE VILLAS", "Silicon Oasis", "Cedre Villa 1")]
    columns = list(sales[0])
    warehouse.insert_rows(
        table="dxbi_sales_unit_events",
        rows=[[row[c] for c in columns] for row in sales],
        column_names=columns,
    )
    warehouse.insert_rows(
        table="dxbi_sale_profile",
        rows=profiles,
        column_names=[
            "sale_key", "master_project", "area_name", "project_name", "project_source",
            "building_name", "building_source",
        ],
    )  # fmt: skip
    # DLD's unit register: Merano's units, one DLD building (area 526, land 95, building 1).
    units = [f"10{i}" for i in range(10)] + [f"20{i}" for i in range(3)] + ["301", "302"]
    warehouse.insert_rows(
        table="dld_od_units_bronze",
        rows=[
            ["snap", "2026-05-16", "MERANO TOWER", unit, 526, "95", "1", index + 1, "1 B/R", 70.0]
            for index, unit in enumerate(units)
        ],
        column_names=[
            "run_id", "scraped_at", "project_en", "unit_number", "area_id", "land_number",
            "building_number", "property_id", "rooms_en", "actual_area",
        ],
    )  # fmt: skip

    built = hierarchy.build_hierarchy(warehouse)
    assert built["analytics_projects"] == 3

    projects = dict(
        warehouse.query(
            "SELECT project_key, (project_name, master_name) FROM analytics_projects"
        ).result_rows
    )
    # DXBI's spelling; the most common master, so the one Dubai Hills pairing does not split it.
    assert projects["meranotower"] == ("Merano Tower", "Business Bay")
    assert projects["cedrevillas"] == ("Cedre Villas", "Dubai Silicon Oasis")
    buildings = warehouse.query(
        "SELECT building_name, project_key, records, dld_building, arraySort(spellings)"
        " FROM analytics_buildings"
    ).result_rows
    merano = next(row for row in buildings if row[1] == "meranotower")
    # "Merano" and "Merano Tower" sit on one DLD building: one building.
    assert merano[2] == 14 and merano[3] == "526/95/1"
    assert sorted(set(merano[4])) == ["Merano", "Merano Tower"]
    stock = dict(
        warehouse.query(
            "SELECT scope_id, (units, units_source, units_at_least) FROM analytics_unit_stock"
            " WHERE scope_level = 'project'"
        ).result_rows
    )
    assert stock["meranotower"] == (15, "buildings", 0)

    dxbi_profile.create_tables(warehouse)
    dxbi_profile.build_profile(warehouse, "dxbi_sales_listed")
    listed = dict(
        warehouse.query(
            "SELECT sale_key, (scope_name, master_name, building_display, stray)"
            " FROM dxbi_sales_listed"
        ).result_rows
    )
    assert listed["m0"] == ("Merano Tower", "Business Bay", "Merano", 0)
    assert listed["t0"][0:3] == ("Merano Tower", "Business Bay", "Merano")
    # Filed under another project than its building's: kept there, marked for review.
    assert listed["stray"][0] == "Sami Q Tower" and listed["stray"][3] == 1


@live
def test_unit_keys_read_dxbi_and_dld_formats_alike(warehouse) -> None:  # noqa: F811
    # DXBI writes "FLAT 415" and "0103" where DLD writes 415 and 103: one unit each, else a
    # tower's traded units outnumber its register and the page drops the register count.
    same = [["FLAT 415", "415", "Unit No. 415"], ["A-0101", "A 101", "a101"],
            ["2510 (Q 3)", "2510"]]  # fmt: skip
    different = ["101", "1001", "G101", "A101"]
    texts = [text for group in same for text in group] + different
    keys = warehouse.query(
        "SELECT " + ", ".join(hierarchy.unit_key(f"'{text}'") for text in texts)
    ).result_rows[0]
    by_text = dict(zip(texts, keys, strict=True))
    for group in same:
        assert len({by_text[text] for text in group}) == 1, group
    assert len({by_text[text] for text in different}) == len(different)
    shop, flat = warehouse.query(
        "SELECT "
        + ", ".join(
            hierarchy.non_residential(hierarchy.unit_key(t)) for t in ("'SHOP 1'", "'FLAT 1'")
        )
    ).result_rows[0]
    assert (shop, flat) == (1, 0)


@live
def test_unit_counts_where_names_and_numbers_disagree(warehouse) -> None:  # noqa: F811
    loaded = datetime(2026, 7, 1, tzinfo=UTC)
    rows, profiles = [], []

    def sale(key, building, project, unit, sqft, area, dld_area):
        rows.append({
            "sale_key": key, "transaction_date": date(2026, 6, 1), "unit_number": unit,
            "building_name": building, "building_key": building.lower().replace(" ", ""),
            "project_name": "", "area_name": area, "area_key": area.lower().replace(" ", ""),
            "size_sqft": sqft, "sale_amount_aed": 1_000_000, "property_type": "Apartment",
            "bedrooms": "1 Bed", "market_status": "Ready", "loaded_at": loaded,
        })  # fmt: skip
        profiles.append([key, "", dld_area, project, "dld_pair", building, "dxbi", sqft])

    # Icon Tower 1: DLD files its units under no project, so no register name matches it. Its
    # unit numbers at their floor areas sit in one DLD building; a neighbour repeats the numbers
    # at other areas.
    for i in range(1, 7):
        sale(f"i{i}", "Icon Tower 1", "ICON TOWER 1", f"100{i}", 1076.4, "JLT", "Al Thanyah Fifth")
    # Twin Heights: towers A and B both number 101-104; only the floor areas tell them apart.
    for i in range(1, 5):
        sale(f"a{i}", "Twin Heights A", "TWIN HEIGHTS", f"10{i}", 753.5, "Business Bay", "BB")
        sale(f"b{i}", "Twin Heights B", "TWIN HEIGHTS", f"10{i}", 1291.7, "Business Bay", "BB")
    # Twin Heights A again under another DXBI community spelling: the same building.
    sale("a5", "Twin Heights A", "TWIN HEIGHTS", "104", 753.5, "Business Bay District", "BB")
    # Shore 1 and Shore 2: DLD files only Shore 1's units under the project, so both match it.
    for i in range(1, 5):
        sale(f"s{i}", "Shore 1", "SHORE", f"20{i}", 700.0, "Business Bay", "BB")
        sale(f"t{i}", "Shore 2", "SHORE", f"20{i}", 700.0, "Business Bay", "BB")
    # Format Tower: five registered units, written seven ways, and a parking bay.
    for i, unit in enumerate(["101", "FLAT 101", "Unit No. 102", "0103", "103", "104", "105",
                              "PARKING P1"]):  # fmt: skip
        sale(f"f{i}", "Format Tower", "FORMAT TOWER", unit, 538.2, "Business Bay", "BB")
    columns = list(rows[0])
    warehouse.insert_rows(
        table="dxbi_sales_unit_events",
        rows=[[row[c] for c in columns] for row in rows],
        column_names=columns,
    )
    warehouse.insert_rows(
        table="dxbi_sale_profile",
        rows=profiles,
        column_names=[
            "sale_key", "master_project", "area_name", "project_name", "project_source",
            "building_name", "building_source", "size_sqft",
        ],
    )  # fmt: skip

    units = []

    def unit(project, area, land, building, number, sqm, area_id):
        units.append(["snap", "2026-05-16", project, number, area_id, area, land, building,
                      len(units) + 1, "1 B/R", sqm])  # fmt: skip

    for i in range(1, 9):
        unit("", "Al Thanyah Fifth", "992", "1", f"100{i}", 100.0, 350)
        unit("", "Al Thanyah Fifth", "993", "1", f"100{i}", 60.0, 350)
    for i in range(1, 5):
        unit("TWIN HEIGHTS", "BB", "50", "1", f"10{i}", 70.0, 526)
        unit("TWIN HEIGHTS", "BB", "50", "2", f"10{i}", 120.0, 526)
    for i in range(1, 6):
        unit("FORMAT TOWER", "BB", "60", "1", f"10{i}", 50.0, 526)
        unit("SHORE", "BB", "70", "1", f"20{i}", 65.0, 526)
    warehouse.insert_rows(
        table="dld_od_units_bronze",
        rows=units,
        column_names=[
            "run_id", "scraped_at", "project_en", "unit_number", "area_id", "area_en",
            "land_number", "building_number", "property_id", "rooms_en", "actual_area",
        ],
    )  # fmt: skip

    hierarchy.build_hierarchy(warehouse)

    links = warehouse.query(
        "SELECT project_key, dld_group, matched FROM analytics_project_dld_keys"
    ).result_rows
    assert links == [("icontower1", "b:350/992/1", 6)]
    buildings = dict(
        warehouse.query("SELECT building_name, dld_building FROM analytics_buildings").result_rows
    )
    twin_a = warehouse.query(
        "SELECT count(), sum(records) FROM analytics_buildings WHERE building_name = 'Twin Heights A'"
    ).result_rows[0]
    assert twin_a == (1, 5)
    # The numbers alone split 4/4 between the twins; the floor areas pick each one's building.
    assert buildings["Twin Heights A"] == "526/50/1"
    assert buildings["Twin Heights B"] == "526/50/2"
    assert buildings["Icon Tower 1"] == "350/992/1"
    stock = dict(
        warehouse.query(
            "SELECT scope_id, (units, units_source, units_at_least, units_traded)"
            " FROM analytics_unit_stock WHERE scope_level = 'project'"
        ).result_rows
    )
    # The register's 8 units, not "at least 6 traded".
    assert stock["icontower1"] == (8, "buildings", 0, 6)
    assert stock["twinheights"] == (8, "buildings", 0, 8)
    # Seven spellings of five units and a parking bay are five units traded: the register counts.
    assert stock["formattower"] == (5, "buildings", 0, 5)
    building_stock = dict(
        warehouse.query(
            "SELECT b.building_name, (s.units, s.units_source) FROM analytics_buildings AS b"
            " INNER JOIN analytics_unit_stock AS s"
            " ON s.scope_level = 'building' AND s.scope_id = b.building_id"
        ).result_rows
    )
    # One DLD building is one building: matched by two, its 5 units are neither's.
    assert building_stock["Shore 1"] == (4, "units_traded")
    assert building_stock["Shore 2"] == (4, "units_traded")
