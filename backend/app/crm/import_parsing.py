from __future__ import annotations

import csv
import hashlib
import io
import re
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
)
from app.crm.import_models import (
    CrmContactImportSummary,
    CrmSheetMapping,
)

_MAX_ROWS = 500_000

_PLACEHOLDER_HEADER = re.compile(r"^column\s*\d+$", re.IGNORECASE)

_TRANSFER_WORDS = ("sale", "sell", "delayed sell")

_CANONICAL_FIELDS = {
    "area_name",
    "master_project",
    "project_name",
    "building_name",
    "unit_number",
    "property_type",
    "size_sqft",
    "transaction_date",
    "transaction_price_aed",
    "party_role",
    "procedure_type",
    "contact_name",
    "phone_primary",
    "phone_alternate",
    "email_primary",
}

_ALIASES = {
    "area_name": {"areanameen", "area", "community"},
    "master_project": {"masterproject", "masterdevelopment"},
    "project_name": {"project", "projectname", "development"},
    "building_name": {"buildingnameen", "building", "tower", "buildingname"},
    "unit_number": {
        "unitnumber",
        "unit",
        "villanumber",
        "unitnumberproxy",
        "plotpreregisterationno",
        "plotpreregistrationno",
        "plotregistrationno",
    },
    "property_type": {"propertytypeen", "propertytype", "type"},
    "size_sqft": {"size", "areasqft", "propertysize"},
    "transaction_date": {"regis", "date", "registrationdate", "transactiondate"},
    "transaction_price_aed": {
        "procedurevalue",
        "price",
        "transactionvalue",
        "saleprice",
    },
    "party_role": {"procedurepartytypenameen", "partytype", "partyrole"},
    "procedure_type": {"procedurenameen", "procedurename"},
    "contact_name": {"nameen", "name", "ownername", "contactname"},
    "phone_primary": {"phone", "mobile", "phonenumber", "mobilenumber"},
    "phone_alternate": {"secondarymobile", "alternatemobile", "mobile2"},
    "email_primary": {"email", "emailaddress", "owneremail"},
}


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
    aliases = set().union(*_ALIASES.values())
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
    for field_name, aliases in _ALIASES.items():
        header = _header_for(headers, aliases)
        if header:
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

    family = "transaction_party" if mapping.get("transaction_date") else "contact_list"
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


def _inspect_xlsx(data: bytes, filename: str) -> list[SheetProfile]:
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    profiles: list[SheetProfile] = []
    try:
        for sheet in workbook.worksheets:
            initial_rows = list(
                sheet.iter_rows(
                    min_row=1,
                    max_row=min(15, max(1, sheet.max_row)),
                    max_col=min(100, max(1, sheet.max_column)),
                    values_only=True,
                )
            )
            header_row, headers = _find_header(initial_rows)
            mapping, family, warnings = _heuristic_mapping(
                headers,
                filename=filename,
                sheet_name=sheet.title,
            )
            profiles.append(
                SheetProfile(
                    name=sheet.title.strip() or "Sheet",
                    header_row=header_row,
                    headers=headers,
                    meaningful_rows=max(0, sheet.max_row - header_row),
                    field_map=mapping,
                    sheet_family=family,
                    warnings=warnings,
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
        SheetProfile(
            name=Path(filename).stem,
            header_row=header_row,
            headers=headers,
            meaningful_rows=max(0, len(rows) - header_row),
            field_map=mapping,
            sheet_family=family,
            warnings=warnings,
        )
    ]


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %b %Y",
        "%d-%b-%Y",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(value: Any) -> int | None:
    if isinstance(value, int | float) and value > 0:
        return int(round(value))
    raw = re.sub(r"[^\d.]", "", _text(value))
    if not raw:
        return None
    try:
        amount = int(round(float(raw)))
    except ValueError:
        return None
    return amount if amount > 0 else None


def _normalized_role(value: Any) -> str:
    role = _text(value).lower()
    if "buyer" in role:
        return "Buyer"
    if "seller" in role:
        return "Seller"
    return _text(value).title()


def _is_transfer_candidate(role: str, procedure: str, family: str) -> bool:
    if family == "contact_list":
        return True
    if role not in {"Buyer", "Seller"}:
        return False
    if not procedure:
        return True
    lowered = procedure.lower()
    return any(word in lowered for word in _TRANSFER_WORDS)


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


def _candidate_from_row(
    row: tuple[Any, ...] | list[Any],
    *,
    profile: SheetProfile,
    filename: str,
    row_number: int,
) -> ParsedContact | None:
    name = _text(_field_value(row, profile, "contact_name"))
    unit = _normalize_unit(_field_value(row, profile, "unit_number"))
    if not name:
        return None
    role = _normalized_role(_field_value(row, profile, "party_role"))
    procedure = _text(_field_value(row, profile, "procedure_type"))
    if not _is_transfer_candidate(role, procedure, profile.sheet_family):
        return None

    inferred_project = _inferred_project(filename, profile.name)
    area = _text(_field_value(row, profile, "area_name"))
    master_project = _text(_field_value(row, profile, "master_project"))
    project = _text(_field_value(row, profile, "project_name")) or inferred_project
    building = _text(_field_value(row, profile, "building_name")) or project
    if not area:
        area = "Tilal Al Ghaf" if inferred_project else master_project
    if not project:
        project = master_project

    phone = _normalize_phone(_field_value(row, profile, "phone_primary"))
    alternate = _normalize_phone(_field_value(row, profile, "phone_alternate"))
    email = _normalize_email(_field_value(row, profile, "email_primary"))
    transaction_date = _parse_date(_field_value(row, profile, "transaction_date"))
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
    _recover_embedded_property_identity(candidate)
    return candidate


def _parse_xlsx(
    data: bytes,
    filename: str,
    profiles: list[SheetProfile],
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
            max_index = max((header.index for header in profile.headers), default=0)
            for row_number, row in enumerate(
                sheet.iter_rows(
                    min_row=profile.header_row + 1,
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
) -> tuple[list[ParsedContact], int]:
    rows = _csv_rows(data)
    profile = profiles[0]
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
        )
        if candidate:
            candidates.append(candidate)
    return candidates, total_rows


def _summary(
    candidates: list[ParsedContact],
    total_rows: int,
    duplicate_rows_collapsed: int = 0,
) -> CrmContactImportSummary:
    return CrmContactImportSummary(
        total_rows=total_rows,
        candidate_rows=len(candidates),
        duplicate_rows_collapsed=duplicate_rows_collapsed,
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
