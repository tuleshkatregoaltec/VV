from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from typing import Any, Iterable

import httpx
import openpyxl
from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, or_, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.clickhouse.client import query
from app.config import settings
from app.crm.import_models import (
    CrmContactClaimResponse,
    CrmContactImport,
    CrmContactImportResponse,
    CrmContactImportSummary,
    CrmContactList,
    CrmContactListDetail,
    CrmContactListSummary,
    CrmLeadImportedContact,
    CrmOwnerBulkUpdate,
    CrmOwnerNote,
    CrmOwnerProfile,
    CrmOwnerProperty,
    CrmOwnerRegistryResponse,
    CrmOwnerRegistrySummary,
    CrmOwnerWorkspace,
    CrmOwnerWorkspaceSummary,
    CrmPropertyContactClaim,
    CrmSheetMapping,
)
from app.crm.models import CrmLeadWorkspace

logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 50 * 1024 * 1024
_MAX_ROWS = 500_000
_QUERY_CHUNK = 4_000
_PLACEHOLDER_HEADER = re.compile(r"^column\s*\d+$", re.IGNORECASE)
_NON_KEY = re.compile(r"[^a-z0-9]+")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TRANSFER_WORDS = ("sale", "sell", "delayed sell")
_OWNER_SUMMARY_CACHE_TTL_SECONDS = 300
_owner_summary_cache: dict[tuple[str, int | None], tuple[float, CrmOwnerRegistrySummary]] = {}


def _invalidate_owner_summary_cache(organization_id: str) -> None:
    for key in [key for key in _owner_summary_cache if key[0] == organization_id]:
        _owner_summary_cache.pop(key, None)

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


@dataclass
class ParsedContact:
    source_sheet: str
    source_row_number: int
    contact_name: str
    phone_primary: str | None
    phone_alternate: str | None
    email_primary: str | None
    area_name: str
    project_name: str
    building_name: str
    unit_number: str
    property_type: str
    transaction_date: date | None
    transaction_price_aed: int | None
    party_role: str
    procedure_type: str
    row_fingerprint: str
    ownership_status: str = "unmatched"
    confidence_score: int = 20
    match_reason: str = "No exact property evidence was found."
    lead_id: str | None = None
    unit_candidate_key: str | None = None
    latest_sale_date: date | None = None
    latest_sale_price_aed: int | None = None
    later_sale_date: date | None = None
    lease_end: date | None = None
    annual_rent_aed: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def has_valid_contact(self) -> bool:
        return bool(self.phone_primary or self.phone_alternate or self.email_primary)

    @property
    def property_key(self) -> str:
        location = self.building_name or self.project_name
        if not location or not self.unit_number:
            return ""
        return f"{_location_key(location)}|{self.unit_number.lower()}"


_OWNERSHIP_PRIORITY = {
    "former_owner": 6,
    "verified_current_owner": 5,
    "probable_current_owner": 4,
    "unit_linked_unverified": 3,
    "conflicting_claim": 2,
    "unmatched": 1,
}

_OWNER_REGISTRY_BASE_SQL = """
WITH base AS (
    SELECT
        c.id,
        c.organization_id,
        c.import_id,
        c.list_id,
        c.source_sheet,
        c.source_row_number,
        c.owner_key,
        c.property_key,
        c.contact_name,
        c.phone_primary,
        c.phone_alternate,
        c.email_primary,
        c.area_name,
        c.project_name,
        c.building_name,
        c.unit_number,
        c.property_type,
        c.transaction_date,
        c.ownership_status,
        c.confidence_score,
        c.match_reason,
        c.lead_id,
        c.unit_candidate_key,
        c.latest_sale_date,
        c.latest_sale_price_aed,
        c.later_sale_date,
        c.lease_end,
        c.annual_rent_aed,
        c.owner_key AS owner_key_sql,
        c.property_key AS property_key_sql,
        CASE c.ownership_status
            WHEN 'former_owner' THEN 6
            WHEN 'verified_current_owner' THEN 5
            WHEN 'probable_current_owner' THEN 4
            WHEN 'unit_linked_unverified' THEN 3
            WHEN 'conflicting_claim' THEN 2
            ELSE 1
        END AS status_rank
    FROM crm_property_contact_claims c
    WHERE c.organization_id = :organization_id
      AND (
        CAST(:owner_list_id AS INTEGER) IS NULL
        OR c.list_id = CAST(:owner_list_id AS INTEGER)
      )
),
ranked AS (
    SELECT DISTINCT ON (owner_key_sql, property_key_sql)
        *
    FROM base
    ORDER BY
        owner_key_sql,
        property_key_sql,
        status_rank DESC,
        confidence_score DESC,
        transaction_date DESC NULLS LAST
),
properties AS (
    SELECT * FROM ranked
)
"""


def _identity_text(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _owner_key(
    *,
    contact_name: str,
    phone_primary: str | None,
    phone_alternate: str | None,
    email_primary: str | None,
    property_key: str,
) -> str:
    name = _identity_text(contact_name)
    contact = phone_primary or phone_alternate or (email_primary or "").casefold()
    # A name without a contact identifier is not safe evidence that two different
    # properties share one owner. Keep those identities property-scoped.
    seed = f"{name}|{contact or property_key}"
    return hashlib.md5(seed.encode(), usedforsecurity=False).hexdigest()


def _candidate_owner_key(candidate: ParsedContact) -> str:
    return _owner_key(
        contact_name=candidate.contact_name,
        phone_primary=candidate.phone_primary,
        phone_alternate=candidate.phone_alternate,
        email_primary=candidate.email_primary,
        property_key=candidate.property_key,
    )


def _candidate_preference(candidate: ParsedContact) -> tuple[int, int, int, int]:
    return (
        _OWNERSHIP_PRIORITY.get(candidate.ownership_status, 0),
        candidate.confidence_score,
        1 if candidate.has_valid_contact else 0,
        candidate.transaction_date.toordinal() if candidate.transaction_date else 0,
    )


def _dedupe_candidates(candidates: list[ParsedContact]) -> tuple[list[ParsedContact], int]:
    grouped: dict[tuple[str, str], list[ParsedContact]] = {}
    for candidate in candidates:
        property_key = candidate.property_key or f"source:{candidate.row_fingerprint}"
        grouped.setdefault((_candidate_owner_key(candidate), property_key), []).append(candidate)

    unique: list[ParsedContact] = []
    collapsed = 0
    for group in grouped.values():
        best = max(group, key=_candidate_preference)
        ordered_rows = sorted({f"{item.source_sheet}:{item.source_row_number}" for item in group})
        if len(group) > 1:
            collapsed += len(group) - 1
            best.evidence = {
                **best.evidence,
                "duplicate_count": len(group),
                "source_rows": ordered_rows,
                "alternate_claims": [
                    {
                        "source_sheet": item.source_sheet,
                        "source_row_number": item.source_row_number,
                        "transaction_date": (
                            item.transaction_date.isoformat() if item.transaction_date else None
                        ),
                        "transaction_price_aed": item.transaction_price_aed,
                        "ownership_status": item.ownership_status,
                        "confidence_score": item.confidence_score,
                    }
                    for item in group
                    if item is not best
                ],
            }
        best.phone_primary = best.phone_primary or next(
            (item.phone_primary for item in group if item.phone_primary),
            None,
        )
        best.phone_alternate = best.phone_alternate or next(
            (item.phone_alternate for item in group if item.phone_alternate),
            None,
        )
        best.email_primary = best.email_primary or next(
            (item.email_primary for item in group if item.email_primary),
            None,
        )
        unique.append(best)
    unique.sort(key=lambda item: (item.source_sheet, item.source_row_number))
    return unique, collapsed


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _chunks(values: list[str], size: int = _QUERY_CHUNK) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _header_token(value: str) -> str:
    base = value.rsplit("__", 1)[0]
    return _NON_KEY.sub("", base.lower())


def _location_key(value: str) -> str:
    normalized = value.lower()
    for source, target in {
        "jumeriah": "jumeirah",
        "residences": "residence",
        "apartments": "apartment",
    }.items():
        normalized = normalized.replace(source, target)
    return _NON_KEY.sub("", normalized)


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


async def _llm_mapping(profile: SheetProfile) -> SheetProfile:
    prompt = {
        "task": "Map spreadsheet headers to canonical CRM owner-import fields.",
        "privacy": "Headers only. No owner names, phone numbers, emails, or row values are included.",
        "canonical_fields": sorted(_CANONICAL_FIELDS),
        "headers": [header.key for header in profile.headers],
        "heuristic_mapping": profile.field_map,
        "requirements": [
            "Return JSON only.",
            "Only use canonical fields and exact supplied header names.",
            "Do not invent a unit number when no unit column exists.",
        ],
        "response_shape": {
            "field_map": {"canonical_field": "exact header"},
            "sheet_family": "transaction_party or contact_list",
            "confidence": "number from 0 to 1",
            "warnings": ["string"],
        },
    }
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.DEFAULT_CHAT_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You map spreadsheet schemas. Return a single valid JSON object "
                                "and never infer or request personal data."
                            ),
                        },
                        {"role": "user", "content": json.dumps(prompt)},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "max_tokens": 900,
                    "provider": {"zdr": True},
                },
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            proposal = json.loads(content)
    except Exception:
        logger.warning(
            "CRM import schema mapping fell back to heuristics",
            extra={"sheet": profile.name},
            exc_info=True,
        )
        profile.mapping_source = "heuristic_fallback"
        profile.warnings.append("Automated schema confirmation was unavailable.")
        return profile

    available = {header.key for header in profile.headers}
    llm_map = proposal.get("field_map") if isinstance(proposal, dict) else {}
    if isinstance(llm_map, dict):
        for canonical, header in llm_map.items():
            if canonical in _CANONICAL_FIELDS and header in available:
                profile.field_map.setdefault(canonical, header)
    family = proposal.get("sheet_family")
    if family in {"transaction_party", "contact_list"}:
        profile.sheet_family = family
    confidence = proposal.get("confidence")
    if isinstance(confidence, int | float):
        profile.confidence = max(0.0, min(1.0, float(confidence)))
    warnings = proposal.get("warnings")
    if isinstance(warnings, list):
        profile.warnings.extend(str(item)[:300] for item in warnings if item)
    profile.mapping_source = "llm"
    return profile


def _normalize_unit(value: Any) -> str:
    unit = _text(value).upper().replace("–", "-")
    unit = re.sub(r"\s+", "", unit)
    if unit.endswith(".0") and unit[:-2].isdigit():
        unit = unit[:-2]
    if unit.startswith("TAG-") and "-" in unit:
        unit = unit.rsplit("-", 1)[-1]
    return unit


def _normalize_phone(value: Any) -> str | None:
    raw = _text(value)
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("971") and len(digits) >= 11:
        return f"+{digits}"
    if digits.startswith("05") and len(digits) == 10:
        return f"+971{digits[1:]}"
    if digits.startswith("5") and len(digits) == 9:
        return f"+971{digits}"
    if len(digits) < 7:
        return None
    return f"+{digits}" if raw.startswith("+") else digits


def _normalize_email(value: Any) -> str | None:
    email = _text(value).lower()
    return email if email and _EMAIL.match(email) else None


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
    if not name or not unit:
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
    return ParsedContact(
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


async def _sales_evidence(
    candidates: list[ParsedContact],
) -> dict[str, list[dict[str, Any]]]:
    property_keys = sorted(
        {candidate.property_key for candidate in candidates if candidate.property_key}
    )
    evidence: dict[str, list[dict[str, Any]]] = {}
    for chunk in _chunks(property_keys):
        rows = await query(
            """
            SELECT
                concat(building_key, '|', lowerUTF8(unit_number)) AS property_key,
                transaction_date,
                sale_amount_aed,
                sale_key,
                detail_url
            FROM dxbi_sales_unit_events FINAL
            WHERE concat(building_key, '|', lowerUTF8(unit_number))
                IN {property_keys:Array(String)}
            ORDER BY property_key, transaction_date
            """,
            {"property_keys": chunk},
        )
        for row in rows:
            evidence.setdefault(str(row["property_key"]), []).append(row)
    return evidence


async def _rental_evidence(
    candidates: list[ParsedContact],
) -> dict[str, dict[str, Any]]:
    units = sorted({candidate.unit_number for candidate in candidates if candidate.unit_number})
    evidence: dict[str, dict[str, Any]] = {}
    anchor = date.today()
    for chunk in _chunks(units):
        rows = await query(
            """
            SELECT
                c.event_key,
                c.unit_candidate_key,
                c.building_name,
                c.project_name,
                c.area_name,
                c.property_type,
                c.lease_end,
                c.annual_rent_aed,
                m.unit_number
            FROM dxbi_rental_unit_candidates AS c FINAL
            INNER JOIN dxbi_rental_sale_matches AS m FINAL USING (unit_candidate_key)
            WHERE
                m.match_status = 'unique'
                AND m.unit_number IN {units:Array(String)}
                AND c.lease_end >= {window_start:Date}
                AND c.lease_end <= {window_end:Date}
            ORDER BY c.lease_end DESC
            """,
            {
                "units": chunk,
                "window_start": (anchor - timedelta(days=365)).isoformat(),
                "window_end": (anchor + timedelta(days=90)).isoformat(),
            },
        )
        for row in rows:
            location = str(row.get("building_name") or row.get("project_name") or "")
            key = f"{_location_key(location)}|{str(row['unit_number']).lower()}"
            evidence.setdefault(key, row)
    return evidence


def _price_matches(imported: int | None, observed: int) -> bool:
    if not imported or not observed:
        return True
    return abs(imported - observed) / observed <= 0.02


def _apply_evidence(
    candidate: ParsedContact,
    *,
    sales: dict[str, list[dict[str, Any]]],
    rentals: dict[str, dict[str, Any]],
) -> None:
    key = candidate.property_key
    sale_events = sales.get(key, [])
    rental = rentals.get(key)
    if rental:
        candidate.lead_id = str(rental["event_key"])
        candidate.unit_candidate_key = str(rental["unit_candidate_key"])
        candidate.lease_end = rental.get("lease_end")
        candidate.annual_rent_aed = int(rental.get("annual_rent_aed") or 0) or None

    latest = sale_events[-1] if sale_events else None
    if latest:
        candidate.latest_sale_date = latest["transaction_date"]
        candidate.latest_sale_price_aed = int(latest.get("sale_amount_aed") or 0) or None

    if candidate.party_role == "Seller":
        candidate.ownership_status = "former_owner"
        candidate.confidence_score = 100
        candidate.match_reason = (
            "The uploaded record identifies this contact as the seller, not the current buyer."
        )
        if candidate.transaction_date:
            candidate.later_sale_date = candidate.transaction_date
        return

    if not key:
        candidate.match_reason = "The source row does not contain a usable building and unit."
        return

    if not latest:
        if rental:
            candidate.ownership_status = "unit_linked_unverified"
            candidate.confidence_score = 60
            candidate.match_reason = (
                "The contact links to an exact lease-opportunity unit, but acquisition "
                "evidence was not found in the sales registry."
            )
        else:
            candidate.match_reason = "No exact building and unit match was found."
        return

    if not candidate.transaction_date:
        candidate.ownership_status = "unit_linked_unverified"
        candidate.confidence_score = 62 if rental else 55
        candidate.match_reason = (
            "The unit is exact, but the uploaded contact list does not provide an "
            "acquisition date or price."
        )
        return

    matched_event = next(
        (
            event
            for event in sale_events
            if abs((event["transaction_date"] - candidate.transaction_date).days) <= 2
        ),
        None,
    )
    if latest["transaction_date"] > candidate.transaction_date + timedelta(days=2):
        candidate.ownership_status = "former_owner"
        candidate.confidence_score = 99
        candidate.later_sale_date = latest["transaction_date"]
        candidate.match_reason = (
            f"A later sale was recorded on {latest['transaction_date']:%d %b %Y}; "
            "this contact is not presented as the current owner."
        )
        return

    if matched_event and not _price_matches(
        candidate.transaction_price_aed,
        int(matched_event.get("sale_amount_aed") or 0),
    ):
        candidate.ownership_status = "conflicting_claim"
        candidate.confidence_score = 45
        candidate.match_reason = (
            "The building, unit, and date match, but the uploaded price differs by more "
            "than 2% from the sales registry."
        )
        return

    if matched_event and candidate.transaction_price_aed:
        candidate.ownership_status = "verified_current_owner"
        candidate.confidence_score = 98
        candidate.match_reason = (
            "Exact building and unit; acquisition date and price match the latest sale, "
            "with no later transfer observed."
        )
        return

    if matched_event:
        candidate.ownership_status = "probable_current_owner"
        candidate.confidence_score = 86
        candidate.match_reason = (
            "Exact building and unit; acquisition date matches the latest sale and no "
            "later transfer is observed. Price evidence was unavailable."
        )
        return

    if candidate.transaction_date > latest["transaction_date"]:
        candidate.ownership_status = "probable_current_owner"
        candidate.confidence_score = 72
        candidate.match_reason = (
            "The exact unit matches, but the uploaded acquisition is newer than available "
            "sales-registry coverage and requires review."
        )
        return

    candidate.ownership_status = "conflicting_claim"
    candidate.confidence_score = 40
    candidate.match_reason = (
        "The unit is exact, but the uploaded acquisition date does not match the observed "
        "sales history."
    )


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
        unmatched=sum(candidate.ownership_status == "unmatched" for candidate in candidates),
        rental_opportunities=sum(bool(candidate.lead_id) for candidate in candidates),
        contact_ready=sum(
            bool(candidate.lead_id)
            and candidate.has_valid_contact
            and candidate.ownership_status in {"verified_current_owner", "probable_current_owner"}
            for candidate in candidates
        ),
    )


async def _enrich_workspaces(
    db: AsyncSession,
    *,
    candidates: list[ParsedContact],
    user_id: str,
    organization_id: str,
    list_name: str,
) -> None:
    ready = [
        candidate
        for candidate in candidates
        if candidate.unit_candidate_key
        and candidate.lead_id
        and candidate.has_valid_contact
        and candidate.ownership_status in {"verified_current_owner", "probable_current_owner"}
    ]
    if not ready:
        return
    candidate_keys = sorted(
        {candidate.unit_candidate_key for candidate in ready if candidate.unit_candidate_key}
    )
    result = await db.exec(
        select(CrmLeadWorkspace).where(
            CrmLeadWorkspace.user_id == user_id,
            CrmLeadWorkspace.organization_id == organization_id,
            CrmLeadWorkspace.unit_candidate_key.in_(candidate_keys),  # type: ignore[union-attr]
        )
    )
    existing = {workspace.unit_candidate_key: workspace for workspace in result.all()}
    now = _utcnow()
    for candidate in ready:
        candidate_key = candidate.unit_candidate_key
        if not candidate_key:
            continue
        workspace = existing.get(candidate_key)
        if workspace is None:
            workspace = CrmLeadWorkspace(
                user_id=user_id,
                organization_id=organization_id,
                lead_id=candidate.lead_id or "",
                unit_candidate_key=candidate_key,
                pipeline_status="contact_ready",
                highlight_color="green",
                owner_name=candidate.contact_name,
                owner_email=candidate.email_primary,
                owner_phone=candidate.phone_primary or candidate.phone_alternate,
                tags=["Imported owner", list_name[:80]],
                created_at=now,
                updated_at=now,
            )
            db.add(workspace)
            existing[candidate_key] = workspace
            continue
        workspace.pipeline_status = (
            "contact_ready" if workspace.pipeline_status == "new" else workspace.pipeline_status
        )
        workspace.owner_name = workspace.owner_name or candidate.contact_name
        workspace.owner_email = workspace.owner_email or candidate.email_primary
        workspace.owner_phone = (
            workspace.owner_phone or candidate.phone_primary or candidate.phone_alternate
        )
        tags = list(workspace.tags or [])
        for tag in ("Imported owner", list_name[:80]):
            if tag not in tags and len(tags) < 12:
                tags.append(tag)
        workspace.tags = tags
        workspace.updated_at = now
        db.add(workspace)


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


async def process_contact_import(
    db: AsyncSession,
    *,
    upload: UploadFile,
    name: str,
    user_id: str,
    organization_id: str,
) -> CrmContactImportResponse:
    filename = Path(upload.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".xlsx", ".csv"}:
        raise HTTPException(status_code=400, detail="Upload an XLSX or CSV file")
    data = await upload.read(_MAX_FILE_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    if len(data) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="The uploaded file exceeds 50 MB")
    sha256 = hashlib.sha256(data).hexdigest()
    existing_result = await db.exec(
        select(CrmContactImport).where(
            CrmContactImport.organization_id == organization_id,
            CrmContactImport.sha256 == sha256,
        )
    )
    existing = existing_result.first()
    if existing:
        return await _import_response(db, existing)

    now = _utcnow()
    record = CrmContactImport(
        organization_id=organization_id,
        created_by_user_id=user_id,
        name=name.strip()[:200] or Path(filename).stem[:200],
        original_filename=filename,
        sha256=sha256,
        size_bytes=len(data),
        status="processing",
        mapping={},
        summary={},
        created_at=now,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    if record.id is None:
        raise HTTPException(status_code=500, detail="Import record could not be created")

    try:
        inspector = _inspect_xlsx if suffix == ".xlsx" else _inspect_csv
        profiles = await asyncio.to_thread(inspector, data, filename)
        profiles = [await _llm_mapping(profile) for profile in profiles]
        parser = _parse_xlsx if suffix == ".xlsx" else _parse_csv
        candidates, total_rows = await asyncio.to_thread(parser, data, filename, profiles)
        sales, rentals = await asyncio.gather(
            _sales_evidence(candidates),
            _rental_evidence(candidates),
        )
        for candidate in candidates:
            _apply_evidence(candidate, sales=sales, rentals=rentals)
        candidates, duplicate_rows_collapsed = _dedupe_candidates(candidates)

        contact_list = CrmContactList(
            organization_id=organization_id,
            created_by_user_id=user_id,
            source_import_id=record.id,
            name=record.name,
            description=f"Imported from {filename}",
            created_at=now,
            updated_at=now,
        )
        db.add(contact_list)
        await db.flush()
        if contact_list.id is None:
            raise RuntimeError("Contact list could not be created")

        for start in range(0, len(candidates), 1_000):
            db.add_all(
                [
                    CrmPropertyContactClaim(
                        organization_id=organization_id,
                        import_id=record.id,
                        list_id=contact_list.id,
                        source_sheet=candidate.source_sheet,
                        source_row_number=candidate.source_row_number,
                        row_fingerprint=candidate.row_fingerprint,
                        owner_key=_candidate_owner_key(candidate),
                        property_key=candidate.property_key
                        or f"source:{candidate.row_fingerprint}",
                        contact_name=candidate.contact_name,
                        phone_primary=candidate.phone_primary,
                        phone_alternate=candidate.phone_alternate,
                        email_primary=candidate.email_primary,
                        area_name=candidate.area_name,
                        project_name=candidate.project_name,
                        building_name=candidate.building_name,
                        unit_number=candidate.unit_number,
                        property_type=candidate.property_type,
                        transaction_date=candidate.transaction_date,
                        transaction_price_aed=candidate.transaction_price_aed,
                        party_role=candidate.party_role,
                        procedure_type=candidate.procedure_type,
                        ownership_status=candidate.ownership_status,
                        confidence_score=candidate.confidence_score,
                        match_reason=candidate.match_reason,
                        lead_id=candidate.lead_id,
                        unit_candidate_key=candidate.unit_candidate_key,
                        latest_sale_date=candidate.latest_sale_date,
                        latest_sale_price_aed=candidate.latest_sale_price_aed,
                        later_sale_date=candidate.later_sale_date,
                        lease_end=candidate.lease_end,
                        annual_rent_aed=candidate.annual_rent_aed,
                        evidence=candidate.evidence,
                        created_at=now,
                        updated_at=now,
                    )
                    for candidate in candidates[start : start + 1_000]
                ]
            )
            await db.flush()

        await _enrich_workspaces(
            db,
            candidates=candidates,
            user_id=user_id,
            organization_id=organization_id,
            list_name=record.name,
        )
        summary = _summary(candidates, total_rows, duplicate_rows_collapsed)
        record.status = "completed"
        record.mapping = {"sheets": [_mapping_response(profile) for profile in profiles]}
        record.summary = summary.model_dump()
        record.completed_at = _utcnow()
        db.add(record)
        await db.commit()
        _invalidate_owner_summary_cache(organization_id)
        return await _import_response(db, record)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("CRM contact import failed", extra={"import_id": record.id})
        await db.rollback()
        record.status = "failed"
        record.error_message = str(exc)[:2_000]
        record.completed_at = _utcnow()
        db.add(record)
        await db.commit()
        raise HTTPException(status_code=422, detail=f"Import failed: {exc}") from exc


async def _import_response(
    db: AsyncSession,
    record: CrmContactImport,
) -> CrmContactImportResponse:
    list_result = await db.exec(
        select(CrmContactList).where(CrmContactList.source_import_id == record.id)
    )
    contact_list = list_result.first()
    raw_sheets = record.mapping.get("sheets", []) if record.mapping else []
    return CrmContactImportResponse(
        id=record.id or 0,
        list_id=contact_list.id if contact_list else None,
        name=record.name,
        original_filename=record.original_filename,
        status=record.status,  # type: ignore[arg-type]
        summary=CrmContactImportSummary.model_validate(record.summary or {}),
        mappings=[CrmSheetMapping.model_validate(item) for item in raw_sheets],
        error_message=record.error_message,
        created_at=record.created_at,
        completed_at=record.completed_at,
    )


async def list_contact_imports(
    db: AsyncSession,
    *,
    organization_id: str,
) -> list[CrmContactImportResponse]:
    result = await db.exec(
        select(CrmContactImport)
        .where(CrmContactImport.organization_id == organization_id)
        .order_by(CrmContactImport.created_at.desc())
    )
    return [await _import_response(db, record) for record in result.all()]


async def rename_contact_import(
    db: AsyncSession,
    *,
    import_id: int,
    name: str,
    organization_id: str,
) -> CrmContactImportResponse:
    result = await db.exec(
        select(CrmContactImport).where(
            CrmContactImport.id == import_id,
            CrmContactImport.organization_id == organization_id,
        )
    )
    record = result.first()
    if not record:
        raise HTTPException(status_code=404, detail="Owner-data import not found")
    cleaned = name.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Import name cannot be empty")
    record.name = cleaned[:200]
    db.add(record)
    list_result = await db.exec(
        select(CrmContactList).where(
            CrmContactList.source_import_id == import_id,
            CrmContactList.organization_id == organization_id,
        )
    )
    contact_list = list_result.first()
    if contact_list:
        contact_list.name = record.name
        contact_list.updated_at = _utcnow()
        db.add(contact_list)
    await db.commit()
    await db.refresh(record)
    return await _import_response(db, record)


async def delete_contact_import(
    db: AsyncSession,
    *,
    import_id: int,
    organization_id: str,
) -> None:
    result = await db.exec(
        select(CrmContactImport).where(
            CrmContactImport.id == import_id,
            CrmContactImport.organization_id == organization_id,
        )
    )
    record = result.first()
    if not record:
        raise HTTPException(status_code=404, detail="Owner-data import not found")

    # Remove only records published by this import. Agent-maintained lead
    # workspaces, notes, and manually saved properties are intentionally kept.
    await db.exec(
        delete(CrmPropertyContactClaim).where(
            CrmPropertyContactClaim.import_id == import_id,
            CrmPropertyContactClaim.organization_id == organization_id,
        )
    )
    await db.exec(
        delete(CrmContactList).where(
            CrmContactList.source_import_id == import_id,
            CrmContactList.organization_id == organization_id,
        )
    )
    await db.delete(record)
    await db.commit()
    _invalidate_owner_summary_cache(organization_id)


def _claim_property_key(claim: CrmPropertyContactClaim) -> str:
    if claim.property_key:
        return claim.property_key
    location = claim.building_name or claim.project_name
    if not location or not claim.unit_number:
        return f"claim:{claim.id or claim.row_fingerprint}"
    return f"{_location_key(location)}|{claim.unit_number.casefold()}"


def _claim_owner_key(claim: CrmPropertyContactClaim) -> str:
    if claim.owner_key:
        return claim.owner_key
    return _owner_key(
        contact_name=claim.contact_name,
        phone_primary=claim.phone_primary,
        phone_alternate=claim.phone_alternate,
        email_primary=claim.email_primary,
        property_key=_claim_property_key(claim),
    )


def _claim_preference(claim: CrmPropertyContactClaim) -> tuple[int, int, int, int]:
    return (
        _OWNERSHIP_PRIORITY.get(claim.ownership_status, 0),
        claim.confidence_score,
        1 if claim.phone_primary or claim.phone_alternate or claim.email_primary else 0,
        claim.transaction_date.toordinal() if claim.transaction_date else 0,
    )


def _dedupe_claims(
    claims: list[CrmPropertyContactClaim],
) -> list[list[CrmPropertyContactClaim]]:
    grouped: dict[tuple[str, str], list[CrmPropertyContactClaim]] = {}
    for claim in claims:
        grouped.setdefault(
            (_claim_owner_key(claim), _claim_property_key(claim)),
            [],
        ).append(claim)
    groups = list(grouped.values())
    groups.sort(
        key=lambda group: _claim_preference(max(group, key=_claim_preference)), reverse=True
    )
    return groups


def _claim_source_rows(group: list[CrmPropertyContactClaim]) -> list[str]:
    values = {f"{claim.source_sheet}:{claim.source_row_number}" for claim in group}
    for claim in group:
        source_rows = claim.evidence.get("source_rows", []) if claim.evidence else []
        if isinstance(source_rows, list):
            values.update(str(item) for item in source_rows if item)
    return sorted(values)


def _claim_duplicate_count(group: list[CrmPropertyContactClaim]) -> int:
    persisted = [
        int(claim.evidence.get("duplicate_count", 1))
        for claim in group
        if claim.evidence and isinstance(claim.evidence.get("duplicate_count", 1), int)
    ]
    return max(len(group), max(persisted, default=1))


def _claim_response(
    claim: CrmPropertyContactClaim,
    group: list[CrmPropertyContactClaim] | None = None,
) -> CrmContactClaimResponse:
    if claim.id is None:
        raise HTTPException(status_code=500, detail="Imported contact is missing an id")
    grouped = group or [claim]
    return CrmContactClaimResponse(
        id=claim.id,
        source_sheet=claim.source_sheet,
        source_row_number=claim.source_row_number,
        contact_name=claim.contact_name,
        phone_primary=claim.phone_primary,
        phone_alternate=claim.phone_alternate,
        email_primary=claim.email_primary,
        area_name=claim.area_name,
        project_name=claim.project_name,
        building_name=claim.building_name,
        unit_number=claim.unit_number,
        property_type=claim.property_type,
        transaction_date=claim.transaction_date,
        transaction_price_aed=claim.transaction_price_aed,
        ownership_status=claim.ownership_status,  # type: ignore[arg-type]
        confidence_score=claim.confidence_score,
        match_reason=claim.match_reason,
        lead_id=claim.lead_id,
        unit_candidate_key=claim.unit_candidate_key,
        latest_sale_date=claim.latest_sale_date,
        latest_sale_price_aed=claim.latest_sale_price_aed,
        later_sale_date=claim.later_sale_date,
        lease_end=claim.lease_end,
        annual_rent_aed=claim.annual_rent_aed,
        owner_key=_claim_owner_key(claim),
        duplicate_count=_claim_duplicate_count(grouped),
        source_rows=_claim_source_rows(grouped),
    )


def _list_summary(
    contact_list: CrmContactList,
    claims: list[CrmPropertyContactClaim],
) -> CrmContactListSummary:
    if contact_list.id is None:
        raise HTTPException(status_code=500, detail="CRM contact list is missing an id")
    unique_claims = [max(group, key=_claim_preference) for group in _dedupe_claims(claims)]
    return CrmContactListSummary(
        id=contact_list.id,
        source_import_id=contact_list.source_import_id,
        name=contact_list.name,
        description=contact_list.description,
        total_contacts=len(unique_claims),
        contact_ready=sum(
            bool(claim.lead_id)
            and bool(claim.phone_primary or claim.phone_alternate or claim.email_primary)
            and claim.ownership_status in {"verified_current_owner", "probable_current_owner"}
            for claim in unique_claims
        ),
        needs_review=sum(
            claim.ownership_status in {"unit_linked_unverified", "conflicting_claim"}
            for claim in unique_claims
        ),
        former_owners=sum(claim.ownership_status == "former_owner" for claim in unique_claims),
        created_at=contact_list.created_at,
        updated_at=contact_list.updated_at,
    )


async def list_contact_lists(
    db: AsyncSession,
    *,
    organization_id: str,
) -> list[CrmContactListSummary]:
    list_result = await db.exec(
        select(CrmContactList)
        .where(CrmContactList.organization_id == organization_id)
        .order_by(CrmContactList.updated_at.desc())
    )
    contact_lists = list(list_result.all())
    if not contact_lists:
        return []
    ids = [item.id for item in contact_lists if item.id is not None]
    claim_result = await db.exec(
        select(CrmPropertyContactClaim).where(
            CrmPropertyContactClaim.organization_id == organization_id,
            CrmPropertyContactClaim.list_id.in_(ids),  # type: ignore[union-attr]
        )
    )
    grouped: dict[int, list[CrmPropertyContactClaim]] = {}
    for claim in claim_result.all():
        grouped.setdefault(claim.list_id, []).append(claim)
    return [_list_summary(item, grouped.get(item.id or 0, [])) for item in contact_lists]


async def get_contact_list(
    db: AsyncSession,
    *,
    list_id: int,
    organization_id: str,
    status: str | None,
    search: str | None,
    limit: int,
    offset: int,
) -> CrmContactListDetail:
    list_result = await db.exec(
        select(CrmContactList).where(
            CrmContactList.id == list_id,
            CrmContactList.organization_id == organization_id,
        )
    )
    contact_list = list_result.first()
    if not contact_list:
        raise HTTPException(status_code=404, detail="CRM contact list not found")
    statement = select(CrmPropertyContactClaim).where(
        CrmPropertyContactClaim.organization_id == organization_id,
        CrmPropertyContactClaim.list_id == list_id,
    )
    if search:
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                CrmPropertyContactClaim.contact_name.ilike(term),
                CrmPropertyContactClaim.building_name.ilike(term),
                CrmPropertyContactClaim.project_name.ilike(term),
                CrmPropertyContactClaim.unit_number.ilike(term),
            )
        )
    all_result = await db.exec(statement)
    matching_groups = _dedupe_claims(list(all_result.all()))
    if status:
        matching_groups = [
            group
            for group in matching_groups
            if max(group, key=_claim_preference).ownership_status == status
        ]
    visible = matching_groups[offset : offset + limit]
    all_list_result = await db.exec(
        select(CrmPropertyContactClaim).where(
            CrmPropertyContactClaim.organization_id == organization_id,
            CrmPropertyContactClaim.list_id == list_id,
        )
    )
    all_list_claims = list(all_list_result.all())
    return CrmContactListDetail(
        list=_list_summary(contact_list, all_list_claims),
        contacts=[_claim_response(max(group, key=_claim_preference), group) for group in visible],
        total=len(matching_groups),
        limit=limit,
        offset=offset,
    )


async def list_lead_imported_contacts(
    db: AsyncSession,
    *,
    lead_id: str,
    organization_id: str,
) -> list[CrmLeadImportedContact]:
    result = await db.exec(
        select(CrmPropertyContactClaim, CrmContactList)
        .join(CrmContactList, CrmContactList.id == CrmPropertyContactClaim.list_id)
        .where(
            CrmPropertyContactClaim.organization_id == organization_id,
            CrmPropertyContactClaim.lead_id == lead_id,
        )
        .order_by(CrmPropertyContactClaim.confidence_score.desc())
    )
    rows = list(result.all())
    grouped: dict[tuple[str, str], list[tuple[CrmPropertyContactClaim, CrmContactList]]] = {}
    for claim, contact_list in rows:
        grouped.setdefault(
            (_claim_owner_key(claim), _claim_property_key(claim)),
            [],
        ).append((claim, contact_list))

    all_claims_result = await db.exec(
        select(CrmPropertyContactClaim).where(
            CrmPropertyContactClaim.organization_id == organization_id,
        )
    )
    property_counts: dict[str, int] = {}
    for group in _dedupe_claims(list(all_claims_result.all())):
        owner_key = _claim_owner_key(max(group, key=_claim_preference))
        property_counts[owner_key] = property_counts.get(owner_key, 0) + 1

    contacts: list[CrmLeadImportedContact] = []
    for group_rows in grouped.values():
        claim_group = [claim for claim, _ in group_rows]
        claim = max(claim_group, key=_claim_preference)
        contact_list = next(
            contact_list for candidate, contact_list in group_rows if candidate.id == claim.id
        )
        if claim.id is None or contact_list.id is None:
            continue
        owner_key = _claim_owner_key(claim)
        contacts.append(
            CrmLeadImportedContact(
                claim_id=claim.id,
                list_id=contact_list.id,
                list_name=contact_list.name,
                contact_name=claim.contact_name,
                phone_primary=claim.phone_primary,
                phone_alternate=claim.phone_alternate,
                email_primary=claim.email_primary,
                ownership_status=claim.ownership_status,  # type: ignore[arg-type]
                confidence_score=claim.confidence_score,
                match_reason=claim.match_reason,
                source_sheet=claim.source_sheet,
                imported_at=claim.created_at,
                owner_key=owner_key,
                duplicate_count=_claim_duplicate_count(claim_group),
                property_count=property_counts.get(owner_key, 1),
                source_lists=sorted({item.name for _, item in group_rows}),
            )
        )
    contacts.sort(key=lambda item: (item.confidence_score, item.property_count), reverse=True)
    return contacts


def _group_claim_rows(
    rows: list[tuple[CrmPropertyContactClaim, CrmContactList]],
) -> dict[str, list[list[tuple[CrmPropertyContactClaim, CrmContactList]]]]:
    properties: dict[
        tuple[str, str],
        list[tuple[CrmPropertyContactClaim, CrmContactList]],
    ] = {}
    for claim, contact_list in rows:
        properties.setdefault(
            (_claim_owner_key(claim), _claim_property_key(claim)),
            [],
        ).append((claim, contact_list))
    owners: dict[str, list[list[tuple[CrmPropertyContactClaim, CrmContactList]]]] = {}
    for (owner_key, _), property_rows in properties.items():
        owners.setdefault(owner_key, []).append(property_rows)
    return owners


def _is_rental_ready_claim(claim: CrmPropertyContactClaim) -> bool:
    return bool(claim.lead_id) and claim.ownership_status in {
        "verified_current_owner",
        "probable_current_owner",
    }


def _property_from_rows(
    rows: list[tuple[CrmPropertyContactClaim, CrmContactList]],
) -> CrmOwnerProperty:
    claims = [claim for claim, _ in rows]
    best = max(claims, key=_claim_preference)
    return CrmOwnerProperty(
        property_key=_claim_property_key(best),
        area_name=best.area_name,
        project_name=best.project_name,
        building_name=best.building_name,
        unit_number=best.unit_number,
        property_type=best.property_type,
        ownership_status=best.ownership_status,  # type: ignore[arg-type]
        confidence_score=best.confidence_score,
        match_reason=best.match_reason,
        lead_id=best.lead_id,
        unit_candidate_key=best.unit_candidate_key,
        latest_sale_date=best.latest_sale_date,
        latest_sale_price_aed=best.latest_sale_price_aed,
        later_sale_date=best.later_sale_date,
        lease_end=best.lease_end,
        annual_rent_aed=best.annual_rent_aed,
        duplicate_count=_claim_duplicate_count(claims),
        source_lists=sorted({contact_list.name for _, contact_list in rows}),
        source_rows=_claim_source_rows(claims),
    )


def _owner_profile(
    owner_key: str,
    property_groups: list[list[tuple[CrmPropertyContactClaim, CrmContactList]]],
) -> CrmOwnerProfile:
    claims = [claim for group in property_groups for claim, _ in group]
    best = max(claims, key=_claim_preference)
    properties = [_property_from_rows(group) for group in property_groups]
    properties.sort(
        key=lambda item: (
            1 if item.lead_id else 0,
            item.confidence_score,
            -(item.lease_end.toordinal() if item.lease_end else 0),
        ),
        reverse=True,
    )
    phones = list(
        dict.fromkeys(
            value
            for claim in claims
            for value in (claim.phone_primary, claim.phone_alternate)
            if value
        )
    )
    emails = list(dict.fromkeys(claim.email_primary for claim in claims if claim.email_primary))
    rental_properties = [item for item in properties if item.lead_id]
    contact_ready = [
        item
        for item in properties
        if item.lead_id
        and item.ownership_status in {"verified_current_owner", "probable_current_owner"}
    ]
    lease_dates = [item.lease_end for item in rental_properties if item.lease_end]
    return CrmOwnerProfile(
        owner_key=owner_key,
        contact_name=best.contact_name,
        phone_primary=phones[0] if phones else None,
        phone_alternate=phones[1] if len(phones) > 1 else None,
        email_primary=emails[0] if emails else None,
        highest_ownership_status=best.ownership_status,  # type: ignore[arg-type]
        highest_confidence_score=best.confidence_score,
        property_count=len(properties),
        rental_linked_count=len(rental_properties),
        contact_ready_count=len(contact_ready),
        annual_rent_aed=sum(item.annual_rent_aed or 0 for item in rental_properties),
        next_lease_end=min(lease_dates) if lease_dates else None,
        properties=properties,
    )


def _profile_matches_scope(profile: CrmOwnerProfile, scope: str) -> bool:
    ready_properties = [
        item
        for item in profile.properties
        if item.lead_id
        and item.ownership_status in {"verified_current_owner", "probable_current_owner"}
    ]
    if scope == "rental_ready":
        return bool(ready_properties)
    if scope == "registry":
        return len(ready_properties) < len(profile.properties)
    return True


def _profile_for_scope(profile: CrmOwnerProfile, scope: str) -> CrmOwnerProfile:
    if scope == "all":
        return profile
    properties = [
        item
        for item in profile.properties
        if (
            item.lead_id
            and item.ownership_status in {"verified_current_owner", "probable_current_owner"}
        )
        == (scope == "rental_ready")
    ]
    if not properties:
        return profile
    best = max(
        properties,
        key=lambda item: (
            _OWNERSHIP_PRIORITY.get(item.ownership_status, 0),
            item.confidence_score,
        ),
    )
    rental_properties = [item for item in properties if item.lead_id]
    lease_dates = [item.lease_end for item in rental_properties if item.lease_end]
    return profile.model_copy(
        update={
            "highest_ownership_status": best.ownership_status,
            "highest_confidence_score": best.confidence_score,
            "property_count": len(properties),
            "rental_linked_count": len(rental_properties),
            "contact_ready_count": sum(
                bool(item.lead_id)
                and item.ownership_status in {"verified_current_owner", "probable_current_owner"}
                for item in properties
            ),
            "annual_rent_aed": sum(item.annual_rent_aed or 0 for item in rental_properties),
            "next_lease_end": min(lease_dates) if lease_dates else None,
            "properties": properties,
        }
    )


async def _all_owner_profiles(
    db: AsyncSession,
    *,
    organization_id: str,
) -> list[CrmOwnerProfile]:
    result = await db.exec(
        select(CrmPropertyContactClaim, CrmContactList)
        .join(CrmContactList, CrmContactList.id == CrmPropertyContactClaim.list_id)
        .where(CrmPropertyContactClaim.organization_id == organization_id)
    )
    owners = _group_claim_rows(list(result.all()))
    return [
        _owner_profile(owner_key, property_groups) for owner_key, property_groups in owners.items()
    ]


def _owner_registry_summary(
    profiles: list[CrmOwnerProfile],
) -> CrmOwnerRegistrySummary:
    return CrmOwnerRegistrySummary(
        rental_owner_profiles=sum(
            any(
                item.lead_id
                and item.ownership_status in {"verified_current_owner", "probable_current_owner"}
                for item in profile.properties
            )
            for profile in profiles
        ),
        registry_owner_profiles=sum(
            any(
                not (
                    item.lead_id
                    and item.ownership_status
                    in {"verified_current_owner", "probable_current_owner"}
                )
                and item.ownership_status != "former_owner"
                for item in profile.properties
            )
            for profile in profiles
        ),
        prior_owner_profiles=sum(
            any(item.ownership_status == "former_owner" for item in profile.properties)
            for profile in profiles
        ),
        needs_review_profiles=sum(
            any(
                item.ownership_status
                in {"unit_linked_unverified", "conflicting_claim", "unmatched"}
                for item in profile.properties
            )
            for profile in profiles
        ),
        multi_property_owners=sum(profile.property_count > 1 for profile in profiles),
    )


def _owner_scope_clause(scope: str, alias: str = "p") -> str:
    ready = (
        f"{alias}.lead_id IS NOT NULL AND "
        f"{alias}.ownership_status IN "
        "('verified_current_owner', 'probable_current_owner')"
    )
    if scope == "rental_ready":
        return ready
    if scope == "prior_owners":
        return f"{alias}.ownership_status = 'former_owner'"
    if scope == "registry":
        return f"NOT ({ready}) AND {alias}.ownership_status <> 'former_owner'"
    return "TRUE"


def _owner_filter_sql(
    *,
    scope: str,
    status: str | None,
    search: str | None,
    lease_window: str | None = None,
    min_rent_aed: int | None = None,
    max_rent_aed: int | None = None,
    min_value_aed: int | None = None,
    max_value_aed: int | None = None,
    alias: str = "p",
) -> tuple[str, dict[str, Any]]:
    clauses = [_owner_scope_clause(scope, alias)]
    parameters: dict[str, Any] = {}
    if status:
        clauses.append(f"{alias}.ownership_status = :owner_status")
        parameters["owner_status"] = status
    if search:
        clauses.append(
            "lower(concat_ws(' ', "
            f"{alias}.contact_name, {alias}.phone_primary, "
            f"{alias}.phone_alternate, {alias}.email_primary, "
            f"{alias}.building_name, {alias}.project_name, "
            f"{alias}.area_name, {alias}.unit_number"
            ")) LIKE :owner_search"
        )
        parameters["owner_search"] = f"%{search.casefold().strip()}%"
    if lease_window == "expired":
        clauses.append(f"{alias}.lease_end < CURRENT_DATE")
    elif lease_window in {"expiring_30", "expiring_60", "expiring_90"}:
        lower_days, upper_days = {
            "expiring_30": (0, 30),
            "expiring_60": (30, 60),
            "expiring_90": (60, 90),
        }[lease_window]
        clauses.append(
            f"{alias}.lease_end > CURRENT_DATE + make_interval(days => :lease_lower_days)"
        )
        clauses.append(
            f"{alias}.lease_end <= CURRENT_DATE + make_interval(days => :lease_upper_days)"
        )
        parameters["lease_lower_days"] = lower_days
        parameters["lease_upper_days"] = upper_days
    if min_rent_aed is not None:
        clauses.append(f"{alias}.annual_rent_aed >= :owner_min_rent")
        parameters["owner_min_rent"] = min_rent_aed
    if max_rent_aed is not None:
        clauses.append(f"{alias}.annual_rent_aed <= :owner_max_rent")
        parameters["owner_max_rent"] = max_rent_aed
    if min_value_aed is not None:
        clauses.append(f"{alias}.latest_sale_price_aed >= :owner_min_value")
        parameters["owner_min_value"] = min_value_aed
    if max_value_aed is not None:
        clauses.append(f"{alias}.latest_sale_price_aed <= :owner_max_value")
        parameters["owner_max_value"] = max_value_aed
    return " AND ".join(f"({clause})" for clause in clauses), parameters


async def _owner_registry_summary_sql(
    db: AsyncSession,
    *,
    organization_id: str,
    list_id: int | None,
) -> CrmOwnerRegistrySummary:
    cache_key = (organization_id, list_id)
    cached = _owner_summary_cache.get(cache_key)
    if cached and monotonic() - cached[0] < _OWNER_SUMMARY_CACHE_TTL_SECONDS:
        return cached[1]
    statement = text(
        _OWNER_REGISTRY_BASE_SQL
        + """
        , profile_rollup AS (
            SELECT
                owner_key_sql,
                count(*) AS property_count,
                count(*) FILTER (
                    WHERE lead_id IS NOT NULL
                    AND ownership_status IN (
                        'verified_current_owner',
                        'probable_current_owner'
                    )
                ) AS rental_ready_count,
                count(*) FILTER (
                    WHERE NOT (
                        lead_id IS NOT NULL
                        AND ownership_status IN (
                            'verified_current_owner',
                            'probable_current_owner'
                        )
                    )
                    AND ownership_status <> 'former_owner'
                ) AS registry_count,
                count(*) FILTER (
                    WHERE ownership_status = 'former_owner'
                ) AS prior_count,
                count(*) FILTER (
                    WHERE ownership_status IN (
                        'unit_linked_unverified',
                        'conflicting_claim',
                        'unmatched'
                    )
                ) AS review_count
            FROM properties
            GROUP BY owner_key_sql
        )
        SELECT
            count(*) FILTER (WHERE rental_ready_count > 0)
                AS rental_owner_profiles,
            count(*) FILTER (WHERE registry_count > 0)
                AS registry_owner_profiles,
            count(*) FILTER (WHERE prior_count > 0)
                AS prior_owner_profiles,
            count(*) FILTER (WHERE review_count > 0)
                AS needs_review_profiles,
            count(*) FILTER (WHERE property_count > 1)
                AS multi_property_owners
        FROM profile_rollup
        """
    )
    row = (
        await db.exec(
            statement,
            params={"organization_id": organization_id, "owner_list_id": list_id},
        )
    ).mappings().one()
    summary = CrmOwnerRegistrySummary(
        rental_owner_profiles=int(row["rental_owner_profiles"] or 0),
        registry_owner_profiles=int(row["registry_owner_profiles"] or 0),
        prior_owner_profiles=int(row["prior_owner_profiles"] or 0),
        needs_review_profiles=int(row["needs_review_profiles"] or 0),
        multi_property_owners=int(row["multi_property_owners"] or 0),
    )
    _owner_summary_cache[cache_key] = (monotonic(), summary)
    return summary


async def _owner_page_keys_sql(
    db: AsyncSession,
    *,
    organization_id: str,
    list_id: int | None,
    scope: str,
    status: str | None,
    search: str | None,
    lease_window: str | None,
    portfolio_only: bool,
    min_rent_aed: int | None,
    max_rent_aed: int | None,
    min_value_aed: int | None,
    max_value_aed: int | None,
    limit: int,
    offset: int,
) -> tuple[list[str], int]:
    where_sql, parameters = _owner_filter_sql(
        scope=scope,
        status=status,
        search=search,
        lease_window=lease_window,
        min_rent_aed=min_rent_aed,
        max_rent_aed=max_rent_aed,
        min_value_aed=min_value_aed,
        max_value_aed=max_value_aed,
    )
    statement = text(
        _OWNER_REGISTRY_BASE_SQL
        + f"""
        , scoped_properties AS (
            SELECT p.* FROM properties p WHERE {where_sql}
        ),
        profile_rollup AS (
            SELECT
                owner_key_sql,
                count(*) AS property_count,
                count(*) FILTER (WHERE lead_id IS NOT NULL)
                    AS rental_linked_count,
                count(*) FILTER (
                    WHERE lead_id IS NOT NULL
                    AND ownership_status IN (
                        'verified_current_owner',
                        'probable_current_owner'
                    )
                ) AS contact_ready_count,
                max(confidence_score) AS highest_confidence_score,
                min(lease_end) FILTER (WHERE lease_end IS NOT NULL)
                    AS next_lease_end
            FROM scoped_properties
            GROUP BY owner_key_sql
        )
        SELECT
            owner_key_sql,
            count(*) OVER () AS total_profiles
        FROM profile_rollup
        WHERE (NOT :portfolio_only OR property_count > 1)
        ORDER BY
            contact_ready_count DESC,
            property_count DESC,
            highest_confidence_score DESC,
            next_lease_end ASC NULLS LAST,
            owner_key_sql
        LIMIT :owner_limit OFFSET :owner_offset
        """
    )
    parameters.update(
        {
            "organization_id": organization_id,
            "owner_list_id": list_id,
            "portfolio_only": portfolio_only,
            "owner_limit": limit,
            "owner_offset": offset,
        }
    )
    rows = (await db.exec(statement, params=parameters)).mappings().all()
    return (
        [str(row["owner_key_sql"]) for row in rows],
        int(rows[0]["total_profiles"]) if rows else 0,
    )


async def _owner_properties_sql(
    db: AsyncSession,
    *,
    organization_id: str,
    list_id: int | None,
    owner_keys: list[str],
    scope: str,
    status: str | None = None,
    search: str | None = None,
    lease_window: str | None = None,
    min_rent_aed: int | None = None,
    max_rent_aed: int | None = None,
    min_value_aed: int | None = None,
    max_value_aed: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if not owner_keys:
        return {}
    where_sql, parameters = _owner_filter_sql(
        scope=scope,
        status=status,
        search=search,
        lease_window=lease_window,
        min_rent_aed=min_rent_aed,
        max_rent_aed=max_rent_aed,
        min_value_aed=min_value_aed,
        max_value_aed=max_value_aed,
    )
    statement = text(
        _OWNER_REGISTRY_BASE_SQL
        + f"""
        , limited_properties AS (
            SELECT DISTINCT ON (owner_key_sql, property_key_sql)
                *
            FROM base
            WHERE owner_key_sql = ANY(:owner_keys)
            ORDER BY
                owner_key_sql,
                property_key_sql,
                status_rank DESC,
                confidence_score DESC,
                transaction_date DESC NULLS LAST
        ),
        limited_source_aggregation AS (
            SELECT
                c.owner_key AS owner_key_sql,
                c.property_key AS property_key_sql,
                count(*) AS duplicate_count,
                array_agg(DISTINCT l.name ORDER BY l.name)
                    AS source_lists,
                array_agg(
                    DISTINCT c.source_sheet || ':' || c.source_row_number::text
                    ORDER BY c.source_sheet || ':' || c.source_row_number::text
                ) AS source_rows
            FROM crm_property_contact_claims c
            INNER JOIN crm_contact_lists l ON l.id = c.list_id
            WHERE c.organization_id = :organization_id
              AND (
                CAST(:owner_list_id AS INTEGER) IS NULL
                OR c.list_id = CAST(:owner_list_id AS INTEGER)
              )
              AND c.owner_key = ANY(:owner_keys)
            GROUP BY c.owner_key, c.property_key
        ),
        scoped_properties AS (
            SELECT p.* FROM limited_properties p WHERE {where_sql}
        )
        SELECT
            p.*,
            a.duplicate_count,
            a.source_lists,
            a.source_rows
        FROM scoped_properties p
        INNER JOIN limited_source_aggregation a
            ON a.owner_key_sql = p.owner_key_sql
            AND a.property_key_sql = p.property_key_sql
        WHERE p.owner_key_sql = ANY(:owner_keys)
        ORDER BY
            p.owner_key_sql,
            p.status_rank DESC,
            p.confidence_score DESC,
            p.lease_end ASC NULLS LAST
        """
    )
    parameters.update(
        {
            "organization_id": organization_id,
            "owner_list_id": list_id,
            "owner_keys": owner_keys,
        }
    )
    rows = (await db.exec(statement, params=parameters)).mappings().all()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["owner_key_sql"]), []).append(dict(row))
    return grouped


def _sql_owner_property(row: dict[str, Any]) -> CrmOwnerProperty:
    return CrmOwnerProperty(
        property_key=str(row["property_key_sql"]),
        area_name=str(row["area_name"] or ""),
        project_name=str(row["project_name"] or ""),
        building_name=str(row["building_name"] or ""),
        unit_number=str(row["unit_number"] or ""),
        property_type=str(row["property_type"] or ""),
        ownership_status=str(row["ownership_status"]),  # type: ignore[arg-type]
        confidence_score=int(row["confidence_score"] or 0),
        match_reason=str(row["match_reason"] or ""),
        lead_id=str(row["lead_id"]) if row["lead_id"] else None,
        unit_candidate_key=(str(row["unit_candidate_key"]) if row["unit_candidate_key"] else None),
        latest_sale_date=row["latest_sale_date"],
        latest_sale_price_aed=(
            int(row["latest_sale_price_aed"]) if row["latest_sale_price_aed"] else None
        ),
        later_sale_date=row["later_sale_date"],
        lease_end=row["lease_end"],
        annual_rent_aed=(int(row["annual_rent_aed"]) if row["annual_rent_aed"] else None),
        duplicate_count=int(row["duplicate_count"] or 1),
        source_lists=list(row["source_lists"] or []),
        source_rows=list(row["source_rows"] or []),
    )


def _sql_owner_profile(
    owner_key: str,
    rows: list[dict[str, Any]],
) -> CrmOwnerProfile:
    best = max(
        rows,
        key=lambda row: (
            int(row["status_rank"] or 0),
            int(row["confidence_score"] or 0),
        ),
    )
    properties = [_sql_owner_property(row) for row in rows]
    phones = list(
        dict.fromkeys(
            str(value)
            for row in rows
            for value in (row["phone_primary"], row["phone_alternate"])
            if value
        )
    )
    emails = list(dict.fromkeys(str(row["email_primary"]) for row in rows if row["email_primary"]))
    rental_properties = [item for item in properties if item.lead_id]
    contact_ready = [
        item
        for item in properties
        if item.lead_id
        and item.ownership_status in {"verified_current_owner", "probable_current_owner"}
    ]
    lease_dates = [item.lease_end for item in rental_properties if item.lease_end]
    return CrmOwnerProfile(
        owner_key=owner_key,
        contact_name=str(best["contact_name"]),
        phone_primary=phones[0] if phones else None,
        phone_alternate=phones[1] if len(phones) > 1 else None,
        email_primary=emails[0] if emails else None,
        highest_ownership_status=str(best["ownership_status"]),  # type: ignore[arg-type]
        highest_confidence_score=int(best["confidence_score"] or 0),
        property_count=len(properties),
        rental_linked_count=len(rental_properties),
        contact_ready_count=len(contact_ready),
        annual_rent_aed=sum(item.annual_rent_aed or 0 for item in rental_properties),
        next_lease_end=min(lease_dates) if lease_dates else None,
        properties=properties,
    )


async def get_owner_registry(
    db: AsyncSession,
    *,
    organization_id: str,
    list_id: int | None,
    scope: str,
    status: str | None,
    search: str | None,
    lease_window: str | None,
    portfolio_only: bool,
    min_rent_aed: int | None,
    max_rent_aed: int | None,
    min_value_aed: int | None,
    max_value_aed: int | None,
    limit: int,
    offset: int,
) -> CrmOwnerRegistryResponse:
    summary = await _owner_registry_summary_sql(
        db,
        organization_id=organization_id,
        list_id=list_id,
    )
    owner_keys, total = await _owner_page_keys_sql(
        db,
        organization_id=organization_id,
        list_id=list_id,
        scope=scope,
        status=status,
        search=search,
        lease_window=lease_window,
        portfolio_only=portfolio_only,
        min_rent_aed=min_rent_aed,
        max_rent_aed=max_rent_aed,
        min_value_aed=min_value_aed,
        max_value_aed=max_value_aed,
        limit=limit,
        offset=offset,
    )
    property_rows = await _owner_properties_sql(
        db,
        organization_id=organization_id,
        list_id=list_id,
        owner_keys=owner_keys,
        scope=scope,
        status=status,
        search=search,
        lease_window=lease_window,
        min_rent_aed=min_rent_aed,
        max_rent_aed=max_rent_aed,
        min_value_aed=min_value_aed,
        max_value_aed=max_value_aed,
    )
    profiles = [
        _sql_owner_profile(owner_key, property_rows[owner_key])
        for owner_key in owner_keys
        if owner_key in property_rows
    ]
    return CrmOwnerRegistryResponse(
        scope=scope,  # type: ignore[arg-type]
        owners=profiles,
        total=total,
        limit=limit,
        offset=offset,
        summary=summary,
    )


async def get_owner_profile(
    db: AsyncSession,
    *,
    organization_id: str,
    owner_key: str,
) -> CrmOwnerProfile:
    property_rows = await _owner_properties_sql(
        db,
        organization_id=organization_id,
        list_id=None,
        owner_keys=[owner_key],
        scope="all",
    )
    rows = property_rows.get(owner_key)
    if not rows:
        raise HTTPException(status_code=404, detail="Owner profile not found")
    return _sql_owner_profile(owner_key, rows)


def _owner_workspace_summaries(
    workspaces: list[CrmOwnerWorkspace],
    notes: list[CrmOwnerNote],
) -> list[CrmOwnerWorkspaceSummary]:
    notes_by_workspace: dict[int, list[CrmOwnerNote]] = {}
    for note in notes:
        notes_by_workspace.setdefault(note.workspace_id, []).append(note)
    summaries: list[CrmOwnerWorkspaceSummary] = []
    for workspace in workspaces:
        workspace_notes = notes_by_workspace.get(workspace.id or 0, [])
        workspace_notes.sort(key=lambda item: item.created_at, reverse=True)
        summaries.append(
            CrmOwnerWorkspaceSummary(
                owner_key=workspace.owner_key,
                pipeline_status=workspace.pipeline_status,  # type: ignore[arg-type]
                highlight_color=workspace.highlight_color,  # type: ignore[arg-type]
                next_follow_up=workspace.next_follow_up,
                tags=list(workspace.tags or []),
                note_count=len(workspace_notes),
                last_note=workspace_notes[0].body if workspace_notes else None,
                updated_at=workspace.updated_at,
            )
        )
    summaries.sort(key=lambda item: item.updated_at, reverse=True)
    return summaries


async def list_owner_workspaces(
    db: AsyncSession,
    *,
    user_id: str,
    organization_id: str,
) -> list[CrmOwnerWorkspaceSummary]:
    workspace_result = await db.exec(
        select(CrmOwnerWorkspace).where(
            CrmOwnerWorkspace.user_id == user_id,
            CrmOwnerWorkspace.organization_id == organization_id,
        )
    )
    workspaces = list(workspace_result.all())
    if not workspaces:
        return []
    workspace_ids = [item.id for item in workspaces if item.id is not None]
    note_result = await db.exec(
        select(CrmOwnerNote).where(
            CrmOwnerNote.user_id == user_id,
            CrmOwnerNote.organization_id == organization_id,
            CrmOwnerNote.workspace_id.in_(workspace_ids),  # type: ignore[union-attr]
        )
    )
    return _owner_workspace_summaries(workspaces, list(note_result.all()))


async def bulk_update_owner_workspaces(
    db: AsyncSession,
    *,
    payload: CrmOwnerBulkUpdate,
    user_id: str,
    organization_id: str,
) -> list[CrmOwnerWorkspaceSummary]:
    owner_keys = sorted({value.strip() for value in payload.owner_keys if value.strip()})
    if not owner_keys:
        raise HTTPException(status_code=422, detail="Select at least one owner")
    if not any((payload.pipeline_status, payload.highlight_color, payload.note)):
        raise HTTPException(status_code=422, detail="Choose a CRM update to apply")

    claim_result = await db.exec(
        select(CrmPropertyContactClaim.owner_key).where(
            CrmPropertyContactClaim.organization_id == organization_id,
            CrmPropertyContactClaim.owner_key.in_(owner_keys),  # type: ignore[union-attr]
        )
    )
    valid_keys = set(claim_result.all())
    owner_keys = [key for key in owner_keys if key in valid_keys]
    if not owner_keys:
        raise HTTPException(status_code=404, detail="Selected owners were not found")

    workspace_result = await db.exec(
        select(CrmOwnerWorkspace).where(
            CrmOwnerWorkspace.user_id == user_id,
            CrmOwnerWorkspace.organization_id == organization_id,
            CrmOwnerWorkspace.owner_key.in_(owner_keys),  # type: ignore[union-attr]
        )
    )
    existing = {workspace.owner_key: workspace for workspace in workspace_result.all()}
    now = _utcnow()
    touched: list[CrmOwnerWorkspace] = []
    note_body = (payload.note or "").strip()
    for owner_key in owner_keys:
        workspace = existing.get(owner_key)
        if workspace is None:
            workspace = CrmOwnerWorkspace(
                user_id=user_id,
                organization_id=organization_id,
                owner_key=owner_key,
                pipeline_status="new",
                highlight_color="none",
                tags=[],
                created_at=now,
                updated_at=now,
            )
        if payload.pipeline_status is not None:
            workspace.pipeline_status = payload.pipeline_status
        if payload.highlight_color is not None:
            workspace.highlight_color = payload.highlight_color
        workspace.updated_at = now
        db.add(workspace)
        await db.flush()
        if note_body and workspace.id is not None:
            db.add(
                CrmOwnerNote(
                    workspace_id=workspace.id,
                    user_id=user_id,
                    organization_id=organization_id,
                    body=note_body,
                    created_at=now,
                    updated_at=now,
                )
            )
        touched.append(workspace)
    await db.commit()
    return await list_owner_workspaces(
        db,
        user_id=user_id,
        organization_id=organization_id,
    )
