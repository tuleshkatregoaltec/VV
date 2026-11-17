"""Local mapping must preserve provenance and explicitly declared measurement units."""

import csv

from openpyxl import Workbook

from app.crm.import_parsing import _inspect_xlsx, _parse_xlsx
from app.crm.ownership import _source_size
from scripts.crm.clean_owner_workbook import HEADERS
from scripts.crm.map_owner_workbook import export_import_ready, original_rows, prepare_candidates


def test_mapper_declares_sqm_and_retains_notes_without_inventing_a_sale(tmp_path):
    source = tmp_path / "cleaned.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(HEADERS)
    sheet.append(
        [
            "2023-01-02",
            1000000,
            "Dubai Hills",
            "Maple",
            "plot1",
            "villa1",
            "Tower A",
            100,
            "101",
            "1",
            "Flat",
            "42",
            "Buyer",
            "Example",
            "0500000000",
            "AE",
            "Do not contact",
        ]
    )
    workbook.save(source)
    candidates = prepare_candidates(source, size_unit="sqm")
    assert len(candidates) == 1
    candidate = candidates[0]
    assert round(_source_size(candidate), 2) == 1076.39
    assert candidate.evidence["event_family"] == "contact_snapshot"
    assert candidate.evidence["source_contact_notes"] == "Do not contact"
    assert candidate.evidence["source_identity_incomplete"] is False

    ready = tmp_path / "owner-import-ready.xlsx"
    export_import_ready(source, ready, size_unit="sqm")
    data = ready.read_bytes()
    profiles = _inspect_xlsx(data, ready.name)
    imported, total = _parse_xlsx(data, ready.name, profiles)
    assert len(imported) == total == 1
    assert imported[0].evidence["source_size_unit"] == "sqm"
    assert round(_source_size(imported[0]), 2) == 1076.39
    assert imported[0].transaction_price_aed == candidate.transaction_price_aed


def test_provenance_includes_duplicates_but_excludes_rejected_records(tmp_path):
    source = tmp_path / "audit.csv"
    with source.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["source_row_number", "cleaned_row_number"])
        writer.writerows([(2, 2), (3, 2), (4, ""), (5, 3)])
    assert original_rows(source) == {2: [2, 3], 3: [5]}
