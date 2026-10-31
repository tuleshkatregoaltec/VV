#!/usr/bin/env python3
"""Offline auditable cleanup, with an explicit dated-transaction rejection policy."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, localcontext
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.utils import get_column_letter

from app.crm.import_normalization import (
    NORMALIZATION_VERSION,
    normalize_location,
    parse_decimal,
    positive_decimal,
)

HEADERS = (
    "Regis",
    "ProcedureValue",
    "Master Project",
    "Project",
    "Plot Pre Reg No",
    "Building No",
    "BuildingNameEn",
    "Size",
    "UnitNumber",
    "DmSubNo",
    "PropertyTypeEn",
    "LandNumber",
    "ProcedurePartyTypeNameEn",
    "NameEn",
    "Mobile",
    "CountryNameEn",
    "Column1",
)
IDENTIFIER_COLUMNS = {4, 5, 6, 8, 9, 11, 14}
LOCATION_COLUMNS = {2, 3, 6}
NUMERIC_COLUMNS = {1, 7}
NULL_TOKENS = {"", "null", "#n/a", "n/a"}
MISSING_TOKENS = NULL_TOKENS | {"-", "na", "none", "nan", "unknown"}
HEADER_MAPPING = dict(
    zip(
        HEADERS,
        (
            "transaction_date",
            "transaction_price_aed",
            "master_project",
            "project_name",
            "plot_number",
            "building_number",
            "building_name",
            "size_unknown",
            "unit_number",
            "municipality_sub_number",
            "property_type",
            "land_number",
            "party_role",
            "contact_name",
            "phone_primary",
            "country",
            "notes",
        ),
        strict=True,
    )
)
OUTPUT_NAMES = (
    "cleaned-owner-records.xlsx",
    "source-row-provenance.csv",
    "candidate-events.csv",
    "metrics.json",
    "cell-error-audit.csv",
    "normalization-audit.csv",
    "dropped-row-audit.csv",
)


class ExcelError(str):
    """Keep actual Excel errors distinguishable from ordinary textual null tokens."""


def normalize_row(row: tuple) -> tuple:
    """Normalize conservatively without merging parties, contacts, notes or history."""
    if len(row) != len(HEADERS):
        raise ValueError("Expected exactly 17 owner columns")
    result = []
    for index, value in enumerate(row):
        if isinstance(value, ExcelError):
            value = None if index < 13 else str(value)
        elif isinstance(value, str):
            value = value.strip()
            if index < 13 and value.casefold() in NULL_TOKENS:
                value = None
        elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            if not math.isfinite(value) and index not in NUMERIC_COLUMNS:
                raise ValueError("Non-finite numeric cell is unsupported")
            if not math.isfinite(value):
                value = str(value)
            if index in IDENTIFIER_COLUMNS:
                value = format(Decimal(str(value)), "f")
                if "." in value:
                    value = value.rstrip("0").rstrip(".")
        elif value is not None and not isinstance(value, (date, bool)):
            raise ValueError("Unsupported cell value type")
        if value is not None and index in NUMERIC_COLUMNS:
            parsed = parse_decimal(value)
            if parsed is not None:
                value = parsed
        elif value is not None and index in LOCATION_COLUMNS:
            value = normalize_location(value, area=index == 2)
        result.append(value)
    return tuple(result)


def load_source(path: str | Path) -> tuple[tuple, list[tuple[int, tuple, tuple]], list[int]]:
    """Read original row numbers and values; reject unsupported shapes and formulas."""
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        if workbook.sheetnames != ["Sheet1"]:
            raise ValueError("Expected exactly one worksheet named Sheet1")
        sheet = workbook["Sheet1"]
        cells = sheet.iter_rows()
        header_cells = next(cells, ())
        headers = tuple(cell.value for cell in header_cells[: len(HEADERS)])
        if headers != HEADERS or any(
            cell.value is not None for cell in header_cells[len(HEADERS) :]
        ):
            raise ValueError("Unexpected owner workbook headers")
        records, blanks = [], []
        for number, row in enumerate(cells, start=2):
            if any(cell.data_type == "f" for cell in row):
                raise ValueError(f"Formula cell found at source row {number}; no files written")
            if any(cell.value is not None for cell in row[len(HEADERS) :]):
                raise ValueError(
                    f"Extra column value found at source row {number}; no files written"
                )
            raw = tuple(
                ExcelError(cell.value) if cell.data_type == "e" else cell.value
                for cell in row[: len(HEADERS)]
            )
            raw += (None,) * (len(HEADERS) - len(raw))
            if all(value is None or isinstance(value, str) and not value.strip() for value in raw):
                blanks.append(number)
                continue
            records.append((number, raw, normalize_row(raw)))
        return headers, records, blanks
    finally:
        workbook.close()


def _fingerprint(values: tuple, *, raw: bool = False) -> str:
    parts = []
    for value in values:
        kind = type(value).__name__
        if isinstance(value, (datetime, date)):
            text = value.isoformat()
        elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            text = format(Decimal(str(value)), "f")
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            if not raw:
                kind = "number"
        else:
            text = value
        parts.append((kind, text))
    return json.dumps(parts, ensure_ascii=True, separators=(",", ":"))


def _event_id(row: tuple) -> str:
    return "candidate-" + hashlib.sha256(_fingerprint(row[:12]).encode()).hexdigest()


def _csv_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _write_literal_row(sheet, values):
    cells = []
    for value in values:
        # Excel numeric cells cannot round-trip more than 15 significant digits.
        # Keep exact high-precision amounts as decimal text, re-readable by our parser.
        if isinstance(value, Decimal) and len(value.as_tuple().digits) > 15:
            value = format(value, "f")
        cell = WriteOnlyCell(sheet, value=value)
        if isinstance(value, str):
            cell.data_type = "s"  # Neither formula-looking text nor Excel errors execute.
        cells.append(cell)
    sheet.append(cells)


def _meaningful(value) -> bool:
    return (
        value is not None
        and not isinstance(value, ExcelError)
        and str(value).strip().casefold() not in MISSING_TOKENS
        and not str(value).strip().startswith("#")
    )


def _exact_add(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = (
            max(left.adjusted(), right.adjusted(), 0)
            - min(left.as_tuple().exponent, right.as_tuple().exponent, 0)
            + 2
        )
        return left + right


def _drop_reasons(row: tuple, policy: str) -> list[str]:
    if policy == "preserve":
        return []
    reasons = []
    if positive_decimal(row[1]) is None:
        reasons.append("invalid_or_nonpositive_price")
    if not _meaningful(row[13]) or not any(char.isalpha() for char in str(row[13])):
        reasons.append("missing_meaningful_name")
    if not any(
        _meaningful(row[index]) and str(row[index]) != "0" for index in (2, 3, 4, 5, 6, 8, 9, 11)
    ):
        reasons.append("missing_property_identity_or_location")
    return reasons


def clean_workbook(
    input_path: str | Path, output_dir: str | Path, *, policy: str = "preserve"
) -> dict:
    """Write a reimportable workbook, row provenance and non-PII candidate event audit."""
    input_path, output_dir = Path(input_path), Path(output_dir)
    if policy not in {"preserve", "transaction"}:
        raise ValueError("Unknown cleaning policy")
    outputs = [output_dir / name for name in OUTPUT_NAMES]
    if any(path.resolve() == input_path.resolve() for path in outputs):
        raise ValueError("Output must not replace the source workbook")
    if any(path.exists() for path in outputs):
        raise ValueError("Output artifacts already exist; choose an unused output directory")
    source_sha = hashlib.sha256(input_path.read_bytes()).hexdigest()
    headers, records, blanks = load_source(input_path)
    retained, unique, raw_seen, audit, events, error_audit = {}, {}, set(), [], {}, []
    normalization_audit, drop_audit, drop_counts = [], [], Counter()
    price_sums = {
        stage: Decimal(0) for stage in ("source", "duplicates", "unique", "dropped", "retained")
    }
    price_quality = Counter()
    types, errors, normalized_cells, raw_duplicates = Counter(), Counter(), Counter(), 0
    histories = defaultdict(set)
    for number, raw, normalized in records:
        raw_key = _fingerprint(raw, raw=True)
        raw_duplicates += raw_key in raw_seen
        raw_seen.add(raw_key)
        for index, (before, after) in enumerate(zip(raw, normalized, strict=True)):
            types[type(before).__name__] += 1
            if isinstance(before, ExcelError):
                errors[headers[index]] += 1
                error_audit.append(
                    (
                        "Sheet1",
                        number,
                        f"{get_column_letter(index + 1)}{number}",
                        headers[index],
                        str(before),
                        "blanked_structured" if index < 13 else "preserved_text",
                    )
                )
            if type(before) is not type(after) or before != after:
                normalized_cells[headers[index]] += 1
                normalization_audit.append(
                    (
                        "Sheet1",
                        number,
                        f"{get_column_letter(index + 1)}{number}",
                        headers[index],
                        type(before).__name__,
                        _csv_value(before),
                        type(after).__name__,
                        _csv_value(after),
                    )
                )
        event_id = _event_id(normalized)
        duplicate = normalized in unique
        first = unique.setdefault(normalized, number)
        parsed_price = parse_decimal(normalized[1])
        price_quality[
            "invalid_or_missing"
            if parsed_price is None
            else "positive"
            if parsed_price > 0
            else "nonpositive"
        ] += 1
        amount = parsed_price or Decimal(0)
        price_sums["source"] = _exact_add(price_sums["source"], amount)
        stage = "duplicates" if duplicate else "unique"
        price_sums[stage] = _exact_add(price_sums[stage], amount)
        reasons = _drop_reasons(normalized, policy)
        status = "duplicate" if duplicate else "dropped" if reasons else "retained"
        audit.append(
            (number, first if not reasons else "", event_id, status, first, ";".join(reasons))
        )
        if not duplicate:
            stage = "dropped" if reasons else "retained"
            price_sums[stage] = _exact_add(price_sums[stage], amount)
            if reasons:
                drop_counts.update(reasons)
                drop_audit.append(("Sheet1", number, ";".join(reasons), *map(_csv_value, raw)))
            else:
                retained[normalized] = number
        if reasons:
            continue
        event = events.setdefault(
            event_id,
            {
                "attributes": normalized[:12],
                "roles": Counter(),
                "rows": [],
                "original_rows": 0,
            },
        )
        event["original_rows"] += 1
        if not duplicate:
            role = normalized[12]
            event["roles"][role if role in {"Buyer", "Seller"} else "other"] += 1
            event["rows"].append(number)
        # Property attributes excluding date, price and size; historical events stay separate.
        histories[normalized[2:7] + normalized[8:12]].add(event_id)
    metrics = {
        "source_sha256": source_sha,
        "sheet": "Sheet1",
        "body_row_positions": len(records) + len(blanks),
        "nonempty_source_rows": len(records),
        "empty_source_rows": len(blanks),
        "empty_source_row_numbers": blanks,
        "retained_rows": len(retained),
        "exact_raw_duplicate_rows": raw_duplicates,
        "additional_normalization_duplicate_rows": len(raw_seen) - len(unique),
        "total_duplicate_rows": len(records) - len(unique),
        "unique_rows_before_policy": len(unique),
        "dropped_rows": len(drop_audit),
        "dropped_rows_by_reason": dict(drop_counts),
        "normalization_audit_cells": len(normalization_audit),
        "normalization_version": NORMALIZATION_VERSION,
        "header_mapping": HEADER_MAPPING,
        "policy": policy,
        "stage_order": [
            "normalize",
            "deduplicate_all_17_columns",
            "apply_policy",
            "write_retained",
        ],
        "price_sums_aed": {stage: format(value, "f") for stage, value in price_sums.items()},
        "source_price_quality": dict(price_quality),
        "source_cell_types": dict(sorted(types.items())),
        "excel_error_cells_audited": len(error_audit),
        "excel_error_cells_blanked_structured": sum(errors[header] for header in HEADERS[:13]),
        "excel_error_cells_preserved_as_text": sum(errors[header] for header in HEADERS[13:]),
        "excel_error_cells_by_column": dict(errors),
        "normalized_cells_by_column": dict(normalized_cells),
        "candidate_event_count": len(events),
        "candidate_events_with_buyer_and_seller": sum(
            bool(event["roles"]["Buyer"] and event["roles"]["Seller"]) for event in events.values()
        ),
        "candidate_events_single_buyer_or_seller_side": sum(
            bool(event["roles"]["Buyer"]) != bool(event["roles"]["Seller"])
            for event in events.values()
        ),
        "candidate_events_with_neither_buyer_nor_seller": sum(
            not event["roles"]["Buyer"] and not event["roles"]["Seller"]
            for event in events.values()
        ),
        "property_signatures_with_multiple_candidate_events": sum(
            len(event_ids) > 1 for event_ids in histories.values()
        ),
        "candidate_events_per_property_signature": dict(
            sorted(Counter(len(event_ids) for event_ids in histories.values()).items())
        ),
        "rules": {
            "deduplication": "All 17 normalized columns must match; retain first source row",
            "candidate_event": "First 12 normalized columns; candidate only, no transaction ID",
            "role_counts": "Retained rows, not distinct people or legal ownership assertions",
            "csv_safety": "Formula-looking text gets a leading apostrophe in CSV only",
            "excel_errors": (
                "Structured columns 0:13 blanked; text owner/contact/note columns preserved as "
                "literal text; original error codes and coordinates retained in cell-error-audit.csv"
            ),
            "history_signature": "Property columns 2:7 and 8:12, excluding date, price, size",
            "size": "Exact decimal normalization; no area-unit inference or conversion",
            "location": "Shared market lower/single-space labels; explicit master-project area aliases only",
            "numeric": "Strict finite decimal parsing; identifiers and contacts are never amounts",
            "policy": "Transaction: drop nonpositive/invalid price, missing meaningful name or property; phone optional",
        },
    }
    assert len(records) == len(retained) + metrics["total_duplicate_rows"] + len(drop_audit)
    assert metrics["total_duplicate_rows"] == (
        raw_duplicates + metrics["additional_normalization_duplicate_rows"]
    )
    assert price_sums["source"] == _exact_add(price_sums["duplicates"], price_sums["unique"])
    assert price_sums["unique"] == _exact_add(price_sums["retained"], price_sums["dropped"])
    output_dir.mkdir(parents=True, exist_ok=True)
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Sheet1")
    _write_literal_row(sheet, headers)
    for row in retained:
        _write_literal_row(sheet, row)
    workbook.save(outputs[0])
    with outputs[1].open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "source_row_number",
                "retained_source_row_number",
                "candidate_event_id",
                "status",
                "first_normalized_source_row_number",
                "drop_reasons",
                "cleaned_row_number",
            )
        )
        cleaned_rows = {
            number: cleaned for cleaned, number in enumerate(retained.values(), start=2)
        }
        writer.writerows((*row, cleaned_rows.get(row[4], "")) for row in audit)
    with outputs[2].open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "candidate_event_id",
                *headers[:12],
                "buyer_rows",
                "seller_rows",
                "other_rows",
                "retained_source_row_numbers",
                "original_row_count",
            )
        )
        for event_id, event in events.items():
            writer.writerow(
                (
                    event_id,
                    *map(_csv_value, event["attributes"]),
                    event["roles"]["Buyer"],
                    event["roles"]["Seller"],
                    event["roles"]["other"],
                    ";".join(map(str, event["rows"])),
                    event["original_rows"],
                )
            )
    outputs[3].write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with outputs[4].open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "source_sheet",
                "source_row_number",
                "source_cell_coordinate",
                "column_name",
                "original_error_code",
                "cleaned_action",
            )
        )
        writer.writerows(error_audit)
    with outputs[5].open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "source_sheet",
                "source_row_number",
                "source_cell_coordinate",
                "column_name",
                "before_type",
                "before_value",
                "after_type",
                "after_value",
            )
        )
        writer.writerows(normalization_audit)
    with outputs[6].open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("source_sheet", "source_row_number", "drop_reasons", *HEADERS))
        writer.writerows(drop_audit)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--policy", choices=("preserve", "transaction"), default="preserve")
    args = parser.parse_args()
    metrics = clean_workbook(args.input_path, args.output_dir, policy=args.policy)
    print(
        json.dumps(
            {key: value for key, value in metrics.items() if key != "empty_source_row_numbers"},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
