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
