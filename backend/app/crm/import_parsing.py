from __future__ import annotations

import csv
import hashlib
import io
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl

from app.crm.identity import (
    _NON_KEY,
    ParsedContact,
    _normalize_email,
    _normalize_phone,
    _normalize_unit,
    _recover_embedded_property_identity,
    _text,
    _usable_project_name,
)
from app.crm.import_events import IMPORT_RESOLVER_VERSION, event_family, source_size_unit
from app.crm.import_inventory import SourcePropertyInventory
from app.crm.import_models import (
    CrmContactImportSummary,
    CrmSheetMapping,
)
from app.crm.import_normalization import location_evidence, positive_decimal

_MAX_ROWS = 500_000

_PLACEHOLDER_HEADER = re.compile(r"^column\s*\d+$", re.IGNORECASE)
_BUILDING_NO_PROPERTY_IDENTIFIER = re.compile(
    r"(?:^|[-\s])(?:villa|v|th)[-\s]*(?=[a-z0-9.]*\d)[a-z0-9.]+$", re.IGNORECASE
)
_BUILDING_NO_NUMERIC_IDENTIFIER = re.compile(
    r"^(?:r\d*\s+)?(.+?)[-\s]+(?:v|villa|th)[-\s]*(\d+)$", re.IGNORECASE
)

_CANONICAL_FIELDS = {
    "area_name",
    "master_project",
    "project_name",
    "building_name",
    "unit_number",
    "property_type",
    "completion_status",
    "size_sqft",
    "size_sqm",
    "size_unknown",
    "transaction_date",
    "transaction_price_aed",
    "party_role",
    "procedure_type",
    "contact_name",
    "phone_primary",
    "phone_alternate",
    "email_primary",
    "building_number",
    "land_number",
    "land_sub_number",
    "property_number",
    "plot_number",
    "municipality_number",
    "municipality_sub_number",
}

_ALIASES = {
    "area_name": {"areanameen", "area", "community", "masterlocation"},
    "master_project": {"masterproject", "masterdevelopment"},
    "project_name": {"project", "projectname", "development"},
    "building_name": {"buildingnameen", "building", "tower", "buildingname", "buildingname2"},
    "unit_number": {
        "unitnumber",
        "unit",
        "flatnumber",
        "flatno",
        "villanumber",
        "unitnumberproxy",
        "plotpreregisterationno",
        "plotpreregistrationno",
        "plotregistrationno",
    },
    "property_type": {"propertytypeen", "propertytype", "type"},
    "completion_status": {
        "completionstatus",
        "marketstatus",
        "registrationtype",
        "regtypeen",
        "propertycompletionstatus",
    },
    "size_sqft": {"areasqft", "sizesqft", "propertysizesqft"},
    "size_sqm": {"sizesqm", "areasqm", "propertysizesqm", "areasquaremeters"},
    "size_unknown": {"size", "propertysize"},
    "transaction_date": {"regis", "date", "registrationdate", "transactiondate"},
    "transaction_price_aed": {
        "procedurevalue",
        "price",
        "transactionvalue",
        "saleprice",
        "transactionamount",
    },
    "party_role": {"procedurepartytypenameen", "partytype", "partyrole"},
    "procedure_type": {"procedurenameen", "procedurename"},
    "contact_name": {"nameen", "name", "ownername", "contactname"},
    "phone_primary": {"phone", "mobile", "phonenumber", "mobilenumber", "mobile1", "phone1"},
    "phone_alternate": {"secondarymobile", "alternatemobile", "mobile2"},
    "email_primary": {"email", "emailaddress", "owneremail"},
    "building_number": {"buildingno", "buildingnumber", "building1"},
    "land_number": {"landnumber", "landno"},
    "land_sub_number": {"landsubnumber", "landsubno"},
    "property_number": {"propertynumber"},
    "plot_number": {"plotpreregno", "plotpreregistrationno", "plotnumber"},
    # JVT exports spell it "Muncipality": Area = municipality no, Land = sub no (see their
    # sibling "Municipality No" / "Municipality Sub No" sheets).
    "municipality_number": {
        "dmno",
        "municipalityno",
        "areamuncipalitynumber",
        "areamunicipalitynumber",
    },
    "municipality_sub_number": {
        "dmsubno",
        "municipalitysubno",
        "landmuncipalitynumber",
        "landmunicipalitynumber",
    },
}

# Land-registry variants ("Project Lnd"). They are the field when the explicit column is absent,
# otherwise an ordered fallback that fills the explicit column's blank cells.
_FALLBACK_ALIASES = {
    "master_project": {"masterprojectlnd", "masterprojectland"},
    "project_name": {"projectlnd", "projectland"},
}
_LOCATION_FIELDS = ("area_name", "master_project", "project_name", "building_name")

_CHANNEL_TOKENS = {
    "mobile",
    "mobile1",
    "mobile2",
    "phone",
    "phone1",
    "phone2",
    "secondarymobile",
    "alternatemobile",
    "phonenumber",
    "mobilenumber",
}
# Unmapped headers holding owner identity or contact data are intentionally never imported, so
# they are not reported as dropped; anything naming a property location is always reported.
_IDENTITY_HEADER = re.compile(
    r"name|phone|mobile|mail|nation|passport|birth|dob|emirates|contact|gender|visa|owner"
    r"|idnumber|unified|identity|card|whatsapp"
)
_LOCATION_HEADER = re.compile(r"build|project|area|unit|villa|tower|community")
_SPREADSHEET_ERROR = re.compile(r"#(?:REF!|N/A|VALUE!|DIV/0!|NAME\?|NULL!|NUM!)", re.IGNORECASE)
_BLANK_TEXT = {"", "0", "null", "none", "n/a", "-"}
_AUTOFILL_LABEL = re.compile(r"(?P<base>.*\S)\s+(?P<number>\d+)")
# Rows read at inspection to find which unmapped columns hold data and to sample them.
_SCAN_ROWS = 2000


@dataclass
class HeaderCell:
    key: str
    label: str
    index: int


@dataclass
class SheetProfile:
    name: str
    header_row: int
    headers: list[HeaderCell]
    meaningful_rows: int
    field_map: dict[str, str]
    sheet_family: str
    mapping_source: str = "heuristic"
    confidence: float = 0.82
    warnings: list[str] = field(default_factory=list)
    date_order: str = "dmy"
    last_data_row: int | None = None
    property_inventory: SourcePropertyInventory = field(default_factory=SourcePropertyInventory)
    # Ordered extra headers per canonical field: used when the mapped cell is blank.
    fallback_map: dict[str, list[str]] = field(default_factory=dict)
    # Non-personal headers that hold data but have no role (header keys, in sheet order).
    unmapped_headers: list[str] = field(default_factory=list)
    # First rows below the header, kept for data detection and non-personal column samples.
    sample_rows: list[tuple[Any, ...]] = field(default_factory=list, repr=False)
    # Header index -> {row number: label} for Excel autofill runs found while parsing.
    autofill_repairs: dict[int, dict[int, str]] = field(default_factory=dict, repr=False)


def is_blank(value: Any) -> bool:
    """True for empty cells and the placeholders exports use for "no value"."""
    if value is None:
        return True
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value == 0
    text = str(value).strip().lower()
    return text in _BLANK_TEXT or bool(_SPREADSHEET_ERROR.fullmatch(text))


def repair_autofill_runs(values: list[tuple[int, Any]], *, min_run: int = 50) -> dict[int, str]:
    """Undo Excel autofill in one location column.

    Dragging the seed ``DAMAC HILLS 2`` down a column writes ``DAMAC HILLS 3``, ``DAMAC HILLS 4``
    ... one per row, so the number minus the row number stays constant. A run of at least
    ``min_run`` such rows after the seed is an artefact: each of its rows maps to the seed label
    (the row just before the run, which itself follows the same pattern). Shorter runs, and
    numbering that does not track the row number, are real data and are left alone.
    """
    repaired: dict[int, str] = {}
    run: list[tuple[int, str]] = []
    base = ""
    offset = 0

    def close() -> None:
        if len(run) - 1 >= min_run:
            repaired.update({row: run[0][1] for row, _ in run[1:]})

    for row, cell in sorted(values, key=lambda item: item[0]):
        label = _text(cell)
        match = _AUTOFILL_LABEL.fullmatch(label)
        if (
            match
            and run
            and row == run[-1][0] + 1
            and match["base"].casefold() == base
            and int(match["number"]) - row == offset
        ):
            run.append((row, label))
            continue
        close()
        run = [(row, label)] if match else []
        if match:
            base = match["base"].casefold()
            offset = int(match["number"]) - row
    close()
    return repaired


def _header_token(value: str) -> str:
    base = value.rsplit("__", 1)[0]
    return _NON_KEY.sub("", base.lower())


def _unique_headers(values: tuple[Any, ...] | list[Any]) -> list[HeaderCell]:
    counts: dict[str, int] = {}
    headers: list[HeaderCell] = []
    for index, raw in enumerate(values):
        label = _text(raw)
        if not label or _PLACEHOLDER_HEADER.match(label):
            continue
        count = counts.get(label.lower(), 0) + 1
        counts[label.lower()] = count
        key = label if count == 1 else f"{label}__{count}"
        headers.append(HeaderCell(key=key, label=label, index=index))
    return headers


def _recognized_headers(values: tuple[Any, ...] | list[Any]) -> int:
    tokens = {_header_token(_text(value)) for value in values if _text(value)}
    aliases = set().union(*_ALIASES.values(), *_FALLBACK_ALIASES.values())
    return len(tokens & aliases)


def _find_header(rows: list[tuple[Any, ...]]) -> tuple[int, list[HeaderCell]]:
    best_index = 0
    best_score = -1
    best_headers: list[HeaderCell] = []
    for index, row in enumerate(rows):
        headers = _unique_headers(row)
        score = _recognized_headers(row) * 100 + len(headers)
        if score > best_score:
            best_index = index
            best_score = score
            best_headers = headers
    return best_index + 1, best_headers


def _header_for(
    headers: list[HeaderCell],
    aliases: set[str],
    *,
    last: bool = False,
) -> str | None:
    matches = [header.key for header in headers if _header_token(header.key) in aliases]
    if not matches:
        return None
    return matches[-1] if last else matches[0]


def _heuristic_mapping(
    headers: list[HeaderCell],
    *,
    filename: str,
    sheet_name: str,
) -> tuple[dict[str, str], str, list[str]]:
    mapping: dict[str, str] = {}
    warnings: list[str] = []
    lowered_filename = filename.lower()
    for field_name, aliases in (*_ALIASES.items(), *_FALLBACK_ALIASES.items()):
        header = _header_for(headers, aliases)
        if header and field_name not in mapping:
            mapping[field_name] = header

    if "elan" in lowered_filename:
        villa = _header_for(headers, {"villanumber"}, last=True)
        if villa:
            mapping["unit_number"] = villa

    header_tokens = {_header_token(header.key): header.key for header in headers}
    if (
        "procedure" in header_tokens
        and "procedurepartytypenameen" not in header_tokens
        and "partytype" not in header_tokens
    ):
        mapping["party_role"] = header_tokens["procedure"]
        mapping.pop("procedure_type", None)

    family = "transaction_party" if mapping.get("party_role") else "contact_list"
    if "size_unknown" in mapping:
        warnings.append("Size has no stated unit; it cannot corroborate a transaction match.")
    if mapping.get("transaction_date") and not mapping.get("party_role"):
        warnings.append("Dated owner records have no party role; ownership requires review.")
    if "contact_name" not in mapping:
        warnings.append("No owner/contact name column was detected.")
    if "unit_number" not in mapping:
        warnings.append("No direct unit-number column was detected.")
    if not {"phone_primary", "phone_alternate", "email_primary"} & mapping.keys():
        warnings.append("No contact channel was detected.")
    if family == "contact_list" and not mapping.get("building_name"):
        inferred = _inferred_project(filename, sheet_name)
        if inferred:
            warnings.append(f"Property name will be inferred as {inferred}.")
    return mapping, family, warnings


def _inferred_project(filename: str, sheet_name: str) -> str:
    source = f"{filename} {sheet_name}".lower()
    for name in ("Aura", "Harmony", "Alaya", "Elysian", "Elan"):
        if name.lower() in source:
            return name
    return ""


def _fallback_map(headers: list[HeaderCell], mapping: dict[str, str]) -> dict[str, list[str]]:
    fallbacks: dict[str, list[str]] = {}
    for field_name, aliases in _FALLBACK_ALIASES.items():
        keys = [
            header.key
            for header in headers
            if _header_token(header.key) in aliases and header.key != mapping.get(field_name)
        ]
        if keys:
            fallbacks[field_name] = keys
    return fallbacks


def _mapped_headers(profile: SheetProfile) -> set[str]:
    return set(profile.field_map.values()).union(*profile.fallback_map.values())


def _unmapped_with_data(profile: SheetProfile) -> list[str]:
    """Headers with no role that hold data. Owner identity and contact columns are never listed."""
    mapped = _mapped_headers(profile)
    unmapped = []
    for header in profile.headers:
        token = _header_token(header.key)
        if (
            header.key in mapped
            or token in _CHANNEL_TOKENS | {"propertynumber"}
            or (_IDENTITY_HEADER.search(token) and not _LOCATION_HEADER.search(token))
        ):
            continue
        if any(
            header.index < len(row) and not is_blank(row[header.index])
            for row in profile.sample_rows
        ):
            unmapped.append(header.key)
    return unmapped


def _set_unmapped_warning(profile: SheetProfile) -> None:
    profile.warnings[:] = [w for w in profile.warnings if not w.startswith("Columns not imported")]
    if profile.unmapped_headers:
        profile.warnings.insert(0, f"Columns not imported: {', '.join(profile.unmapped_headers)}.")


def refresh_unmapped_headers(profile: SheetProfile) -> None:
    """Drop headers that gained a role (model, saved mapping, override) and redo the warning."""
    mapped = _mapped_headers(profile)
    profile.unmapped_headers = [h for h in profile.unmapped_headers if h not in mapped]
    _set_unmapped_warning(profile)


def _finalize_profile(profile: SheetProfile, rows: list[tuple[Any, ...]]) -> SheetProfile:
    profile.fallback_map = _fallback_map(profile.headers, profile.field_map)
    profile.sample_rows = rows
    profile.unmapped_headers = _unmapped_with_data(profile)
    _set_unmapped_warning(profile)
    return profile


def _populated_xlsx_rows(workbook, sheet) -> list[int]:
    """Ignore formatting-only rows without stopping at gaps in real data.

    Scan XML once, then bound openpyxl's expensive cell/date decoding. Clear the
    sheetData parent too, so a million empty row elements do not accumulate.
    """
    rows = []
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    parent = None
    with workbook._archive.open(sheet._worksheet_path) as stream:
        for action, element in ET.iterparse(stream, events=("start", "end")):
            if action == "start" and element.tag == ns + "sheetData":
                parent = element
            if action != "end" or element.tag != ns + "row":
                continue
            if any(node.text for node in element.iter() if node.tag in {ns + "v", ns + "t"}):
                rows.append(int(element.attrib["r"]))
            element.clear()
            if parent is not None:
                parent.clear()
    return rows


def _inspect_xlsx(data: bytes, filename: str) -> list[SheetProfile]:
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    profiles: list[SheetProfile] = []
    try:
        for sheet in workbook.worksheets:
            initial_rows = list(
                sheet.iter_rows(
                    min_row=1,
                    max_row=min(15, max(1, sheet.max_row or 15)),
                    max_col=min(100, max(1, sheet.max_column or 100)),
                    values_only=True,
                )
            )
            header_row, headers = _find_header(initial_rows)
            mapping, family, warnings = _heuristic_mapping(
                headers,
                filename=filename,
                sheet_name=sheet.title,
            )
            populated_rows = _populated_xlsx_rows(workbook, sheet)
            scan_rows = list(
                sheet.iter_rows(
                    min_row=header_row + 1,
                    max_row=header_row + _SCAN_ROWS,
                    max_col=max((header.index for header in headers), default=0) + 1,
                    values_only=True,
                )
            )
            profiles.append(
                _finalize_profile(
                    SheetProfile(
                        name=sheet.title.strip() or "Sheet",
                        header_row=header_row,
                        headers=headers,
                        meaningful_rows=sum(number > header_row for number in populated_rows),
                        field_map=mapping,
                        sheet_family=family,
                        warnings=warnings,
                        last_data_row=max(populated_rows, default=header_row),
                    ),
                    scan_rows,
                )
            )
    finally:
        workbook.close()
    return profiles


def _csv_rows(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


def _inspect_csv(data: bytes, filename: str) -> list[SheetProfile]:
    rows = _csv_rows(data)
    initial = [tuple(row[:100]) for row in rows[:15]]
    header_row, headers = _find_header(initial)
    mapping, family, warnings = _heuristic_mapping(
        headers,
        filename=filename,
        sheet_name=Path(filename).stem,
    )
    return [
        _finalize_profile(
            SheetProfile(
                name=Path(filename).stem,
                header_row=header_row,
                headers=headers,
                meaningful_rows=max(0, len(rows) - header_row),
                field_map=mapping,
                sheet_family=family,
                warnings=warnings,
            ),
            [tuple(row) for row in rows[header_row : header_row + _SCAN_ROWS]],
        )
    ]


_DATE_TIME_SUFFIX = re.compile(
    r"[T\s]+\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:\s*[ap]\.?m\.?)?$", re.IGNORECASE
)
_NUMERIC_DATE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d-%b-%Y",
    "%d %B %Y",
    "%d-%B-%Y",
    "%b %d %Y",
    "%B %d %Y",
)
_EMPTY_DATES = {"", "-", "n/a", "na", "none", "null", "unknown", "nan"}


def _date_text(value: Any) -> str:
    """Date text without a time part, with "Sept" as "Sep" and no commas."""
    text = _DATE_TIME_SUFFIX.sub("", _text(value)).strip()
    text = re.sub(r"\bsept\b", "Sep", text, flags=re.IGNORECASE)
    return " ".join(text.replace(",", " ").split())


def _numeric_date(text: str) -> tuple[int, int, int] | None:
    match = _NUMERIC_DATE.match(text)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def _date_order(values: Iterable[Any]) -> str:
    """Day/month order of a date column: "dmy" (UAE, the default), "mdy" when a text date is
    clearly month first (09/25/2024), or "mixed" when the column has clear dates both ways."""
    day_first = month_first = False
    for value in values:
        if value is None or isinstance(value, date):
            continue
        parts = _numeric_date(_date_text(value))
        if not parts:
            continue
        first, second, _ = parts
        day_first = day_first or (first > 12 >= second)
        month_first = month_first or (second > 12 >= first)
        if day_first and month_first:
            return "mixed"
    return "mdy" if month_first else "dmy"


def _parse_date(value: Any, order: str = "dmy") -> date | None:
    """Read a sale date. NN/NN/YYYY follows its own clue when one number is over 12; otherwise
    the column's order, and a "mixed" column leaves it empty rather than guess."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _date_text(value)
    if not text:
        return None
    parts = _numeric_date(text)
    if parts:
        first, second, year = parts
        if first > 12 or (order == "dmy" and second <= 12):
            day, month = first, second
        elif second > 12 or order == "mdy" or first == second:
            day, month = second, first
        else:
            return None
        try:
            return date(year, month, day)
        except ValueError:
            return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _date_column_index(profile: SheetProfile) -> int | None:
    header_key = profile.field_map.get("transaction_date")
    header = next((item for item in profile.headers if item.key == header_key), None)
    return header.index if header_key and header else None


def _read_dates_by_column_order(profile: SheetProfile, values: Iterable[Any]) -> None:
    """Set the sheet's date order from its whole date column, and warn about dates read month
    first, left empty as unclear, or not readable at all."""
    header_key = profile.field_map.get("transaction_date")
    if not header_key:
        return
    values = list(values)
    profile.date_order = _date_order(values)
    label = next((h.label for h in profile.headers if h.key == header_key), header_key)
    unclear = unreadable = 0
    for value in values:
        if value is None or isinstance(value, date):
            continue
        if _text(value).lower() in _EMPTY_DATES or _parse_date(value, profile.date_order):
            continue
        parts = _numeric_date(_date_text(value))
        if parts and parts[0] <= 12 and parts[1] <= 12:
            unclear += 1
        else:
            unreadable += 1
    if profile.date_order == "mdy":
        profile.warnings.append(f"Dates in {label} were read month first (MM/DD/YYYY).")
    if unclear:
        profile.warnings.append(
            f"Dates in {label} mix day-first and month-first: {unclear:,} unclear "
            f"date{'s' if unclear != 1 else ''} left empty."
        )
    if unreadable:
        profile.warnings.append(
            f"{unreadable:,} date{'s' if unreadable != 1 else ''} in {label} could not be read."
        )


def _parse_amount(value: Any) -> int | None:
    parsed = positive_decimal(value)
    if parsed is None:
        return None
    # Keep the historical whole-AED, ties-to-even contract.
    amount = int(round(parsed))
    return amount if amount > 0 else None


def _normalized_role(value: Any) -> str:
    role = _text(value).lower()
    if "buyer" in role:
        return "Buyer"
    if "seller" in role:
        return "Seller"
    return _text(value).title()


def _field_value(
    row: tuple[Any, ...] | list[Any],
    profile: SheetProfile,
    canonical: str,
) -> Any:
    header_key = profile.field_map.get(canonical)
    if not header_key:
        return None
    header = next((item for item in profile.headers if item.key == header_key), None)
    if not header or header.index >= len(row):
        return None
    return row[header.index]


def _location_value(
    row: tuple[Any, ...] | list[Any],
    profile: SheetProfile,
    canonical: str,
    row_number: int,
) -> tuple[str, str]:
    """The first non-blank cell of the field's header, then its fallbacks, with autofill undone.

    Returns ``(value, original)``; ``original`` is the file's own text when an autofill run was
    restored and empty otherwise.
    """
    keys = [profile.field_map.get(canonical), *profile.fallback_map.get(canonical, [])]
    for key in keys:
        header = next((item for item in profile.headers if item.key == key), None)
        if header is None or header.index >= len(row):
            continue
        original = _text(row[header.index])
        restored = profile.autofill_repairs.get(header.index, {}).get(row_number)
        if restored and not is_blank(original):
            return restored, original
        if not is_blank(original):
            return original, ""
    return "", ""


def _repair_autofill_labels(
    profile: SheetProfile, columns: dict[int, list[tuple[int, Any]]]
) -> None:
    """Find autofill runs in the location columns (header index -> (row, cell) pairs)."""
    profile.autofill_repairs = {}
    for index, values in columns.items():
        repaired = repair_autofill_runs(values)
        if not repaired:
            continue
        profile.autofill_repairs[index] = repaired
        label = next(h.label for h in profile.headers if h.index == index)
        seeds = sorted(set(repaired.values()))
        warning = (
            f"Autofill labels in {label} were restored to {', '.join(seeds)} "
            f"({len(repaired)} rows); the file's own text is kept in the row evidence."
        )
        if warning not in profile.warnings:
            profile.warnings.append(warning)


def _location_header_indexes(profile: SheetProfile) -> list[int]:
    keys = {
        key
        for canonical in _LOCATION_FIELDS
        for key in (profile.field_map.get(canonical), *profile.fallback_map.get(canonical, []))
        if key
    }
    return sorted(header.index for header in profile.headers if header.key in keys)


def _dropped_row(
    row: tuple[Any, ...] | list[Any],
    *,
    profile: SheetProfile,
    row_number: int,
    reason: str,
) -> dict[str, Any]:
    """The file's own values for a row the import does not keep, for the dropped-rows log."""

    def value(canonical: str) -> str:
        cell = _field_value(row, profile, canonical)
        if isinstance(cell, datetime):
            return cell.date().isoformat()
        if isinstance(cell, date):
            return cell.isoformat()
        return _text(cell)[:200]

    return {
        "sheet": profile.name,
        "row": row_number,
        "reason": reason,
        "name": value("contact_name"),
        "building": value("building_name")
        or _location_value(row, profile, "project_name", row_number)[0][:200],
        "unit": value("unit_number"),
        "date": value("transaction_date"),
        "price": value("transaction_price_aed"),
        "role": value("party_role"),
        "procedure": value("procedure_type"),
    }


# What the property-first matcher reads from a row: the sheet's own property fields, never an
# owner or contact. The importer stores this at parse time and the offline shadow run reads it
# through ``matcher_source`` too, so both give the matcher the same input.
_MATCHER_FIELDS = (
    "unit_number",
    "building_number",
    "property_number",
    "plot_number",
    "property_type",
    "size_sqft",
    "size_sqm",
    "size_unknown",
    "procedure_type",  # the matcher never links a financing row (mortgage...) to a sale
)
_MATCHER_IDENTIFIERS = ("unit_number", "building_number", "property_number", "plot_number")


def _decimal_text(value: Any) -> str:
    number = positive_decimal(value)
    return format(number, "f") if number is not None else ""


def matcher_source(
    row: tuple[Any, ...] | list[Any], profile: SheetProfile, row_number: int
) -> dict[str, str]:
    """The matcher's input for one sheet row (canonical field names, text values)."""
    source: dict[str, str] = {}
    for name in _LOCATION_FIELDS:
        value = _location_value(row, profile, name, row_number)[0]
        if value and not is_blank(value):
            source[name] = value
    for name in _MATCHER_FIELDS:
        value = _text(_field_value(row, profile, name))
        if value and not is_blank(value):
            source[name] = value
    price = _decimal_text(_field_value(row, profile, "transaction_price_aed"))
    if price:
        source["transaction_price_aed"] = price
    day = _parse_date(_field_value(row, profile, "transaction_date"), profile.date_order)
    if day:
        source["transaction_date"] = day.isoformat()
    return source


def matcher_source_from_evidence(
    evidence: dict[str, Any],
    *,
    transaction_date: date | None = None,
    transaction_price_aed: int | None = None,
    procedure_type: str = "",
    area_name: str = "",
    project_name: str = "",
    building_name: str = "",
    unit_number: str = "",
    property_type: str = "",
) -> dict[str, str]:
    """Rebuild the matcher's input for a stored claim that has no ``matcher_source``.

    Claims made before the property-first matcher kept the file's own cells in
    ``source_fields`` (what the sheet said, by canonical name), ``original_identifiers`` and
    ``source_identifiers``. A location the importer restored from an autofill run is read from
    ``original_property_fields``. A claim with no ``source_fields`` at all falls back to its
    property columns, which are the importer's normalised reading of the same cells.
    """
    fields = evidence.get("source_fields") or {}
    restored = evidence.get("original_fields") or {}
    resolved = evidence.get("original_property_fields") or {}
    columns = {
        "area_name": area_name,
        "project_name": project_name,
        "building_name": building_name,
        "unit_number": unit_number,
        "property_type": property_type,
        "procedure_type": procedure_type,
    }
    # Source-audited claims keep only size and type in ``source_fields``: with no location there,
    # the location and unit come from the claim's own columns.
    no_location = not any(name in fields for name in _LOCATION_FIELDS)
    source: dict[str, str] = {}
    for name in (*_LOCATION_FIELDS, *_MATCHER_FIELDS):
        value = ""
        if name in restored and resolved.get(name):
            value = str(resolved[name])  # the autofill run's restored value
        elif name in fields:
            value = _text(fields[name])
        elif name in _MATCHER_IDENTIFIERS:
            value = _text((evidence.get("original_identifiers") or {}).get(name)) or _text(
                (evidence.get("source_identifiers") or {}).get(name)
            )
        if not value and (
            not fields or (no_location and name in (*_LOCATION_FIELDS, "unit_number"))
        ):
            value = _text(columns.get(name))
        if name == "procedure_type" and not value:
            value = _text(procedure_type)
        if value and not is_blank(value):
            source[name] = value
    price = _decimal_text(fields.get("transaction_price_aed")) or _decimal_text(
        transaction_price_aed
    )
    if price:
        source["transaction_price_aed"] = price
    if transaction_date:
        source["transaction_date"] = transaction_date.isoformat()
    return source


def _missing_owner_name(name: str) -> bool:
    return name.strip().casefold() in {"", "-", "n/a", "na", "none", "null", "nan", "unknown"}


def _candidate_from_row(
    row: tuple[Any, ...] | list[Any],
    *,
    profile: SheetProfile,
    filename: str,
    row_number: int,
    dropped: list[dict[str, Any]] | None = None,
) -> ParsedContact | None:
    located = {
        canonical: _location_value(row, profile, canonical, row_number)
        for canonical in _LOCATION_FIELDS
    }
    area, master_project, explicit_project, building_source = (
        located[canonical][0] for canonical in _LOCATION_FIELDS
    )
    original_fields = {
        canonical: original for canonical, (_, original) in located.items() if original
    }
    inventory_fields = {key: _text(_field_value(row, profile, key)) for key in profile.field_map}
    for key, value in (
        ("area_name", area),
        ("master_project", master_project),
        ("project_name", explicit_project),
        ("building_name", building_source),
    ):
        if key in inventory_fields or key in {"master_project", "project_name"} and value:
            inventory_fields[key] = value
    profile.property_inventory.add(inventory_fields)
    name = _text(_field_value(row, profile, "contact_name"))
    unit = _normalize_unit(_field_value(row, profile, "unit_number"))
    if unit == "0":
        unit = ""
    unit_fallback_field = ""
    unit_fallback_value = ""
    if not unit:
        property_number = next(
            (
                _text(row[header.index])
                for header in profile.headers
                if _header_token(header.key) == "propertynumber"
                and header.index < len(row)
                and _text(row[header.index])
            ),
            "",
        )
        if property_number and _normalize_unit(property_number) not in {"0", "1"}:
            unit = _normalize_unit(property_number)
            unit_fallback_field = "propertynumber"
            unit_fallback_value = property_number
    building_no = _text(_field_value(row, profile, "building_number"))
    if _missing_owner_name(name):
        if dropped is not None:
            dropped.append(
                _dropped_row(row, profile=profile, row_number=row_number, reason="no_name")
            )
        return None
    role = _normalized_role(_field_value(row, profile, "party_role"))
    procedure = _text(_field_value(row, profile, "procedure_type"))
    inferred_project = _inferred_project(filename, profile.name)
    area_source_field = ""
    project = explicit_project or inferred_project
    building = building_source or project
    if not area:
        area = _usable_project_name(master_project)
        if area:
            area_source_field = "master_project"
    if not project:
        project = master_project

    phone = _normalize_phone(_field_value(row, profile, "phone_primary"))
    alternate = _normalize_phone(_field_value(row, profile, "phone_alternate"))
    channels = list(
        dict.fromkeys(
            value
            for value in (
                phone,
                alternate,
                *(
                    _normalize_phone(row[h.index])
                    for h in profile.headers
                    if h.index < len(row) and _header_token(h.key) in _CHANNEL_TOKENS
                ),
            )
            if value
        )
    )
    phone = channels[0] if channels else None
    alternate = channels[1] if len(channels) > 1 else None
    email = _normalize_email(_field_value(row, profile, "email_primary"))
    transaction_date = _parse_date(
        _field_value(row, profile, "transaction_date"), profile.date_order
    )
    transaction_price = _parse_amount(_field_value(row, profile, "transaction_price_aed"))
    fingerprint_source = "|".join(
        (
            profile.name,
            str(row_number),
            name.lower(),
            building.lower(),
            unit.lower(),
            transaction_date.isoformat() if transaction_date else "",
        )
    )
    candidate = ParsedContact(
        source_sheet=profile.name,
        source_row_number=row_number,
        contact_name=name[:300],
        phone_primary=phone,
        phone_alternate=alternate if alternate != phone else None,
        email_primary=email,
        area_name=area[:200],
        project_name=project[:200],
        building_name=building[:250],
        unit_number=unit[:100],
        property_type=_text(_field_value(row, profile, "property_type"))[:100],
        transaction_date=transaction_date,
        transaction_price_aed=transaction_price,
        party_role=role[:80],
        procedure_type=procedure[:160],
        row_fingerprint=hashlib.sha256(fingerprint_source.encode()).hexdigest(),
    )
    candidate.evidence.update(
        {
            "resolver_version": IMPORT_RESOLVER_VERSION,
            "source_filename": filename,
            "event_family": event_family(procedure),
            "source_size_unit": source_size_unit(profile.field_map),
            "original_identifiers": {
                key: _text(_field_value(row, profile, key))
                for key in (
                    "unit_number",
                    "building_number",
                    "property_number",
                    "plot_number",
                    "plot_pre_reg_number",
                )
            },
            "original_property_fields": {
                key: getattr(candidate, key)
                for key in (
                    "area_name",
                    "project_name",
                    "building_name",
                    "unit_number",
                    "property_type",
                )
            },
            "source_fields": {
                canonical: _text(_field_value(row, profile, canonical))
                for canonical in profile.field_map
            },
            "contact_channels": channels,
            "matcher_source": matcher_source(row, profile, row_number),
            "price_quality": "positive" if transaction_price is not None else "missing_or_invalid",
            "source_identifiers": {
                key: _text(_field_value(row, profile, key))
                for key in (
                    "land_number",
                    "land_sub_number",
                    "building_number",
                    "property_number",
                    "plot_number",
                    "municipality_number",
                    "municipality_sub_number",
                )
            },
        }
    )
    if area_source_field:
        candidate.evidence["source_area_field"] = area_source_field
    if original_fields:
        candidate.evidence["original_fields"] = original_fields
    source_unit = re.sub(r"\s+", "", _text(_field_value(row, profile, "unit_number"))).upper()
    if source_unit and source_unit.lower() != unit.lower():
        candidate.evidence["source_unit_number"] = source_unit[:100]
    if unit_fallback_field:
        candidate.evidence["source_unit_number"] = re.sub(r"\s+", "", unit_fallback_value).upper()[
            :100
        ]
        candidate.evidence["unit_number_fallback"] = {
            "source_field": unit_fallback_field,
            "source_value": unit_fallback_value[:100],
        }
    _recover_embedded_property_identity(candidate)
    address_recovery = candidate.evidence.get("address_recovery")
    building_no_identifier = _BUILDING_NO_NUMERIC_IDENTIFIER.fullmatch(building_no)
    if (
        not unit
        and isinstance(address_recovery, dict)
        and address_recovery.get("method") == "embedded_numeric_identifier"
        and building_no_identifier
    ):
        source_building = _text(_field_value(row, profile, "building_name"))
        candidate.building_name = _text(building_no_identifier.group(1))
        candidate.unit_number = _normalize_unit(building_no_identifier.group(2))
        candidate.evidence["source_unit_number"] = _normalize_unit(building_no)[:100]
        candidate.evidence["address_recovery"] = {
            "source_building_name": source_building,
            "source_building_no": building_no,
            "resolved_building_name": candidate.building_name,
            "resolved_unit_number": candidate.unit_number,
            "method": "building_no_structured_numeric_identifier",
        }
    # Keep the full code when the registry-style numeric suffix rule does not apply.
    if not candidate.unit_number and _BUILDING_NO_PROPERTY_IDENTIFIER.search(building_no):
        candidate.unit_number = _normalize_unit(building_no)[:100]
        candidate.evidence["source_unit_number"] = re.sub(r"\s+", "", building_no).upper()[:100]
    if (
        not candidate.unit_number
        and _normalize_unit(building_no) not in {"", "0", "1"}
        and any(character.isdigit() for character in building_no)
    ):
        candidate.unit_number = _normalize_unit(building_no)[:100]
        candidate.evidence["source_unit_number"] = re.sub(r"\s+", "", building_no).upper()[:100]
        candidate.evidence["unit_number_fallback"] = {
            "source_field": "buildingno",
            "source_value": building_no[:100],
        }
    candidate.evidence["location_normalization"] = location_evidence(
        candidate.area_name, candidate.project_name, candidate.building_name
    )
    return candidate


def _parse_xlsx(
    data: bytes,
    filename: str,
    profiles: list[SheetProfile],
    dropped: list[dict[str, Any]] | None = None,
) -> tuple[list[ParsedContact], int]:
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    candidates: list[ParsedContact] = []
    total_rows = 0
    profile_by_name = {profile.name: profile for profile in profiles}
    try:
        for sheet in workbook.worksheets:
            profile = profile_by_name.get(sheet.title.strip() or "Sheet")
            if not profile:
                continue
            profile.property_inventory = SourcePropertyInventory()
            max_index = max((header.index for header in profile.headers), default=0)
            location_indexes = _location_header_indexes(profile)
            if location_indexes:
                first = location_indexes[0]
                columns: dict[int, list[tuple[int, Any]]] = {i: [] for i in location_indexes}
                for row_number, row in enumerate(
                    sheet.iter_rows(
                        min_row=profile.header_row + 1,
                        max_row=profile.last_data_row,
                        min_col=first + 1,
                        max_col=location_indexes[-1] + 1,
                        values_only=True,
                    ),
                    start=profile.header_row + 1,
                ):
                    for index in location_indexes:
                        columns[index].append((row_number, row[index - first]))
                _repair_autofill_labels(profile, columns)
            date_index = _date_column_index(profile)
            if date_index is not None:
                _read_dates_by_column_order(
                    profile,
                    (
                        row[0] if row else None
                        for row in sheet.iter_rows(
                            min_row=profile.header_row + 1,
                            max_row=profile.last_data_row,
                            min_col=date_index + 1,
                            max_col=date_index + 1,
                            values_only=True,
                        )
                    ),
                )
            for row_number, row in enumerate(
                sheet.iter_rows(
                    min_row=profile.header_row + 1,
                    max_row=profile.last_data_row,
                    max_col=max_index + 1,
                    values_only=True,
                ),
                start=profile.header_row + 1,
            ):
                if not any(value not in (None, "") for value in row):
                    continue
                total_rows += 1
                if total_rows > _MAX_ROWS:
                    raise ValueError(f"Import exceeds the {_MAX_ROWS:,}-row limit")
                candidate = _candidate_from_row(
                    row,
                    profile=profile,
                    filename=filename,
                    row_number=row_number,
                    dropped=dropped,
                )
                if candidate:
                    candidates.append(candidate)
    finally:
        workbook.close()
    return candidates, total_rows


def _parse_csv(
    data: bytes,
    filename: str,
    profiles: list[SheetProfile],
    dropped: list[dict[str, Any]] | None = None,
) -> tuple[list[ParsedContact], int]:
    rows = _csv_rows(data)
    profile = profiles[0]
    profile.property_inventory = SourcePropertyInventory()
    _repair_autofill_labels(
        profile,
        {
            index: [
                (number, row[index] if index < len(row) else None)
                for number, row in enumerate(rows[profile.header_row :], profile.header_row + 1)
            ]
            for index in _location_header_indexes(profile)
        },
    )
    date_index = _date_column_index(profile)
    if date_index is not None:
        _read_dates_by_column_order(
            profile,
            (
                row[date_index] if date_index < len(row) else None
                for row in rows[profile.header_row :]
            ),
        )
    candidates: list[ParsedContact] = []
    total_rows = 0
    for row_number, row in enumerate(rows[profile.header_row :], start=profile.header_row + 1):
        if not any(value.strip() for value in row):
            continue
        total_rows += 1
        if total_rows > _MAX_ROWS:
            raise ValueError(f"Import exceeds the {_MAX_ROWS:,}-row limit")
        candidate = _candidate_from_row(
            row,
            profile=profile,
            filename=filename,
            row_number=row_number,
            dropped=dropped,
        )
        if candidate:
            candidates.append(candidate)
    return candidates, total_rows


def _summary(
    candidates: list[ParsedContact],
    total_rows: int,
    duplicate_rows_collapsed: int = 0,
    dropped_no_unit: int = 0,
) -> CrmContactImportSummary:
    return CrmContactImportSummary(
        total_rows=total_rows,
        candidate_rows=len(candidates),
        rows_with_sales_history=sum(c.latest_sale_date is not None for c in candidates),
        properties_linked_rows=sum(
            bool(c.latest_sale_date or c.unit_candidate_key or c.evidence.get("cadastral_identity"))
            for c in candidates
        ),
        plot_only_rows=sum(
            bool(c.evidence.get("cadastral_identity")) and not c.unit_number for c in candidates
        ),
        distinct_properties=len(
            {candidate.property_key for candidate in candidates if candidate.property_key}
        ),
        duplicate_rows_collapsed=duplicate_rows_collapsed,
        dropped_no_unit=dropped_no_unit,
        valid_contacts=sum(candidate.has_valid_contact for candidate in candidates),
        verified_current_owners=sum(
            candidate.ownership_status == "verified_current_owner" for candidate in candidates
        ),
        probable_current_owners=sum(
            candidate.ownership_status == "probable_current_owner" for candidate in candidates
        ),
        unit_linked_unverified=sum(
            candidate.ownership_status == "unit_linked_unverified" for candidate in candidates
        ),
        former_owners=sum(candidate.ownership_status == "former_owner" for candidate in candidates),
        unverified_former_owners=sum(
            candidate.ownership_status == "unverified_former_owner" for candidate in candidates
        ),
        conflicting_claims=sum(
            candidate.ownership_status == "conflicting_claim" for candidate in candidates
        ),
        insufficient_property_data=sum(
            candidate.ownership_status == "insufficient_property_data" for candidate in candidates
        ),
        registry_not_observed=sum(
            candidate.ownership_status == "registry_not_observed" for candidate in candidates
        ),
        unmatched=sum(candidate.ownership_status == "unmatched" for candidate in candidates),
        rental_opportunities=sum(bool(candidate.lead_id) for candidate in candidates),
        contact_ready=sum(
            bool(candidate.lead_id)
            and candidate.has_valid_contact
            and candidate.ownership_status in {"verified_current_owner", "probable_current_owner"}
            and candidate.party_role != "Seller"
            for candidate in candidates
        ),
    )


def _mapping_response(profile: SheetProfile) -> dict[str, Any]:
    return CrmSheetMapping(
        sheet_name=profile.name,
        header_row=profile.header_row,
        meaningful_rows=profile.meaningful_rows,
        sheet_family=profile.sheet_family,
        mapping_source=profile.mapping_source,  # type: ignore[arg-type]
        confidence=profile.confidence,
        field_map=profile.field_map,
        warnings=profile.warnings,
    ).model_dump(mode="json")
