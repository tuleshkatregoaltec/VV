"""The stage between the legacy lookups and the status: match every row, store the verdict."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.crm import owner_match_stage as stage
from app.crm.identity import ParsedContact
from app.crm.owner_matcher import MATCHER_VERSION, SalesIndex
from app.crm.owner_places import PlaceIndex

COMMUNITIES = ("damachills2", "damachills")
PLACES = PlaceIndex(
    [{"community_key": c, "name_key": c} for c in COMMUNITIES]
    + [{"community_key": "damachills2", "name_key": "navitastowere"}],
    {},
    {},
)
SOURCE = {
    "master_project": "DAMAC HILLS 2",
    "building_name": "NAVITAS ( E )@AKOYA OXYGEN",
    "unit_number": "1410",
    "size_unknown": "31.01",
    "transaction_price_aed": "460000",
    "transaction_date": "2022-05-20",
}


def sale(amount: int, day: str, key: str) -> dict[str, Any]:
    return {
        "family": "sale",
        "event_key": key,
        "event_date": day,
        "amount": amount,
        "unit_number": "1410",
        "building_name": "Navitas Tower E",
        "project_name": "Navitas",
        "area_name": "Damac Hills 2",
        "size_sqft": 334.0,
        "property_type": "Apartment",
    }


def contact(row: int, *, source: dict | None = SOURCE, scope: str | None = None, **changes):
    values: dict[str, Any] = {
        "source_sheet": "Sheet1",
        "source_row_number": row,
        "contact_name": f"Owner {row}",
        "phone_primary": None,
        "phone_alternate": None,
        "email_primary": None,
        "area_name": "Damac Hills 2",
        "project_name": "Navitas",
        "building_name": "Navitas Tower E",
        "unit_number": "1410",
        "property_type": "Apartment",
        "transaction_date": date(2022, 5, 20),
        "transaction_price_aed": 460000,
        "party_role": "Buyer",
        "procedure_type": "Sell",
        "row_fingerprint": f"fp{row}",
    }
    values.update(changes)
    candidate = ParsedContact(**values)
    if source is not None:
        candidate.evidence["matcher_source"] = source
    if scope is not None:
        candidate.evidence["source_import_scope"] = scope
    return candidate


@pytest.fixture
def loaded(monkeypatch: pytest.MonkeyPatch):
    events = [sale(441750, "2016-10-06", "k1"), sale(460000, "2022-05-20", "k2")]
    mock = AsyncMock(side_effect=lambda sources: SalesIndex(events, PLACES, []))
    monkeypatch.setattr(stage, "load_sales_index", mock)
    return mock, events


async def test_every_row_gets_a_verdict_in_its_evidence(loaded) -> None:
    candidates = [contact(2), contact(3)]
    await stage.run_owner_matching(candidates)
    for candidate in candidates:
        match = candidate.evidence["owner_match"]
        assert match["version"] == MATCHER_VERSION
        assert match["matcher_outcome"] == "matched_sale"
        assert match["sale"]["amount_aed"] == 460000
        assert match["later_sale_date"] is None


async def test_the_index_is_loaded_once_per_import_and_only_for_its_rows(loaded) -> None:
    mock, _ = loaded
    candidates = [contact(2, scope="1"), contact(3, scope="1"), contact(2, scope="2")]
    await stage.run_owner_matching(candidates)
    assert mock.await_count == 2
    assert sorted(len(call.args[0]) for call in mock.await_args_list) == [1, 2]


async def test_a_later_sale_of_the_unit_is_recorded_with_the_verdict(loaded) -> None:
    _, events = loaded
    events.append(sale(520000, "2024-02-01", "k3"))
    (candidate,) = [contact(2)]
    await stage.run_owner_matching([candidate])
    assert candidate.evidence["owner_match"]["later_sale_date"] == "2024-02-01"


async def test_nothing_is_loaded_for_no_rows(loaded) -> None:
    mock, _ = loaded
    await stage.run_owner_matching([])
    mock.assert_not_awaited()


def test_a_claim_without_a_stored_source_is_rebuilt_from_its_evidence() -> None:
    candidate = contact(2, source=None, procedure_type="")
    candidate.evidence["source_fields"] = {
        "master_project": "DAMAC HILLS 2",
        "building_name": "NAVITAS ( E )@AKOYA OXYGEN",
        "unit_number": "1410",
        "size_unknown": "31.01",
        "transaction_price_aed": "460000",
    }
    assert stage.candidate_source(candidate) == {
        **{k: v for k, v in SOURCE.items() if k != "transaction_date"},
        "transaction_date": "2022-05-20",
    }


async def test_a_rebuilt_source_is_kept_so_the_next_rematch_reads_the_same_input(loaded) -> None:
    candidate = contact(2, source=None)
    await stage.run_owner_matching([candidate])
    assert candidate.evidence["matcher_source"]["unit_number"] == "1410"


async def test_aliases_are_learned_over_the_whole_import(monkeypatch: pytest.MonkeyPatch) -> None:
    # sheet unit 102 is DXBI's 715 on two different sales: the second row teaches the first
    def registry(amount: int, key: str) -> dict[str, Any]:
        return {
            "instance_date": "2023-01-01",
            "procedure_name_en": "Sell",
            "actual_worth": amount,
            "procedure_area": 107.63,
            "property_type_en": "Unit",
            "area_name_en": "Al Wasl",
            "master_project_en": "City Walk",
            "project_name_en": "CITYWALK RESIDENTIAL",
            "building_name_en": "Citywalk Residential Building 5",
            "unit_number": "715",
            "community_name": "City Walk",
            "match_status": "matched",
            "dxbi_sale_key": key,
            "transaction_id": key,
        }

    places = PlaceIndex([{"community_key": "citywalk", "name_key": "citywalk"}], {}, {})
    rental = {
        **sale(90000, "2021-01-01", "r1"),
        "family": "rental",
        "unit_number": "102",
        "building_name": "Citywalk Residential Building 5",
        "project_name": "",
        "area_name": "City Walk",
        "size_sqft": 1160.0,
    }
    index = SalesIndex([rental], places, [registry(850000, "a"), registry(910000, "b")])
    monkeypatch.setattr(stage, "load_sales_index", AsyncMock(return_value=index))

    def walk(row: int, amount: int) -> ParsedContact:
        return contact(
            row,
            source={
                "master_project": "City Walk",
                "building_name": "Citywalk Residential Building 5",
                "unit_number": "102",
                "size_unknown": "107.63",
                "transaction_price_aed": str(amount),
            },
        )

    candidates = [walk(2, 850000), walk(3, 910000)]
    await stage.run_owner_matching(candidates)
    assert [c.evidence["owner_match"]["matcher_outcome"] for c in candidates] == [
        "matched_sale"
    ] * 2
    assert all("learned_unit_alias" in c.evidence["owner_match"]["warnings"] for c in candidates)
