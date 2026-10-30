"""The live loader gives the matcher only the DXBI / Transactions rows an import can touch."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.crm import owner_match_loader as loader
from app.crm import owner_queries
from app.crm.owner_matcher import match_row, source_place

HIERARCHY = [
    {"name_key": c, "community_key": c, "project_key": "", "building_id": c}
    for c in ("damachills2", "damachills", "alfurjan", "citywalk")
] + [
    {"name_key": "navitastowere", "community_key": "damachills2", "project_key": "navitas"},
    {"name_key": "aziziberton", "community_key": "alfurjan", "project_key": ""},
]
NAVITAS = {
    "master_project": "DAMAC HILLS 2",
    "building_name": "NAVITAS ( E )@AKOYA OXYGEN",
    "unit_number": "1410",
    "property_type": "Hotel Rooms",
    "size_unknown": "31.01",
    "transaction_price_aed": "460000",
    "transaction_date": "2022-05-20",
}
BERTON = {
    "master_project": "Al Furjan",
    "building_name": "Azizi Berton",
    "unit_number": "211",
    "size_unknown": "40",
    "transaction_price_aed": "700000",
}


def dxbi(place: tuple[str, str, str], unit: str, amount: int, day: str, **fields: Any) -> dict:
    area, project, building = place
    return {
        "family": fields.pop("family", "sale"),
        "event_key": f"{building}-{unit}-{amount}",
        "event_date": day,
        "amount": amount,
        "unit_number": unit,
        "area_name": area,
        "project_name": project,
        "building_name": building,
        "size_sqft": 334.0,
        "property_type": "Apartment",
        **fields,
    }


NAVITAS_PLACE = ("Damac Hills 2", "Navitas", "Navitas Tower E")
BERTON_PLACE = ("Al Furjan", "", "Azizi Berton")
OTHER_PLACE = ("Business Bay", "", "Executive Towers")
PLACES = [
    {"family": "sale", "area_name": a, "project_name": p, "building_name": b, "location_name": ""}
    for a, p, b in (NAVITAS_PLACE, BERTON_PLACE, OTHER_PLACE)
]


@pytest.fixture
def queries(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    calls = {
        "fetch_place_hierarchy": AsyncMock(return_value=HIERARCHY),
        "fetch_registry_places": AsyncMock(return_value=[]),
        "fetch_matcher_places": AsyncMock(return_value=PLACES),
        "fetch_matcher_events": AsyncMock(
            return_value=[dxbi(NAVITAS_PLACE, "1410", 460000, "2022-05-20")]
        ),
        "fetch_matcher_registry": AsyncMock(return_value=[]),
    }
    for name, mock in calls.items():
        monkeypatch.setattr(owner_queries, name, mock)
    return calls


async def test_the_loader_reads_only_the_places_the_import_names(queries) -> None:
    index = await loader.load_sales_index([NAVITAS])
    wanted = queries["fetch_matcher_events"].call_args.args[0]
    assert {row["building_name"] for row in wanted} == {"Navitas Tower E"}
    assert match_row(NAVITAS, index).outcome == "matched_sale"


async def test_two_communities_in_one_import_load_both_places(queries) -> None:
    await loader.load_sales_index([NAVITAS, BERTON])
    wanted = queries["fetch_matcher_events"].call_args.args[0]
    assert {row["building_name"] for row in wanted} == {"Navitas Tower E", "Azizi Berton"}


async def test_transactions_are_fetched_by_amount_with_the_two_dirham_tolerance(queries) -> None:
    await loader.load_sales_index([NAVITAS, {**BERTON, "transaction_price_aed": "700000.5"}])
    amounts = queries["fetch_matcher_registry"].call_args.args[0]
    assert set(range(459998, 460003)) <= set(amounts)
    assert set(range(699998, 700004)) <= set(amounts)
    assert len(amounts) == len(set(amounts))


async def test_a_row_with_no_price_or_no_place_asks_for_nothing(queries) -> None:
    await loader.load_sales_index([{"unit_number": "5", "transaction_price_aed": "100"}])
    queries["fetch_matcher_events"].assert_not_called()
    queries["fetch_matcher_registry"].assert_not_called()
    await loader.load_sales_index(
        [{k: v for k, v in NAVITAS.items() if k != "transaction_price_aed"}]
    )
    queries["fetch_matcher_registry"].assert_not_called()


async def test_a_transactions_only_sale_is_matched_through_the_loaded_rows(queries) -> None:
    queries["fetch_matcher_events"].return_value = []
    queries["fetch_matcher_registry"].return_value = [
        {
            "instance_date": "2023-08-28",
            "procedure_name_en": "Sell",
            "actual_worth": 460000,
            "procedure_area": 28.81,
            "property_type_en": "Unit",
            "area_name_en": "Wadi Al Safa 5",
            "master_project_en": "DAMAC HILLS 2",
            "project_name_en": "NAVITAS",
            "building_name_en": "Navitas Tower E",
            "unit_number": "",
            "community_name": "Damac Hills 2",
            "match_status": "dld_only",
            "dxbi_sale_key": "",
            "transaction_id": "t1",
        }
    ]
    index = await loader.load_sales_index([{**NAVITAS, "unit_number": "9999"}])
    assert match_row({**NAVITAS, "unit_number": "9999"}, index).outcome in (
        "matched_registry_sale",
        "matched_registry_sale_no_unit",
    )


async def test_blank_dxbi_labels_are_filled_from_the_place_catalog(queries) -> None:
    # DXBI stores a blank project for four sales in five; the catalog names it (the snapshot the
    # offline run used was normalised the same way).
    queries["fetch_matcher_places"].return_value = [
        {**PLACES[0], "project_name": "", "building_name": "Navitas Tower E"}
    ]
    queries["fetch_registry_places"].return_value = [
        {
            "location_id": 1,
            "path_key": "navitastowereakoyaoxygen",
            "building_key": "navitastowere",
            "area_key": "damachills2",
            "match_rank": 1,
            "building_label": "Navitas Tower E",
            "project_label": "Navitas",
            "area_label": "Damac Hills 2",
        }
    ]
    queries["fetch_matcher_events"].return_value = [
        dxbi(("Damac Hills 2", "", "Navitas Tower E"), "1410", 460000, "2022-05-20")
    ]
    index = await loader.load_sales_index([NAVITAS])
    (sale,) = index.sales_at(source_place(NAVITAS, index.places), Decimal(460000))
    assert sale["project_name"] == "Navitas"
    assert match_row(NAVITAS, index).outcome == "matched_sale"


def test_identical_rows_are_matched_once_and_aliases_are_learned_per_call() -> None:
    from app.crm.owner_matcher import SalesIndex
    from app.crm.owner_places import PlaceIndex

    index = SalesIndex(
        [dxbi(NAVITAS_PLACE, "1410", 460000, "2022-05-20")], PlaceIndex(HIERARCHY, {}, {}), []
    )
    results = loader.match_sources(index, [NAVITAS, dict(NAVITAS), {**NAVITAS, "unit_number": "5"}])
    assert results[0] is results[1]
    assert results[0].outcome == "matched_sale"
    assert results[2].outcome != "matched_sale"
