from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import openpyxl
from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, exists, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.clickhouse.client import query
from app.config import settings
from app.crm.import_models import CrmPropertyContactClaim
from app.crm.import_service import _normalize_email, _normalize_phone
from app.crm.inbound_models import (
    CrmInboundContact,
    CrmInboundEnquiry,
    CrmInboundImport,
    CrmInboundMatch,
    CrmInboundNote,
    InboundContactResponse,
    InboundEnquiryCreate,
    InboundEnquiryListResponse,
    InboundEnquiryResponse,
    InboundEnquiryUpdate,
    InboundImportResponse,
    InboundImportSummary,
    InboundMatchesResponse,
    InboundMatchResponse,
    InboundNoteResponse,
)
from app.listings.service import list_listings_from_clickhouse

_MAX_FILE_BYTES = 50 * 1024 * 1024
_ALGORITHM_VERSION = "inbound-v1"
_LISTING_MAX_AGE_HOURS = 48
_NON_KEY = re.compile(r"[^a-z0-9]+")
_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?971|0)?[\s().-]*5\d(?:[\s().-]*\d){7}(?!\d)")
_ID_RE = re.compile(r"\b\d{9,18}\b")

_ALIASES: dict[str, set[str]] = {
    "full_name": {"name", "fullname", "leadname", "contactname", "customername"},
    "first_name": {"firstname", "first"},
    "last_name": {"lastname", "surname", "last"},
    "phone": {"phone", "phonenumber", "mobile", "mobilenumber", "telephone"},
    "email": {"email", "emailaddress"},
    "whatsapp": {"whatsapp", "whatsappnumber"},
    "intent": {"intent", "leadtype", "enquirytype", "transactiontype", "lookingfor"},
    "source": {"source", "leadsource", "channel", "platform"},
    "campaign": {"campaign", "campaignname", "formname", "adname", "adsetname"},
    "source_lead_id": {"leadid", "sourceleadid", "recordid", "submissionid"},
    "notes": {"notes", "message", "comments", "requirements", "description", "enquiry"},
    "locations": {"area", "location", "community", "project", "preferredlocation"},
    "property_type": {"propertytype", "unittype", "assettype"},
    "bedrooms": {"bedrooms", "beds", "bedroom"},
    "budget_min": {"budgetmin", "minbudget", "minimumprice"},
    "budget_max": {"budget", "budgetmax", "maxbudget", "maximumprice", "price"},
    "timeline": {"timeline", "movingdate", "purchasedate", "when", "urgency"},
    "financing": {"financing", "paymentmethod", "mortgage", "finance"},
    "language": {"language", "preferredlanguage"},
    "consent": {"consent", "marketingconsent", "optin", "permissiontocontact"},
    "created_at": {"createdat", "createdtime", "submissiondate", "leaddate", "date"},
    "unit_number": {"unit", "unitnumber", "villanumber"},
    "building": {"building", "tower", "buildingname"},
}

_KNOWN_LOCATIONS = (
    "JBR",
    "Dubai Marina",
    "Downtown Dubai",
    "Business Bay",
    "Palm Jumeirah",
    "Jumeirah Village Circle",
    "JVC",
    "Dubai Hills",
    "Arabian Ranches",
    "Tilal Al Ghaf",
    "Damac Hills",
    "Dubai Creek Harbour",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _token(value: Any) -> str:
    return _NON_KEY.sub("", str(value or "").strip().lower())


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _amount(value: Any) -> int | None:
    if isinstance(value, int | float) and value > 0:
        return int(value)
    raw = _text(value).lower().replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(m|mn|million|k|thousand)?", raw)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2) or ""
    if suffix in {"m", "mn", "million"}:
        number *= 1_000_000
    elif suffix in {"k", "thousand"}:
        number *= 1_000
    return int(number) if number > 0 else None


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    raw = _text(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return _utcnow()


def _normalize_intent(value: Any, notes: str = "") -> str | None:
    raw = f"{_text(value)} {notes}".lower()
    if any(word in raw for word in ("landlord", "list for rent", "rent out", "to let")):
        return "let"
    if any(word in raw for word in ("seller", "sell my", "want to sell", "valuation")):
        return "sell"
    if any(word in raw for word in ("tenant", "looking to rent", "for rent", "lease")):
        return "rent"
    if any(word in raw for word in ("buyer", "looking to buy", "purchase", "for sale")):
        return "buy"
    return None


def _redact(text: str, contact_values: list[str]) -> str:
    redacted = text
    for value in sorted((v for v in contact_values if len(v.strip()) >= 3), key=len, reverse=True):
        redacted = re.sub(re.escape(value), "[REDACTED]", redacted, flags=re.IGNORECASE)
    redacted = _EMAIL_RE.sub("[EMAIL]", redacted)
    redacted = _PHONE_RE.sub("[PHONE]", redacted)
    return _ID_RE.sub("[ID]", redacted)[:2_000]


def _deterministic_criteria(row: dict[str, Any], notes: str) -> dict[str, Any]:
    criteria: dict[str, Any] = {}
    location_value = _text(row.get("locations"))
    locations = [item.strip() for item in re.split(r"[,;/|]", location_value) if item.strip()]
    if not locations:
        lowered = notes.lower()
        locations = [location for location in _KNOWN_LOCATIONS if location.lower() in lowered]
    if locations:
        criteria["locations"] = list(dict.fromkeys(locations))

    bedroom_value = _text(row.get("bedrooms"))
    bedroom_match = re.search(r"(studio|\d+)\s*(?:bed|br|bedroom)?", bedroom_value, re.I)
    if not bedroom_match:
        bedroom_match = re.search(r"(studio|\d+)\s*(?:bed|br|bedroom)s?", notes, re.I)
    if bedroom_match:
        bedrooms = 0 if bedroom_match.group(1).lower() == "studio" else int(bedroom_match.group(1))
        criteria["bedrooms_min"] = bedrooms
        criteria["bedrooms_max"] = bedrooms

    minimum = _amount(row.get("budget_min"))
    maximum = _amount(row.get("budget_max"))
    if maximum is None:
        budget_match = re.search(
            r"(?:budget|around|up to|max(?:imum)?)[^\d]{0,12}(\d+(?:\.\d+)?\s*(?:m|mn|million|k)?)",
            notes,
            re.I,
        )
        maximum = _amount(budget_match.group(1)) if budget_match else None
    if minimum:
        criteria["budget_min_aed"] = minimum
    if maximum:
        criteria["budget_max_aed"] = maximum
    if property_type := _text(row.get("property_type")):
        criteria["property_type"] = property_type
    if timeline := _text(row.get("timeline")):
        criteria["timeline"] = timeline
    if financing := _text(row.get("financing")):
        criteria["financing"] = financing
    if unit := _text(row.get("unit_number")):
        criteria["unit_number"] = unit
    if building := _text(row.get("building")):
        criteria["building"] = building
    return criteria


async def _ai_extract(notes: str, known: dict[str, Any]) -> tuple[dict[str, Any], float, list[str]]:
    if not notes or not settings.OPENROUTER_API_KEY:
        return {}, 0.0, []
    prompt = {
        "task": "Extract a Dubai real-estate enquiry from redacted text.",
        "text": notes,
        "already_extracted": known,
        "allowed_intents": ["buy", "rent", "sell", "let"],
        "output": {
            "intent": "string or null",
            "criteria": {
                "locations": ["strings"],
                "property_type": "string or null",
                "bedrooms_min": "integer or null",
                "bedrooms_max": "integer or null",
                "budget_min_aed": "integer or null",
                "budget_max_aed": "integer or null",
                "timeline": "string or null",
                "financing": "string or null",
            },
            "strict_fields": ["criteria keys explicitly stated as hard requirements"],
            "confidence": "0 to 1",
        },
        "rules": ["Return JSON only", "Use null for unknown values", "Do not infer identity"],
    }
    try:
        async with httpx.AsyncClient(timeout=25) as client:
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
                            "content": "Extract structured property demand. Never invent missing facts.",
                        },
                        {"role": "user", "content": json.dumps(prompt)},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "max_tokens": 500,
                    "provider": {"zdr": True, "data_collection": "deny"},
                },
            )
            response.raise_for_status()
            payload = json.loads(response.json()["choices"][0]["message"]["content"])
    except Exception:
        return {}, 0.0, []
    criteria = payload.get("criteria") if isinstance(payload.get("criteria"), dict) else {}
    criteria = {key: value for key, value in criteria.items() if value not in (None, "", [])}
    if payload.get("intent"):
        criteria["_intent"] = payload["intent"]
    confidence = float(payload.get("confidence") or 0)
    strict = [str(item) for item in payload.get("strict_fields", []) if item]
    return criteria, max(0.0, min(1.0, confidence)), strict


def _header_mapping(headers: list[Any]) -> dict[str, int]:
    tokens = {_token(header): index for index, header in enumerate(headers) if _text(header)}
    mapping: dict[str, int] = {}
    for canonical, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in tokens:
                mapping[canonical] = tokens[alias]
                break
    return mapping


def _best_header(rows: list[tuple[Any, ...]]) -> tuple[int, tuple[Any, ...], dict[str, int]]:
    """Find the most likely header row in exports with titles or blank preambles."""
    candidates = []
    for index, values in enumerate(rows[:15]):
        mapping = _header_mapping(list(values))
        identity_fields = len({"full_name", "first_name", "phone", "email"} & mapping.keys())
        candidates.append((len(mapping), identity_fields, -index, index, values, mapping))
    if not candidates:
        return 0, (), {}
    _, _, _, index, values, mapping = max(candidates, key=lambda item: item[:3])
    return index, values, mapping


def _file_rows(data: bytes, filename: str) -> tuple[list[tuple[str, int, dict[str, Any]]], dict[str, Any]]:
    rows: list[tuple[str, int, dict[str, Any]]] = []
    mappings: list[dict[str, Any]] = []
    if filename.lower().endswith(".csv"):
        raw = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        header_index, header_values, mapping = _best_header([tuple(row) for row in raw])
        headers = list(header_values)
        for row_number, values in enumerate(raw[header_index + 1 :], start=header_index + 2):
            if any(_text(value) for value in values):
                rows.append((Path(filename).stem, row_number, {key: values[index] if index < len(values) else None for key, index in mapping.items()}))
        mappings.append({"sheet": Path(filename).stem, "header_row": header_index + 1, "field_map": {key: headers[index] for key, index in mapping.items()}})
        return rows, {"sheets": mappings}

    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            preview = list(sheet.iter_rows(min_row=1, max_row=15, values_only=True))
            header_index, header_values, mapping = _best_header(preview)
            mappings.append({"sheet": sheet.title, "header_row": header_index + 1, "field_map": {key: _text(header_values[index]) for key, index in mapping.items()}})
            for row_number, values in enumerate(sheet.iter_rows(min_row=header_index + 2, values_only=True), start=header_index + 2):
                if any(value not in (None, "") for value in values):
                    rows.append((sheet.title, row_number, {key: values[index] if index < len(values) else None for key, index in mapping.items()}))
    finally:
        workbook.close()
    return rows, {"sheets": mappings}


async def _find_or_create_contact(
    db: AsyncSession,
    *,
    organization_id: str,
    full_name: str,
    phone: str | None,
    email: str | None,
    whatsapp: str | None,
    language: str | None,
    consent_status: str,
) -> CrmInboundContact:
    conditions = []
    if phone:
        conditions.append(CrmInboundContact.phone == phone)
    if email:
        conditions.append(CrmInboundContact.email == email)
    existing = None
    if conditions:
        result = await db.exec(
            select(CrmInboundContact).where(
                CrmInboundContact.organization_id == organization_id, or_(*conditions)
            )
        )
        existing = result.first()
    now = _utcnow()
    if existing:
        existing.full_name = full_name or existing.full_name
        existing.phone = phone or existing.phone
        existing.email = email or existing.email
        existing.whatsapp = whatsapp or existing.whatsapp
        existing.preferred_language = language or existing.preferred_language
        existing.updated_at = now
        db.add(existing)
        return existing
    contact = CrmInboundContact(
        organization_id=organization_id,
        full_name=full_name or "Unnamed lead",
        phone=phone,
        email=email,
        whatsapp=whatsapp,
        preferred_language=language,
        consent_status=consent_status,
        created_at=now,
        updated_at=now,
    )
    db.add(contact)
    await db.flush()
    return contact


async def create_inbound_enquiry(
    db: AsyncSession,
    *,
    payload: InboundEnquiryCreate,
    user_id: str,
    organization_id: str,
) -> InboundEnquiryResponse:
    contact = await _find_or_create_contact(
        db,
        organization_id=organization_id,
        full_name=payload.full_name.strip(),
        phone=_normalize_phone(payload.phone),
        email=_normalize_email(payload.email),
        whatsapp=_normalize_phone(payload.whatsapp),
        language=None,
        consent_status=payload.consent_status,
    )
    now = _utcnow()
    enquiry = CrmInboundEnquiry(
        organization_id=organization_id,
        contact_id=contact.id or 0,
        created_by_user_id=user_id,
        assigned_user_id=payload.assigned_user_id or user_id,
        intent=payload.intent,
        status="new",
        source=payload.source,
        campaign=payload.campaign,
        enquiry_date=now,
        criteria=payload.criteria,
        strict_fields=payload.strict_fields,
        raw_notes=payload.notes,
        extraction_confidence=1,
        created_at=now,
        updated_at=now,
    )
    db.add(enquiry)
    await db.commit()
    await db.refresh(enquiry)
    return await _enquiry_response(db, enquiry, contact=contact)


async def process_inbound_import(
    db: AsyncSession,
    *,
    upload: UploadFile,
    name: str,
    user_id: str,
    organization_id: str,
) -> InboundImportResponse:
    filename = Path(upload.filename or "inbound-leads.xlsx").name
    if not filename.lower().endswith((".xlsx", ".csv")):
        raise HTTPException(status_code=415, detail="Upload a CSV or XLSX file")
    data = await upload.read(_MAX_FILE_BYTES + 1)
    if len(data) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Inbound import exceeds 50 MB")
    digest = hashlib.sha256(data).hexdigest()
    existing_result = await db.exec(
        select(CrmInboundImport).where(
            CrmInboundImport.organization_id == organization_id,
            CrmInboundImport.sha256 == digest,
        )
    )
    if existing := existing_result.first():
        return _import_response(existing)

    now = _utcnow()
    record = CrmInboundImport(
        organization_id=organization_id,
        created_by_user_id=user_id,
        name=name.strip() or Path(filename).stem,
        original_filename=filename,
        sha256=digest,
        size_bytes=len(data),
        status="processing",
        mapping={},
        summary={},
        created_at=now,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    summary = InboundImportSummary()
    try:
        rows, mapping = _file_rows(data, filename)
        record.mapping = mapping
        summary.total_rows = len(rows)
        if summary.total_rows > 10_000:
            raise ValueError("Inbound import exceeds the 10,000-row synchronous import limit")
        row_fingerprints: set[str] = set()
        for sheet, row_number, row in rows:
            first = _text(row.get("first_name"))
            last = _text(row.get("last_name"))
            full_name = _text(row.get("full_name")) or " ".join(part for part in (first, last) if part)
            phone = _normalize_phone(row.get("phone"))
            email = _normalize_email(row.get("email"))
            if not any((full_name, phone, email)):
                continue
            source_id = _text(row.get("source_lead_id"))
            fingerprint_payload = {
                "source_id": source_id,
                "name": full_name.casefold(),
                "phone": phone,
                "email": email,
                "intent": _text(row.get("intent")).casefold(),
                "notes": _text(row.get("notes")).casefold(),
                "locations": _text(row.get("locations")).casefold(),
                "budget": _text(row.get("budget_max")).casefold(),
                "created_at": _text(row.get("created_at")),
            }
            row_fingerprint = hashlib.sha256(
                json.dumps(fingerprint_payload, sort_keys=True).encode()
            ).hexdigest()
            if row_fingerprint in row_fingerprints:
                summary.duplicates += 1
                continue
            row_fingerprints.add(row_fingerprint)
            notes = _text(row.get("notes"))
            intent = _normalize_intent(row.get("intent"), notes)
            criteria = _deterministic_criteria(row, notes)
            redacted = _redact(notes, [full_name, phone or "", email or ""])
            needs_ai = bool(notes) and (
                intent is None
                or not criteria.get("locations")
                or (
                    intent in {"buy", "rent"}
                    and not any(
                        criteria.get(field) is not None
                        for field in ("bedrooms_min", "budget_max_aed", "property_type")
                    )
                )
            )
            ai_values, confidence, strict = (
                await _ai_extract(redacted, criteria) if needs_ai else ({}, 1.0, [])
            )
            ai_intent = ai_values.pop("_intent", None)
            intent = intent or (ai_intent if ai_intent in {"buy", "rent", "sell", "let"} else None)
            for key, value in ai_values.items():
                criteria.setdefault(key, value)
            review: list[str] = []
            if intent is None:
                intent = "buy"
                review.append("Intent was not explicit")
            if intent in {"buy", "rent"} and not criteria.get("locations"):
                review.append("Preferred location is missing")
            if confidence and confidence < 0.85:
                review.append("AI extraction confidence is below 85%")
            contact = await _find_or_create_contact(
                db,
                organization_id=organization_id,
                full_name=full_name,
                phone=phone,
                email=email,
                whatsapp=_normalize_phone(row.get("whatsapp")),
                language=_text(row.get("language")) or None,
                consent_status=_text(row.get("consent")) or "unknown",
            )
            enquiry = CrmInboundEnquiry(
                organization_id=organization_id,
                contact_id=contact.id or 0,
                source_import_id=record.id,
                created_by_user_id=user_id,
                assigned_user_id=user_id,
                intent=intent,
                status="needs_review" if review else "new",
                source=_text(row.get("source")) or "Imported",
                campaign=_text(row.get("campaign")) or record.name,
                source_lead_id=source_id or None,
                source_sheet=sheet,
                source_row_number=row_number,
                enquiry_date=_parse_datetime(row.get("created_at")),
                criteria=criteria,
                strict_fields=strict,
                raw_notes=notes or None,
                extraction_confidence=confidence or (0.8 if review else 0.9),
                extraction_evidence={"redacted_ai": bool(ai_values), "mapping": mapping},
                review_reasons=review,
                created_at=now,
                updated_at=now,
            )
            db.add(enquiry)
            summary.imported += 1
            summary.needs_review += int(bool(review))
            if intent == "buy":
                summary.buyers += 1
            elif intent == "rent":
                summary.tenants += 1
            elif intent == "sell":
                summary.sellers += 1
            else:
                summary.landlords += 1
        record.status = "completed"
        record.summary = summary.model_dump()
        record.completed_at = _utcnow()
        db.add(record)
        await db.commit()
        await db.refresh(record)
    except Exception as exc:
        await db.rollback()
        record.status = "failed"
        record.error_message = str(exc)[:1_000]
        record.summary = summary.model_dump()
        record.completed_at = _utcnow()
        db.add(record)
        await db.commit()
    return _import_response(record)


def _import_response(record: CrmInboundImport) -> InboundImportResponse:
    return InboundImportResponse(
        id=record.id or 0,
        name=record.name,
        original_filename=record.original_filename,
        status=record.status,  # type: ignore[arg-type]
        summary=InboundImportSummary.model_validate(record.summary or {}),
        mapping=record.mapping or {},
        error_message=record.error_message,
        created_at=record.created_at,
        completed_at=record.completed_at,
    )


async def list_inbound_imports(db: AsyncSession, organization_id: str) -> list[InboundImportResponse]:
    result = await db.exec(
        select(CrmInboundImport)
        .where(CrmInboundImport.organization_id == organization_id)
        .order_by(CrmInboundImport.created_at.desc())
    )
    return [_import_response(item) for item in result.all()]


async def delete_inbound_import(db: AsyncSession, import_id: int, organization_id: str) -> None:
    result = await db.exec(
        select(CrmInboundImport).where(
            CrmInboundImport.id == import_id,
            CrmInboundImport.organization_id == organization_id,
        )
    )
    record = result.first()
    if not record:
        raise HTTPException(status_code=404, detail="Inbound import not found")
    imported_enquiries = await db.exec(
        select(CrmInboundEnquiry.contact_id).where(
            CrmInboundEnquiry.source_import_id == import_id,
            CrmInboundEnquiry.organization_id == organization_id,
        )
    )
    contact_ids = list(dict.fromkeys(imported_enquiries.all()))
    await db.exec(
        delete(CrmInboundEnquiry).where(
            CrmInboundEnquiry.source_import_id == import_id,
            CrmInboundEnquiry.organization_id == organization_id,
        )
    )
    if contact_ids:
        await db.exec(
            delete(CrmInboundContact).where(
                CrmInboundContact.organization_id == organization_id,
                CrmInboundContact.id.in_(contact_ids),  # type: ignore[union-attr]
                ~exists(
                    select(CrmInboundEnquiry.id).where(
                        CrmInboundEnquiry.contact_id == CrmInboundContact.id
                    )
                ),
            )
        )
    await db.delete(record)
    await db.commit()


def _contact_response(contact: CrmInboundContact) -> InboundContactResponse:
    return InboundContactResponse(
        id=contact.id or 0,
        full_name=contact.full_name,
        phone=contact.phone,
        email=contact.email,
        whatsapp=contact.whatsapp,
        preferred_language=contact.preferred_language,
        preferred_channel=contact.preferred_channel,
        consent_status=contact.consent_status,
        do_not_contact=contact.do_not_contact,
    )


async def _enquiry_response(
    db: AsyncSession,
    enquiry: CrmInboundEnquiry,
    *,
    contact: CrmInboundContact | None = None,
) -> InboundEnquiryResponse:
    contact = contact or await db.get(CrmInboundContact, enquiry.contact_id)
    if not contact or contact.organization_id != enquiry.organization_id:
        raise HTTPException(status_code=500, detail="Inbound contact is missing")
    notes_result = await db.exec(
        select(CrmInboundNote)
        .where(CrmInboundNote.enquiry_id == enquiry.id)
        .order_by(CrmInboundNote.created_at.desc())
    )
    matches_result = await db.exec(
        select(CrmInboundMatch).where(CrmInboundMatch.enquiry_id == enquiry.id)
    )
    matches = matches_result.all()
    return InboundEnquiryResponse(
        id=enquiry.id or 0,
        contact=_contact_response(contact),
        intent=enquiry.intent,  # type: ignore[arg-type]
        status=enquiry.status,  # type: ignore[arg-type]
        assigned_user_id=enquiry.assigned_user_id,
        source=enquiry.source,
        campaign=enquiry.campaign,
        source_import_id=enquiry.source_import_id,
        enquiry_date=enquiry.enquiry_date,
        criteria=enquiry.criteria,
        strict_fields=enquiry.strict_fields,
        raw_notes=enquiry.raw_notes,
        extraction_confidence=enquiry.extraction_confidence,
        review_reasons=enquiry.review_reasons,
        next_follow_up=enquiry.next_follow_up,
        tags=enquiry.tags,
        notes=[
            InboundNoteResponse(id=note.id or 0, body=note.body, user_id=note.user_id, created_at=note.created_at)
            for note in notes_result.all()
        ],
        match_count=len([item for item in matches if item.state != "dismissed"]),
        saved_match_count=len([item for item in matches if item.state == "saved"]),
        created_at=enquiry.created_at,
        updated_at=enquiry.updated_at,
    )


async def list_inbound_enquiries(
    db: AsyncSession,
    *,
    organization_id: str,
    intent_group: str | None,
    status: str | None,
    search: str | None,
    limit: int,
    offset: int,
) -> InboundEnquiryListResponse:
    result = await db.exec(
        select(CrmInboundEnquiry)
        .where(CrmInboundEnquiry.organization_id == organization_id)
        .order_by(CrmInboundEnquiry.enquiry_date.desc())
    )
    enquiries = list(result.all())
    all_enquiries = enquiries[:]
    if intent_group == "demand":
        enquiries = [item for item in enquiries if item.intent in {"buy", "rent"}]
    elif intent_group == "instructions":
        enquiries = [item for item in enquiries if item.intent in {"sell", "let"}]
    if status:
        enquiries = [item for item in enquiries if item.status == status]
    contacts: dict[int, CrmInboundContact] = {}
    if enquiries:
        contacts_result = await db.exec(
            select(CrmInboundContact).where(
                CrmInboundContact.id.in_([item.contact_id for item in enquiries])  # type: ignore[union-attr]
            )
        )
        contacts = {item.id or 0: item for item in contacts_result.all()}
    if search:
        term = search.casefold()
        enquiries = [
            item
            for item in enquiries
            if term in contacts.get(item.contact_id, CrmInboundContact(organization_id="", full_name="", created_at=_utcnow(), updated_at=_utcnow())).full_name.casefold()
            or term in json.dumps(item.criteria).casefold()
            or term in (item.campaign or "").casefold()
        ]
    total = len(enquiries)
    page = enquiries[offset : offset + limit]
    responses = [await _enquiry_response(db, item, contact=contacts.get(item.contact_id)) for item in page]
    return InboundEnquiryListResponse(
        enquiries=responses,
        total=total,
        summary={
            "total": len(all_enquiries),
            "demand": len([item for item in all_enquiries if item.intent in {"buy", "rent"}]),
            "instructions": len([item for item in all_enquiries if item.intent in {"sell", "let"}]),
            "needs_review": len([item for item in all_enquiries if item.status == "needs_review"]),
            "unassigned": len([item for item in all_enquiries if not item.assigned_user_id]),
        },
    )


async def get_inbound_enquiry(db: AsyncSession, enquiry_id: int, organization_id: str) -> InboundEnquiryResponse:
    enquiry = await db.get(CrmInboundEnquiry, enquiry_id)
    if not enquiry or enquiry.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Inbound enquiry not found")
    return await _enquiry_response(db, enquiry)


async def update_inbound_enquiry(
    db: AsyncSession,
    *,
    enquiry_id: int,
    organization_id: str,
    payload: InboundEnquiryUpdate,
) -> InboundEnquiryResponse:
    enquiry = await db.get(CrmInboundEnquiry, enquiry_id)
    if not enquiry or enquiry.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Inbound enquiry not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "notes":
            enquiry.raw_notes = value
        else:
            setattr(enquiry, key, value)
    enquiry.updated_at = _utcnow()
    db.add(enquiry)
    await db.commit()
    await db.refresh(enquiry)
    return await _enquiry_response(db, enquiry)


async def add_inbound_note(
    db: AsyncSession, *, enquiry_id: int, organization_id: str, user_id: str, body: str
) -> InboundEnquiryResponse:
    enquiry = await db.get(CrmInboundEnquiry, enquiry_id)
    if not enquiry or enquiry.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Inbound enquiry not found")
    db.add(
        CrmInboundNote(
            enquiry_id=enquiry_id,
            organization_id=organization_id,
            user_id=user_id,
            body=body.strip(),
            created_at=_utcnow(),
        )
    )
    enquiry.updated_at = _utcnow()
    db.add(enquiry)
    await db.commit()
    return await _enquiry_response(db, enquiry)


def _locations(criteria: dict[str, Any]) -> list[str]:
    value = criteria.get("locations", [])
    return [str(item) for item in value] if isinstance(value, list) else [str(value)] if value else []


def _location_fit(criteria: dict[str, Any], *values: str) -> tuple[int, str]:
    requested = _locations(criteria)
    if not requested:
        return 10, "Location is open"
    haystack = " ".join(values).casefold()
    if any(item.casefold() in haystack or haystack in item.casefold() for item in requested):
        return 20, f"Matches {requested[0]}"
    return 0, "Outside preferred location"


def _budget_fit(criteria: dict[str, Any], value: int | None) -> tuple[int, str]:
    maximum = int(criteria.get("budget_max_aed") or 0)
    minimum = int(criteria.get("budget_min_aed") or 0)
    if not maximum and not minimum:
        return 8, "Budget is open"
    if not value:
        return 5, "Price requires verification"
    if (not minimum or value >= minimum) and (not maximum or value <= maximum):
        return 15, "Within stated budget"
    if maximum and value <= maximum * 1.1 and value >= minimum * 0.9:
        return 9, "Within flexible budget margin"
    return 0, "Outside budget"


def _bedroom_fit(criteria: dict[str, Any], value: str) -> tuple[int, str]:
    requested = criteria.get("bedrooms_min")
    if requested is None:
        return 5, "Bedroom count is open"
    match = re.search(r"\d+", value)
    observed = int(match.group()) if match else 0 if "studio" in value.lower() else None
    if observed == int(requested):
        return 10, "Exact bedroom match"
    if observed is not None and abs(observed - int(requested)) <= 1:
        return 6, "Within flexible bedroom range"
    return 0, "Bedroom mismatch"


def _violates_strict_fields(
    strict_fields: list[str],
    *,
    location_points: int,
    budget_points: int,
    bedroom_points: int,
    property_points: int,
) -> bool:
    checks = {
        "locations": location_points,
        "budget_min_aed": budget_points,
        "budget_max_aed": budget_points,
        "bedrooms_min": bedroom_points,
        "bedrooms_max": bedroom_points,
        "property_type": property_points,
    }
    return any(checks.get(field, 1) == 0 for field in strict_fields)


def _optional_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def _listing_freshness() -> tuple[datetime | None, bool]:
    try:
        rows = await query(
            "SELECT max(parseDateTimeBestEffortOrNull(scraped_at)) AS refreshed FROM pf_listings_bronze",
            {},
        )
        refreshed = _optional_datetime(rows[0].get("refreshed") if rows else None)
        fresh = bool(
            refreshed
            and (_utcnow() - refreshed).total_seconds() <= _LISTING_MAX_AGE_HOURS * 3600
        )
        return refreshed, fresh
    except Exception:
        return None, False


def _json_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, date | datetime) else value
        for key, value in row.items()
    }


async def _rental_opportunity_rows(criteria: dict[str, Any]) -> list[dict[str, Any]]:
    requested_locations = _locations(criteria)
    return await query(
        """
        SELECT
            c.unit_candidate_key,
            c.event_key,
            c.building_name,
            c.project_name,
            c.area_name,
            c.property_type,
            c.bedrooms,
            c.size_sqft,
            c.annual_rent_aed,
            c.purchase_price_aed,
            c.lease_start,
            c.lease_end,
            c.contract_state,
            c.observed_contracts,
            m.unit_number,
            m.last_purchase_date,
            m.matched_sale_price,
            m.match_status,
            m.latest_detail_url
        FROM dxbi_rental_unit_candidates AS c FINAL
        LEFT JOIN dxbi_rental_sale_matches AS m FINAL USING (unit_candidate_key)
        WHERE
            c.lease_end BETWEEN today() - 1825 AND today() + 90
            AND (
                {area:String} = ''
                OR positionCaseInsensitiveUTF8(c.area_name, {area:String}) > 0
                OR positionCaseInsensitiveUTF8(c.project_name, {area:String}) > 0
                OR positionCaseInsensitiveUTF8(c.building_name, {area:String}) > 0
            )
            AND (
                {property_type:String} = ''
                OR lowerUTF8(c.property_type) = lowerUTF8({property_type:String})
            )
        ORDER BY
            abs(dateDiff('day', today(), c.lease_end)) ASC,
            c.annual_rent_aed DESC
        LIMIT 40
        """,
        {
            "area": requested_locations[0] if requested_locations else "",
            "property_type": str(criteria.get("property_type") or ""),
        },
    )


def _match_response(item: CrmInboundMatch) -> InboundMatchResponse:
    return InboundMatchResponse(
        id=item.id or 0,
        target_type=item.target_type,  # type: ignore[arg-type]
        target_key=item.target_key,
        score=item.score,
        state=item.state,  # type: ignore[arg-type]
        title=item.title,
        subtitle=item.subtitle,
        reasons=item.reasons,
        score_breakdown=item.score_breakdown,
        snapshot=item.snapshot,
        generated_at=item.generated_at,
    )


async def _upsert_match(
    db: AsyncSession,
    *,
    enquiry: CrmInboundEnquiry,
    target_type: str,
    target_key: str,
    score: int,
    title: str,
    subtitle: str,
    reasons: list[str],
    breakdown: dict[str, Any],
    snapshot: dict[str, Any],
) -> CrmInboundMatch | None:
    if score < 50:
        return None
    result = await db.exec(
        select(CrmInboundMatch).where(
            CrmInboundMatch.enquiry_id == enquiry.id,
            CrmInboundMatch.target_type == target_type,
            CrmInboundMatch.target_key == target_key,
        )
    )
    item = result.first()
    now = _utcnow()
    if item is None:
        item = CrmInboundMatch(
            enquiry_id=enquiry.id or 0,
            organization_id=enquiry.organization_id,
            target_type=target_type,
            target_key=target_key,
            score=score,
            title=title,
            subtitle=subtitle,
            reasons=reasons,
            score_breakdown=breakdown,
            snapshot=snapshot,
            generated_at=now,
            updated_at=now,
        )
    elif item.state != "dismissed":
        item.score = score
        item.title = title
        item.subtitle = subtitle
        item.reasons = reasons
        item.score_breakdown = breakdown
        item.snapshot = snapshot
        item.generated_at = now
        item.updated_at = now
    db.add(item)
    return item


async def refresh_inbound_matches(
    db: AsyncSession,
    *,
    enquiry_id: int,
    organization_id: str,
    expand_units: bool = False,
) -> InboundMatchesResponse:
    enquiry = await db.get(CrmInboundEnquiry, enquiry_id)
    if not enquiry or enquiry.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Inbound enquiry not found")
    criteria = enquiry.criteria or {}
    generated: list[CrmInboundMatch] = []

    if enquiry.intent in {"buy", "rent"}:
        requested_locations = _locations(criteria)
        claims_statement = select(CrmPropertyContactClaim).where(
            CrmPropertyContactClaim.organization_id == organization_id,
            CrmPropertyContactClaim.ownership_status.in_(  # type: ignore[union-attr]
                ["verified_current_owner", "probable_current_owner"]
            ),
        )
        if requested_locations:
            location_pattern = f"%{requested_locations[0]}%"
            claims_statement = claims_statement.where(
                or_(
                    CrmPropertyContactClaim.area_name.ilike(location_pattern),  # type: ignore[union-attr]
                    CrmPropertyContactClaim.project_name.ilike(location_pattern),  # type: ignore[union-attr]
                    CrmPropertyContactClaim.building_name.ilike(location_pattern),  # type: ignore[union-attr]
                )
            )
        claims_result = await db.exec(
            claims_statement.order_by(CrmPropertyContactClaim.confidence_score.desc()).limit(80)
        )
        best_by_owner: dict[str, CrmPropertyContactClaim] = {}
        for claim in claims_result.all():
            current = best_by_owner.get(claim.owner_key)
            if current is None or claim.confidence_score > current.confidence_score:
                best_by_owner[claim.owner_key] = claim
        for claim in best_by_owner.values():
            location, location_reason = _location_fit(
                criteria, claim.area_name, claim.project_name, claim.building_name
            )
            budget, budget_reason = _budget_fit(criteria, claim.latest_sale_price_aed)
            property_points = 10 if not criteria.get("property_type") or criteria.get("property_type", "").casefold() in claim.property_type.casefold() else 0
            if _violates_strict_fields(
                enquiry.strict_fields,
                location_points=location,
                budget_points=budget,
                bedroom_points=5,
                property_points=property_points,
            ):
                continue
            actionability = 20 if claim.phone_primary or claim.email_primary else 10
            timing = 10 if claim.lease_end else 3
            score = min(100, location + budget + property_points + 15 + actionability + timing)
            item = await _upsert_match(
                db,
                enquiry=enquiry,
                target_type="owner",
                target_key=claim.owner_key,
                score=score,
                title=claim.contact_name,
                subtitle=f"{claim.building_name or claim.project_name} · Unit {claim.unit_number}",
                reasons=[location_reason, budget_reason, "Current ownership evidence", "Contact available" if actionability == 20 else "Contact enrichment needed"],
                breakdown={"requirements": location + budget + property_points + 15, "actionability": actionability, "timing": timing},
                snapshot={
                    "owner_key": claim.owner_key,
                    "phone": claim.phone_primary,
                    "email": claim.email_primary,
                    "area_name": claim.area_name,
                    "project_name": claim.project_name,
                    "building_name": claim.building_name,
                    "unit_number": claim.unit_number,
                    "latest_sale_price_aed": claim.latest_sale_price_aed,
                    "lease_end": claim.lease_end.isoformat() if claim.lease_end else None,
                },
            )
            if item:
                generated.append(item)

        for lead in await _rental_opportunity_rows(criteria):
            location, location_reason = _location_fit(
                criteria,
                str(lead.get("area_name") or ""),
                str(lead.get("project_name") or ""),
                str(lead.get("building_name") or ""),
            )
            price = int(lead.get("matched_sale_price") or lead.get("purchase_price_aed") or 0) or None
            budget, budget_reason = _budget_fit(criteria, price)
            bedrooms = str(lead.get("bedrooms") or "")
            bedroom, bedroom_reason = _bedroom_fit(criteria, bedrooms)
            property_type = str(lead.get("property_type") or "")
            property_points = 10 if not criteria.get("property_type") or criteria.get("property_type", "").casefold() in property_type.casefold() else 0
            if _violates_strict_fields(
                enquiry.strict_fields,
                location_points=location,
                budget_points=budget,
                bedroom_points=bedroom,
                property_points=property_points,
            ):
                continue
            score = min(100, location + budget + bedroom + property_points + 7 + 10 + 10)
            item = await _upsert_match(
                db,
                enquiry=enquiry,
                target_type="unit",
                target_key=str(lead["unit_candidate_key"]),
                score=score,
                title=f"{lead.get('building_name') or 'Building'} · Unit {lead.get('unit_number') or 'unresolved'}",
                subtitle=f"{bedrooms or 'Layout pending'} · AED {price:,}" if price else f"{bedrooms or 'Layout pending'} · value pending",
                reasons=[
                    location_reason,
                    budget_reason,
                    bedroom_reason,
                    f"Lease ends {lead.get('lease_end')}",
                ],
                breakdown={"requirements": location + budget + bedroom + property_points, "actionability": 7, "timing": 10},
                snapshot=_json_snapshot(lead),
            )
            if item:
                generated.append(item)

        if expand_units:
            sales_rows = await query(
                """
                SELECT
                    sales.building_key,
                    lowerUTF8(sales.unit_number) AS normalized_unit,
                    argMax(sales.sale_key, sales.transaction_date) AS sale_key,
                    argMax(sales.building_name, sales.transaction_date) AS building_name,
                    argMax(sales.unit_number, sales.transaction_date) AS unit_number,
                    argMax(sales.area_name, sales.transaction_date) AS area_name,
                    argMax(sales.property_type, sales.transaction_date) AS property_type,
                    argMax(sales.bedrooms, sales.transaction_date) AS bedrooms,
                    argMax(sales.size_sqft, sales.transaction_date) AS size_sqft,
                    argMax(sales.sale_amount_aed, sales.transaction_date) AS sale_amount_aed,
                    max(sales.transaction_date) AS latest_sale_date
                FROM (
                    SELECT *
                    FROM dxbi_sales_unit_events FINAL
                    WHERE
                        unit_number != ''
                        AND (
                            {area:String} = ''
                            OR positionCaseInsensitiveUTF8(area_name, {area:String}) > 0
                            OR positionCaseInsensitiveUTF8(building_name, {area:String}) > 0
                        )
                ) AS sales
                GROUP BY sales.building_key, normalized_unit
                ORDER BY latest_sale_date DESC
                LIMIT 120
                """,
                {"area": requested_locations[0] if requested_locations else ""},
            )
            existing_keys = {item.target_key for item in generated if item.target_type == "unit"}
            for row in sales_rows:
                target_key = f"registry:{row.get('building_key', '')}|{row.get('normalized_unit', '')}"
                if target_key in existing_keys:
                    continue
                location, location_reason = _location_fit(
                    criteria, str(row.get("area_name") or ""), str(row.get("building_name") or "")
                )
                price = int(row.get("sale_amount_aed") or 0) or None
                budget, budget_reason = _budget_fit(criteria, price)
                bedroom, bedroom_reason = _bedroom_fit(criteria, str(row.get("bedrooms") or ""))
                property_points = 10 if not criteria.get("property_type") or criteria.get("property_type", "").casefold() in str(row.get("property_type") or "").casefold() else 0
                if _violates_strict_fields(
                    enquiry.strict_fields,
                    location_points=location,
                    budget_points=budget,
                    bedroom_points=bedroom,
                    property_points=property_points,
                ):
                    continue
                score = min(100, location + budget + bedroom + property_points + 5 + 5 + 10)
                latest_sale_date = row.get("latest_sale_date")
                item = await _upsert_match(
                    db,
                    enquiry=enquiry,
                    target_type="unit",
                    target_key=target_key,
                    score=score,
                    title=f"{row.get('building_name') or 'Building'} · Unit {row.get('unit_number')}",
                    subtitle=f"{row.get('bedrooms') or 'Layout pending'} · {f'AED {price:,}' if price else 'value pending'}",
                    reasons=[location_reason, budget_reason, bedroom_reason, "Expanded sales-registry universe"],
                    breakdown={"requirements": location + budget + bedroom + property_points, "actionability": 5, "timing": 5},
                    snapshot={
                        **row,
                        "latest_sale_date": latest_sale_date.isoformat() if isinstance(latest_sale_date, date) else latest_sale_date,
                        "source": "sales_registry",
                    },
                )
                if item:
                    generated.append(item)
                    existing_keys.add(target_key)
    else:
        reverse_intent = "buy" if enquiry.intent == "sell" else "rent"
        building = str(criteria.get("building") or "").strip()
        unit_number = str(criteria.get("unit_number") or "").strip()
        if building and unit_number:
            evidence_rows = await query(
                """
                SELECT
                    sale_key,
                    transaction_date,
                    building_name,
                    unit_number,
                    area_name,
                    property_type,
                    bedrooms,
                    size_sqft,
                    sale_amount_aed,
                    ltv_pct,
                    seller_type,
                    detail_url
                FROM dxbi_sales_unit_events FINAL
                WHERE
                    positionCaseInsensitiveUTF8(building_name, {building:String}) > 0
                    AND lowerUTF8(unit_number) = lowerUTF8({unit_number:String})
                ORDER BY transaction_date DESC
                LIMIT 1
                """,
                {"building": building, "unit_number": unit_number},
            )
            if evidence_rows:
                evidence = evidence_rows[0]
                sale_price = int(evidence.get("sale_amount_aed") or 0)
                item = await _upsert_match(
                    db,
                    enquiry=enquiry,
                    target_type="unit",
                    target_key=f"instruction:{evidence.get('sale_key')}",
                    score=98,
                    title=f"{evidence.get('building_name')} · Unit {evidence.get('unit_number')}",
                    subtitle=f"Latest recorded sale · AED {sale_price:,}",
                    reasons=[
                        "Exact building and unit match",
                        f"Purchased {evidence.get('transaction_date')}",
                        "Financing-at-purchase evidence available"
                        if evidence.get("ltv_pct") is not None
                        else "Financing evidence not exposed",
                    ],
                    breakdown={"identity": 50, "evidence": 28, "actionability": 20},
                    snapshot={**_json_snapshot(evidence), "source": "sales_registry"},
                )
                if item:
                    generated.append(item)
        reverse_result = await db.exec(
            select(CrmInboundEnquiry).where(
                CrmInboundEnquiry.organization_id == organization_id,
                CrmInboundEnquiry.intent == reverse_intent,
                CrmInboundEnquiry.id != enquiry.id,
                CrmInboundEnquiry.status.notin_(["closed_lost", "won"]),  # type: ignore[union-attr]
            )
        )
        subject_locations = _locations(criteria)
        if not subject_locations and building:
            subject_locations = [building]
        subject_value = criteria.get("expected_price_aed") or criteria.get("budget_max_aed")
        for demand in reverse_result.all():
            locations = _locations(demand.criteria)
            location = 20 if not subject_locations or not locations or any(a.casefold() in b.casefold() or b.casefold() in a.casefold() for a in subject_locations for b in locations) else 0
            budget, budget_reason = _budget_fit(demand.criteria, int(subject_value or 0) or None)
            bedroom, bedroom_reason = _bedroom_fit(demand.criteria, str(criteria.get("bedrooms_min", "")))
            score = min(100, location + budget + bedroom + 10 + 20 + 10)
            contact = await db.get(CrmInboundContact, demand.contact_id)
            if not contact:
                continue
            item = await _upsert_match(
                db,
                enquiry=enquiry,
                target_type="demand",
                target_key=str(demand.id),
                score=score,
                title=contact.full_name,
                subtitle=f"Active {reverse_intent} enquiry · {demand.campaign or demand.source}",
                reasons=["Reverse demand match", budget_reason, bedroom_reason],
                breakdown={"requirements": location + budget + bedroom + 10, "actionability": 20, "timing": 10},
                snapshot={"enquiry_id": demand.id, "criteria": demand.criteria, "phone": contact.phone, "email": contact.email},
            )
            if item:
                generated.append(item)

    listing_last_refresh, listing_fresh = await _listing_freshness()

    if listing_fresh and enquiry.intent in {"buy", "rent"}:
        requested_locations = _locations(criteria)
        listings = await list_listings_from_clickhouse(
            mode="sale" if enquiry.intent == "buy" else "rent",
            limit=60,
            area=requested_locations[0] if requested_locations else None,
            property_type=criteria.get("property_type"),
            bedrooms=str(criteria.get("bedrooms_min")) if criteria.get("bedrooms_min") is not None else None,
            price_max=criteria.get("budget_max_aed"),
        )
        for listing in listings.listings:
            location, location_reason = _location_fit(criteria, listing.area_name or "", listing.subcommunity_name or "", listing.tower_name or "")
            budget, budget_reason = _budget_fit(criteria, listing.price_value)
            bedroom, bedroom_reason = _bedroom_fit(criteria, listing.bedrooms or "")
            property_points = 10 if not criteria.get("property_type") or criteria.get("property_type", "").casefold() in (listing.property_type or "").casefold() else 0
            if _violates_strict_fields(
                enquiry.strict_fields,
                location_points=location,
                budget_points=budget,
                bedroom_points=bedroom,
                property_points=property_points,
            ):
                continue
            score = min(100, location + budget + bedroom + property_points + 20 + 10)
            item = await _upsert_match(
                db,
                enquiry=enquiry,
                target_type="listing",
                target_key=listing.listing_id,
                score=score,
                title=listing.title,
                subtitle=f"{listing.tower_name or listing.area_name or 'Dubai'} · AED {listing.price_value:,}" if listing.price_value else listing.tower_name or "Dubai",
                reasons=[location_reason, budget_reason, bedroom_reason, "Fresh active listing"],
                breakdown={"requirements": location + budget + bedroom + property_points, "actionability": 20, "timing": 10},
                snapshot=listing.model_dump(mode="json"),
            )
            if item:
                generated.append(item)

    await db.commit()
    stored = await db.exec(
        select(CrmInboundMatch)
        .where(CrmInboundMatch.enquiry_id == enquiry_id)
        .order_by(CrmInboundMatch.score.desc())
    )
    lanes: dict[str, list[InboundMatchResponse]] = {"owners": [], "units": [], "listings": [], "demand": []}
    lane_names = {"owner": "owners", "unit": "units", "listing": "listings", "demand": "demand"}
    for item in stored.all():
        if item.state != "dismissed":
            lanes[lane_names[item.target_type]].append(_match_response(item))
    return InboundMatchesResponse(
        enquiry_id=enquiry_id,
        listing_fresh=listing_fresh,
        listing_last_refresh=listing_last_refresh,
        lanes=lanes,
    )


async def get_inbound_matches(db: AsyncSession, enquiry_id: int, organization_id: str) -> InboundMatchesResponse:
    enquiry = await db.get(CrmInboundEnquiry, enquiry_id)
    if not enquiry or enquiry.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Inbound enquiry not found")
    result = await db.exec(
        select(CrmInboundMatch)
        .where(CrmInboundMatch.enquiry_id == enquiry_id)
        .order_by(CrmInboundMatch.score.desc())
    )
    items = result.all()
    if not items:
        return await refresh_inbound_matches(db, enquiry_id=enquiry_id, organization_id=organization_id)
    listing_last_refresh, listing_fresh = await _listing_freshness()
    lanes: dict[str, list[InboundMatchResponse]] = {"owners": [], "units": [], "listings": [], "demand": []}
    lane_names = {"owner": "owners", "unit": "units", "listing": "listings", "demand": "demand"}
    for item in items:
        if item.state != "dismissed" and (item.target_type != "listing" or listing_fresh):
            lanes[lane_names[item.target_type]].append(_match_response(item))
    return InboundMatchesResponse(
        enquiry_id=enquiry_id,
        listing_fresh=listing_fresh,
        listing_last_refresh=listing_last_refresh,
        lanes=lanes,
    )


async def update_inbound_match_state(
    db: AsyncSession, *, match_id: int, organization_id: str, state: str
) -> InboundMatchResponse:
    item = await db.get(CrmInboundMatch, match_id)
    if not item or item.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Inbound match not found")
    item.state = state
    item.updated_at = _utcnow()
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _match_response(item)
