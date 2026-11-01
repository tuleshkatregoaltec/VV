"""Cleanup preserves evidence and removes only completely equal normalized rows."""

import csv
import hashlib
from datetime import datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook

from scripts.crm import clean_owner_workbook as cleaning


def owner_row(**changes):
    values = [
        datetime(2020, 1, 2),
        1234567.5,
        "Master",
        "Project",
        1,
        2,
        "Building",
        100.5,
        "0012",
        4,
        "Apartment",
        5,
        "Buyer",
        "Private Buyer",
        "001234",
        "Country",
        None,
    ]
    for column, value in changes.items():
        values[cleaning.HEADERS.index(column)] = value
    return tuple(values)


def source(tmp_path, rows, headers=cleaning.HEADERS):
    path = tmp_path / "source.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_only_full_row_duplicates_removed_preserving_parties_notes_contacts_and_history(tmp_path):
    first = owner_row()
    rows = [
        first,
        first,
        owner_row(NameEn="Different Buyer"),
        owner_row(ProcedurePartyTypeNameEn="Seller", NameEn="Private Seller"),
        owner_row(Column1="do not call"),
        owner_row(Mobile="009999"),
        owner_row(Regis=datetime(2018, 1, 2)),
        owner_row(ProcedureValue=7654321),
        owner_row(Size=101.5),
        owner_row(Project=" Project "),
    ]
    path = source(tmp_path, rows)
    original_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    out = tmp_path / "out"
    metrics = cleaning.clean_workbook(path, out)
    assert metrics["retained_rows"] == 8
    assert metrics["exact_raw_duplicate_rows"] == 1
    assert metrics["additional_normalization_duplicate_rows"] == 1
    assert metrics["candidate_event_count"] == 4
    assert metrics["candidate_events_with_buyer_and_seller"] == 1
    assert metrics["candidate_events_single_buyer_or_seller_side"] == 3
    assert metrics["property_signatures_with_multiple_candidate_events"] == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_sha == metrics["source_sha256"]
    workbook = load_workbook(out / "cleaned-owner-records.xlsx")
    assert workbook.sheetnames == ["Sheet1"]
    cleaned = list(workbook.active.values)
    assert cleaned[0] == cleaning.HEADERS
    assert len(cleaned) == 9
    assert {row[13] for row in cleaned[1:]} == {
        "Private Buyer",
        "Different Buyer",
        "Private Seller",
    }
    assert "do not call" in {row[16] for row in cleaned[1:]}
    assert {row[0] for row in cleaned[1:]} == {datetime(2018, 1, 2), datetime(2020, 1, 2)}
    assert {row[1] for row in cleaned[1:]} == {1234567.5, 7654321}
    workbook.close()
    audit = read_csv(out / "source-row-provenance.csv")
    assert len(audit) == len(rows)
    assert audit[1]["status"] == audit[-1]["status"] == "duplicate"
    assert audit[1]["retained_source_row_number"] == audit[-1]["retained_source_row_number"] == "2"
    candidates = read_csv(out / "candidate-events.csv")
    event = next(row for row in candidates if row["original_row_count"] == "7")
    assert (event["buyer_rows"], event["seller_rows"]) == ("4", "1")
    assert "NameEn" not in event and "Mobile" not in event and "Column1" not in event


def test_normalization_preserves_leading_zeros_contacts_and_notes():
    raw = owner_row(
        **{
            "Plot Pre Reg No": 123.0,
            "Building No": 1e20,
            "BuildingNameEn": 400.0,
            "DmSubNo": "0003",
            "LandNumber": 1.25,
            "Mobile": 12345.0,
            "Project": " #N/A ",
            "NameEn": " null ",
            "CountryNameEn": " n/a ",
            "Column1": " #N/A ",
        }
    )
    normalized = cleaning.normalize_row(raw)
    assert normalized[4:7] == ("123", "100000000000000000000", "400")
    assert normalized[8:12] == ("0012", "0003", "Apartment", "1.25")
    assert normalized[14] == "12345"
    assert normalized[3] is None
    assert normalized[13] == "null" and normalized[15:] == ("n/a", "#N/A")
    assert normalized[0:2] == raw[0:2] and normalized[7] == raw[7]


def test_blank_rows_keep_positions_and_structured_excel_errors_are_blanked_and_audited(tmp_path):
    path = source(
        tmp_path, [owner_row(Project="#N/A"), [None] * 17, [" "] * 17, owner_row(Project="null")]
    )
    headers, records, blanks = cleaning.load_source(path)
    assert headers == cleaning.HEADERS and blanks == [3, 4]
    assert [number for number, _, _ in records] == [2, 5]
    assert isinstance(records[0][1][3], cleaning.ExcelError)
    assert records[0][2][3] is None and records[1][2][3] is None
    out = tmp_path / "out"
    metrics = cleaning.clean_workbook(path, out)
    assert metrics["empty_source_rows"] == 2 and metrics["body_row_positions"] == 4
    assert metrics["excel_error_cells_audited"] == 1
    assert metrics["excel_error_cells_blanked_structured"] == 1
    assert metrics["excel_error_cells_preserved_as_text"] == 0
    assert metrics["retained_rows"] == 1
    assert metrics["additional_normalization_duplicate_rows"] == 1
    workbook = load_workbook(out / "cleaned-owner-records.xlsx", data_only=False)
    assert workbook.active["D2"].value is None
    workbook.close()
    assert read_csv(out / "cell-error-audit.csv") == [
        {
            "source_sheet": "Sheet1",
            "source_row_number": "2",
            "source_cell_coordinate": "D2",
            "column_name": "Project",
            "original_error_code": "#N/A",
            "cleaned_action": "blanked_structured",
        }
    ]


def test_cleaned_write_only_workbook_roundtrip_and_normalization_are_idempotent(tmp_path):
    path = source(
        tmp_path,
        [
            owner_row(Project="#N/A"),
            owner_row(Project="null"),
            owner_row(NameEn="#VALUE!", Mobile="#REF!", CountryNameEn="#NAME?", Column1="#N/A"),
        ],
    )
    _, records, _ = cleaning.load_source(path)
    expected = list(dict.fromkeys(row for _, _, row in records))
    for _, _, row in records:
        assert cleaning.normalize_row(row) == row
    out = tmp_path / "out"
    metrics = cleaning.clean_workbook(path, out)
    assert metrics["excel_error_cells_audited"] == 5
    assert metrics["excel_error_cells_blanked_structured"] == 1
    assert metrics["excel_error_cells_preserved_as_text"] == 4
    cleaned_path = out / "cleaned-owner-records.xlsx"
    workbook = load_workbook(cleaned_path, read_only=True)
    assert workbook.active.max_column is None  # Write-only output has no declared dimensions.
    workbook.close()
    headers, reread, blanks = cleaning.load_source(cleaned_path)
    assert headers == cleaning.HEADERS and blanks == []
    assert [raw for _, raw, _ in reread] == [normalized for _, _, normalized in reread] == expected
    assert expected[1][13:] == ("#VALUE!", "#REF!", "#NAME?", "#N/A")
    second = tmp_path / "second"
    second_metrics = cleaning.clean_workbook(cleaned_path, second)
    assert second_metrics["total_duplicate_rows"] == 0
    assert second_metrics["excel_error_cells_audited"] == 0
    assert [
        row for _, _, row in cleaning.load_source(second / "cleaned-owner-records.xlsx")[1]
    ] == expected


def test_dimensionless_workbook_rejects_extra_body_values(tmp_path):
    path = tmp_path / "dimensionless.xlsx"
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Sheet1")
    sheet.append(cleaning.HEADERS)
    sheet.append((*owner_row(), "extra"))
    workbook.save(path)
    with pytest.raises(ValueError, match="Extra column value found at source row 2"):
        cleaning.load_source(path)


def test_formula_rejected_before_any_output_is_written(tmp_path):
    path = source(tmp_path, [owner_row(Mobile="=1+2")])
    with pytest.raises(ValueError, match="Formula cell found at source row 2"):
        cleaning.clean_workbook(path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_literal_formula_looking_text_stays_text_and_csv_is_protected(tmp_path):
    path = source(tmp_path, [owner_row(Project="ordinary")])
    workbook = load_workbook(path)
    workbook.active["D2"] = "=1+2"
    workbook.active["D2"].data_type = "s"
    workbook.save(path)
    workbook.close()
    out = tmp_path / "out"
    cleaning.clean_workbook(path, out)
    workbook = load_workbook(out / "cleaned-owner-records.xlsx", data_only=False)
    assert workbook.active["D2"].value == "=1+2" and workbook.active["D2"].data_type == "s"
    workbook.close()
    assert read_csv(out / "candidate-events.csv")[0]["Project"] == "'=1+2"


@pytest.mark.parametrize("problem", ["headers", "extra_column", "extra_sheet"])
def test_unsupported_shape_fails_loud(tmp_path, problem):
    path = source(tmp_path, [owner_row()])
    workbook = load_workbook(path)
    if problem == "headers":
        workbook.active["A1"] = "Unknown"
    elif problem == "extra_column":
        workbook.active["R2"] = "extra"
    else:
        workbook.create_sheet("Unexpected")
    workbook.save(path)
    workbook.close()
    with pytest.raises(ValueError):
        cleaning.clean_workbook(path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_refuses_source_overwrite(tmp_path):
    path = source(tmp_path, [owner_row()])
    target = tmp_path / "cleaned-owner-records.xlsx"
    path.rename(target)
    with pytest.raises(ValueError, match="must not replace"):
        cleaning.clean_workbook(target, tmp_path)


def test_transaction_policy_dedupes_before_dropping_without_requiring_phone(tmp_path):
    valid = owner_row(
        Mobile=None,
        ProcedureValue="70,000",
        Size="100.50",
        **{"Master Project": " JVC ", "Project": "Phase  1", "BuildingNameEn": "Tower  2"},
    )
    equivalent = owner_row(
        Mobile=None,
        ProcedureValue=70000.0,
        Size=100.5,
        **{
            "Master Project": "jumeirah village circle",
            "Project": "phase 1",
            "BuildingNameEn": "tower 2",
        },
    )
    zero = owner_row(ProcedureValue=0)
    incomplete = tuple(None for _ in cleaning.HEADERS[:13]) + (
        "Private Person",
        "0501234567",
        None,
        None,
    )
    rows = [
        valid,
        equivalent,
        zero,
        zero,
        owner_row(ProcedureValue="-70,000"),
        owner_row(NameEn="unknown"),
        incomplete,
    ]
    path = source(tmp_path, rows)
    out = tmp_path / "out"
    metrics = cleaning.clean_workbook(path, out, policy="transaction")
    assert metrics["nonempty_source_rows"] == 7
    assert metrics["retained_rows"] == 1 and metrics["total_duplicate_rows"] == 2
    assert metrics["dropped_rows"] == 4 and metrics["unique_rows_before_policy"] == 5
    assert metrics["dropped_rows_by_reason"] == {
        "invalid_or_nonpositive_price": 3,
        "missing_meaningful_name": 1,
        "missing_property_identity_or_location": 1,
    }
    assert metrics["stage_order"] == [
        "normalize",
        "deduplicate_all_17_columns",
        "apply_policy",
        "write_retained",
    ]
    assert metrics["price_sums_aed"]["retained"] == "70000"
    provenance = read_csv(out / "source-row-provenance.csv")
    assert [item["status"] for item in provenance] == [
        "retained",
        "duplicate",
        "dropped",
        "duplicate",
        "dropped",
        "dropped",
        "dropped",
    ]
    assert [item["cleaned_row_number"] for item in provenance] == ["2", "2", "", "", "", "", ""]
    drops = read_csv(out / "dropped-row-audit.csv")
    assert [item["source_row_number"] for item in drops] == ["4", "6", "7", "8"]
    assert drops[1]["ProcedureValue"] == "'-70,000"
    audit = read_csv(out / "normalization-audit.csv")
    assert any(
        item["before_value"] == " JVC " and item["after_value"] == "jumeirah village circle"
        for item in audit
    )
    cleaned_path = out / "cleaned-owner-records.xlsx"
    _, records, _ = cleaning.load_source(cleaned_path)
    assert len(records) == 1 and records[0][2][14] is None
    second = cleaning.clean_workbook(cleaned_path, tmp_path / "second", policy="transaction")
    assert (
        second["retained_rows"] == 1
        and second["total_duplicate_rows"] == second["dropped_rows"] == 0
    )


def test_exact_decimal_and_subunit_identity_are_preserved_across_repeated_cleaning(tmp_path):
    price = "123456789012345678901234567890.1234567890123456789"
    path = source(
        tmp_path,
        [
            owner_row(ProcedureValue=price, UnitNumber="0012 (Q 3)"),
            owner_row(ProcedureValue=price, UnitNumber="0012"),
        ],
    )
    out = tmp_path / "out"
    metrics = cleaning.clean_workbook(path, out, policy="transaction")
    assert metrics["retained_rows"] == 2 and metrics["total_duplicate_rows"] == 0
    cleaned_path = out / "cleaned-owner-records.xlsx"
    _, records, _ = cleaning.load_source(cleaned_path)
    assert {row[8] for _, _, row in records} == {"0012 (Q 3)", "0012"}
    assert all(row[1] == Decimal(price) for _, _, row in records)
    second = cleaning.clean_workbook(cleaned_path, tmp_path / "second", policy="transaction")
    assert second["price_sums_aed"] == metrics["price_sums_aed"]


def test_location_normalization_keeps_projects_towers_phases_and_nonlocation_text_distinct(
    tmp_path,
):
    rows = [
        owner_row(Project="JVC", BuildingNameEn="Tower 1", NameEn="JVC", CountryNameEn="JVC"),
        owner_row(Project="Jumeirah Village Circle", BuildingNameEn="Tower 1"),
        owner_row(Project="Phase 1", BuildingNameEn="Tower 1"),
        owner_row(Project="Phase 2", BuildingNameEn="Tower 1"),
        owner_row(Project="Phase 1", BuildingNameEn="Tower 2"),
    ]
    out = tmp_path / "out"
    metrics = cleaning.clean_workbook(source(tmp_path, rows), out, policy="transaction")
    assert metrics["retained_rows"] == 5
    _, records, _ = cleaning.load_source(out / "cleaned-owner-records.xlsx")
    assert records[0][2][13] == records[0][2][15] == "JVC"
    assert records[0][2][3] == "jvc"


@pytest.mark.parametrize("price", ["NaN", "Infinity", "70-000", "70 00", "AED70AED"])
def test_transaction_policy_audits_unreadable_prices_without_manufacturing_value(tmp_path, price):
    out = tmp_path / "out"
    metrics = cleaning.clean_workbook(
        source(tmp_path, [owner_row(ProcedureValue=price)]), out, policy="transaction"
    )
    assert metrics["retained_rows"] == 0 and metrics["dropped_rows"] == 1
    assert metrics["source_price_quality"] == {"invalid_or_missing": 1}
    assert read_csv(out / "dropped-row-audit.csv")[0]["ProcedureValue"] == price


def test_transaction_policy_rejects_meaningless_names_and_isolated_contact_rows(tmp_path):
    without_property = list(owner_row())
    for index in (2, 3, 4, 5, 6, 8, 9, 11):
        without_property[index] = None
    rows = [owner_row(NameEn=value) for value in (None, " ", "unknown", "#VALUE!", "123456")]
    out = tmp_path / "out"
    metrics = cleaning.clean_workbook(
        source(tmp_path, [*rows, tuple(without_property)]), out, policy="transaction"
    )
    assert metrics["retained_rows"] == 0 and metrics["dropped_rows"] == 6
    assert metrics["dropped_rows_by_reason"] == {
        "missing_meaningful_name": 5,
        "missing_property_identity_or_location": 1,
    }
