"""DXBI's places label records as DXBI's location list does: building, project, area."""

from __future__ import annotations

from holocron.sources.dxbi.places import PLACE_COLUMNS, place_rows
from holocron.sources.dxbi.rental_events import normalize_rental_row
from holocron.sources.dxbi.sales_units import location_key, normalize_sales_row

# A slice of DXBI's location list (property/website/DLDLOV), read 2026-10-09.
TREE = [
    {"id": 1, "name": "Dubai", "parent_id": None, "flag": "C", "dv": "Dubai"},
    {"id": 2, "name": "Jabal Ali First", "parent_id": 1, "flag": "A", "dv": "Jabal Ali First"},
    {"id": 3, "name": "Discovery Gardens", "parent_id": 2, "flag": "M",
     "dv": "Discovery Gardens"},
    {"id": 4, "name": "Mogul Cluster", "parent_id": 3, "flag": "P",
     "dv": "Mogul Cluster, Discovery Gardens"},
    {"id": 5, "name": "Mog 197", "parent_id": 4, "flag": "B",
     "dv": "Mog 197, Mogul Cluster, Discovery Gardens"},
    {"id": 6, "name": "Dubai Investment Park Second", "parent_id": 1, "flag": "A",
     "dv": "Dubai Investment Park Second"},
    {"id": 7, "name": "Damac Riverlink", "parent_id": 6, "flag": "P",
     "dv": "Damac Riverlink, Dubai Investment Park Second"},
    {"id": 8, "name": "Hor Al Anz", "parent_id": 1, "flag": "A", "dv": "Hor Al Anz"},
    {"id": 9, "name": "Hadaeq Sheikh Mohammed Bin Rashid", "parent_id": 1, "flag": "A",
     "dv": "Hadaeq Sheikh Mohammed Bin Rashid"},
    {"id": 10, "name": "Eden Hills", "parent_id": 9, "flag": "P", "dv": "Eden Hills"},
    {"id": 11, "name": "Valencia", "parent_id": 1, "flag": "P",
     "dv": "Valencia (all buildings), Damac Lagoons"},
]  # fmt: skip


def _places() -> dict[tuple[object, object], dict]:
    rows = [dict(zip(PLACE_COLUMNS, row, strict=True)) for row in place_rows(TREE, "run")]
    return {(row["building_key"], row["area_key"]): row for row in rows}


def _sale(location: str) -> dict:
    event = normalize_sales_row(
        {
            "unit_number": "12",
            "location_text": f"{location} Ready Apartment, Floor 1, No. 12",
            "amount_text": "AED 1,000,000",
            "specs_text": "1,000 sqft 2 Beds",
            "date_text": "1, Oct 2026 Developer",
        }
    )
    assert event
    return event


def _labels(location: str) -> tuple[str, str, str]:
    sale = _sale(location)
    place = _places()[(sale["building_key"], sale["area_key"])]
    return place["building_label"], place["project_label"], place["area_label"]


def test_a_building_sits_in_its_project_and_a_project_is_no_building() -> None:
    """46% of DXBI sales are of a project (2026-10-08) and showed it as their building; the
    stored record keys find the place DXBI printed, and the place says which it is."""
    assert _labels("Mog 197, Mogul Cluster, Discovery Gardens") == (
        "Mog 197",
        "Mogul Cluster",
        "Discovery Gardens",
    )
    assert _labels("Damac Riverlink, Dubai Investment Park Second") == (
        "",
        "Damac Riverlink",
        "Dubai Investment Park 2",
    )
    # The search box's "(all buildings)" hint is not part of the project's name.
    assert _labels("Valencia (all buildings), Damac Lagoons")[1] == "Valencia"


def test_a_single_name_is_an_area_or_a_project_as_dxbi_lists_it() -> None:
    """Text alone cannot tell a single-name area ("Hor Al Anz") from a single-name project
    ("Eden Hills"), and neither prints an area: DXBI's list says which, and where it is."""
    assert _labels("Hor Al Anz") == ("", "", "Hor Al Anz")
    assert _labels("Eden Hills") == ("", "Eden Hills", "Hadaeq Sheikh Mohammed Bin Rashid")
    # A plot named by its area alone stores the name as both building and area.
    plot = normalize_sales_row(
        {
            "location_text": "Hor Al Anz Plot, Floor u-hidden, No. 630",
            "amount_text": "AED 1,000,000",
            "specs_text": "5,000 sqft",
            "date_text": "1, Oct 2026 Individual",
        }
    )
    assert plot
    assert _places()[(plot["building_key"], plot["area_key"])]["area_label"] == "Hor Al Anz"


def test_a_lease_finds_its_place_by_its_whole_path() -> None:
    lease = normalize_rental_row(
        {
            "columns": [
                {"id": "PATH_NAME", "text": "Damac Riverlink, Dubai Investment Park Second "
                 "Apartment , No. 101"},
                {"id": "PROP_SIZES", "text": "1 Bed 700 sqft"},
                {"id": "TOTAL_PRICES", "text": "60,000 New"},
                {"id": "START_DATE", "text": "1 Jan, 2026 - 31 Dec, 2026 12 Months"},
            ]
        }
    )  # fmt: skip
    assert lease
    rows = [dict(zip(PLACE_COLUMNS, row, strict=True)) for row in place_rows(TREE, "run")]
    place = next(row for row in rows if row["path_key"] == location_key(lease["location_name"]))
    assert (place["building_label"], place["project_label"]) == ("", "Damac Riverlink")
