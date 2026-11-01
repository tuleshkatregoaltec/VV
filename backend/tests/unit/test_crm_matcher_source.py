"""The matcher's input is built once, at parse time, and is the same offline and live."""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

from openpyxl import Workbook

from app.crm.identity import ParsedContact
from app.crm.import_parsing import (
    _inspect_xlsx,
    _parse_xlsx,
    matcher_source_from_evidence,
)

HEADERS = [
    "NameEn",
    "Mobile",
    "Master Project",
    "Project",
    "BuildingNameEn",
    "UnitNumber",
    "Size",
    "ProcedureValue",
    "Regis",
    "ProcedurePartyTypeNameEn",
    "ProcedureNameEn",
]
NAVITAS = "NAVITAS ( E )@AKOYA OXYGEN"


def workbook(rows: list[list[Any]]) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def parse(rows: list[list[Any]]) -> list[ParsedContact]:
    data = workbook(rows)
    profiles = _inspect_xlsx(data, "Fixture Tower.xlsx")
    candidates, _ = _parse_xlsx(data, "Fixture Tower.xlsx", profiles)
    return candidates


ROW = [
    "Zainab Fixture-Owner",
    "0501234567",
    "DAMAC HILLS 2",
    "",
    NAVITAS,
    1410,
    31.01,
    460000,
    datetime(2022, 5, 20),
    "Buyer",
    "Mortgage Registration",
]


def test_parse_stores_the_matcher_source_with_property_fields_only() -> None:
    (candidate,) = parse([ROW])
    source = candidate.evidence["matcher_source"]
    assert source["master_project"] == "DAMAC HILLS 2"
    assert source["building_name"] == NAVITAS
    assert source["unit_number"] == "1410"
    assert source["transaction_price_aed"] == "460000"
    assert source["transaction_date"] == "2022-05-20"
    assert source["procedure_type"] == "Mortgage Registration"
    # who the owner is never reaches the matcher
    assert "Zainab" not in str(source) and "0501234567" not in str(source)
    assert "party_role" not in source


def test_the_shadow_script_reads_the_same_matcher_source_as_the_importer(tmp_path) -> None:
    from scripts.crm import shadow_owner_matching as shadow

    path = tmp_path / "Fixture Tower.xlsx"
    path.write_bytes(workbook([ROW, [*ROW[:7], 999000, *ROW[8:]]]))
    live = parse([ROW, [*ROW[:7], 999000, *ROW[8:]]])
    (sheet,) = shadow.read_workbook(path, None)
    assert [item.source for item in sheet.rows] == [c.evidence["matcher_source"] for c in live]


def test_the_rebuilt_source_equals_the_parse_time_source_for_a_stored_claim() -> None:
    (candidate,) = parse([ROW])
    stored = dict(candidate.evidence)
    stored.pop("matcher_source")
    rebuilt = matcher_source_from_evidence(
        stored,
        transaction_date=date(2022, 5, 20),
        transaction_price_aed=460000,
        procedure_type="Mortgage Registration",
    )
    assert rebuilt == candidate.evidence["matcher_source"]


def test_a_claim_without_source_fields_is_rebuilt_from_its_property_columns() -> None:
    rebuilt = matcher_source_from_evidence(
        {},
        transaction_date=date(2022, 5, 20),
        transaction_price_aed=460000,
        procedure_type="Sell",
        area_name="Damac Hills 2",
        project_name="Navitas",
        building_name="Navitas Tower E",
        unit_number="1410",
        property_type="Apartment",
    )
    assert rebuilt == {
        "area_name": "Damac Hills 2",
        "project_name": "Navitas",
        "building_name": "Navitas Tower E",
        "unit_number": "1410",
        "property_type": "Apartment",
        "procedure_type": "Sell",
        "transaction_price_aed": "460000",
        "transaction_date": "2022-05-20",
    }


def test_an_autofilled_location_is_rebuilt_from_the_restored_value() -> None:
    evidence = {
        "source_fields": {"building_name": "Aster"},
        "original_fields": {"building_name": "Aster"},
        "original_property_fields": {"building_name": "Viridis A", "project_name": ""},
    }
    rebuilt = matcher_source_from_evidence(evidence)
    assert rebuilt["building_name"] == "Viridis A"


def test_an_audited_claim_whose_source_fields_carry_no_location_uses_its_property_columns() -> None:
    # Source-audited workbooks stored only size and type in ``source_fields``; the location is in
    # the claim's own columns. Without it every such row would have no place at all.
    rebuilt = matcher_source_from_evidence(
        {"source_fields": {"size_sqm": "92.92", "property_type": "Unit"}},
        transaction_date=date(2023, 2, 1),
        transaction_price_aed=1650000,
        procedure_type="Sell",
        area_name="Dubai Hills Estate",
        project_name="Park Ridge",
        building_name="Executive Residences 1",
        unit_number="904",
        property_type="Unit",
    )
    assert rebuilt["area_name"] == "Dubai Hills Estate"
    assert rebuilt["building_name"] == "Executive Residences 1"
    assert rebuilt["unit_number"] == "904"
    assert rebuilt["size_sqm"] == "92.92"
