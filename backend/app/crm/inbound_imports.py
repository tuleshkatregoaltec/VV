from __future__ import annotations

import hashlib
import io
import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

import openpyxl
from fastapi import HTTPException, UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.async_work import run_in_thread
from app.crm import agent_languages, assignment, import_jobs, inbound_repository, rotation, routing
from app.crm.ai import _ai_extract, _ai_header_mapping
from app.crm.identity import _normalize_email, _normalize_phone
from app.crm.import_safety import (
    MAX_IMPORT_COLUMNS,
    MAX_IMPORT_ROWS,
    ImportInputError,
    client_message,
    csv_rows,
    validate_xlsx,
)
from app.crm.inbound import _bulk_ownership_enrichments, _find_or_create_contact
from app.crm.inbound_models import (
    CrmInboundActivity,
    CrmInboundContact,
    CrmInboundEnquiry,
    CrmInboundImport,
    InboundImportAssignmentSummary,
    InboundImportPreviewResponse,
    InboundImportPreviewSheet,
    InboundImportResponse,
    InboundImportSummary,
    InboundOwnershipEnrichmentResponse,
    UnassignedReason,
)
from app.crm.inbound_policy import (
    _ALIASES,
    _FIRST_RESPONSE_MINUTES,
    _deterministic_criteria,
    _lead_priority,
    _normalize_intent,
    _parse_datetime,
    _redact,
    _text,
    _token,
    _utcnow,
)
from app.crm.routing_models import ImportAssignmentPolicy

_MAX_FILE_BYTES = 50 * 1024 * 1024

logger = logging.getLogger(__name__)


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


def _mapping_override_for_sheet(
    override: dict[str, Any] | None,
    sheet_name: str,
    headers: list[Any],
    detected: dict[str, int],
) -> dict[str, int]:
    if not override:
        return detected
    sheets = override.get("sheets", [])
    sheet_config = next((item for item in sheets if item.get("sheet") == sheet_name), None)
    if not sheet_config:
        return detected
    by_header = {_text(header): index for index, header in enumerate(headers)}
    mapped = {
        canonical: by_header[header]
        for canonical, header in sheet_config.get("field_map", {}).items()
        if header in by_header and canonical in _ALIASES
    }
    return mapped or detected


def _file_rows(
    data: bytes,
    filename: str,
    mapping_override: dict[str, Any] | None = None,
) -> tuple[list[tuple[str, int, dict[str, Any]]], dict[str, Any]]:
    rows: list[tuple[str, int, dict[str, Any]]] = []
    mappings: list[dict[str, Any]] = []
    if filename.lower().endswith(".csv"):
        raw = csv_rows(data)
        header_index, header_values, mapping = _best_header([tuple(row) for row in raw])
        headers = list(header_values)
        sheet_name = Path(filename).stem
        mapping = _mapping_override_for_sheet(mapping_override, sheet_name, headers, mapping)
        for row_number, values in enumerate(raw[header_index + 1 :], start=header_index + 2):
            if any(_text(value) for value in values):
                rows.append(
                    (
                        sheet_name,
                        row_number,
                        {
                            key: values[index] if index < len(values) else None
                            for key, index in mapping.items()
                        },
                    )
                )
        mappings.append(
            {
                "sheet": sheet_name,
                "header_row": header_index + 1,
                "headers": [_text(value) for value in headers if _text(value)],
                "field_map": {key: headers[index] for key, index in mapping.items()},
            }
        )
        if len(rows) > MAX_IMPORT_ROWS:
            raise ImportInputError(f"Import exceeds the {MAX_IMPORT_ROWS:,}-row limit")
        return rows, {"sheets": mappings}

    validate_xlsx(data)
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            if sheet.max_column and sheet.max_column > MAX_IMPORT_COLUMNS:
                raise ImportInputError(f"Import exceeds the {MAX_IMPORT_COLUMNS}-column limit")
            if sheet.max_row and sheet.max_row > MAX_IMPORT_ROWS + 15:
                raise ImportInputError(f"Import exceeds the {MAX_IMPORT_ROWS:,}-row limit")
            preview = list(sheet.iter_rows(min_row=1, max_row=15, values_only=True))
            header_index, header_values, mapping = _best_header(preview)
            mapping = _mapping_override_for_sheet(
                mapping_override, sheet.title, list(header_values), mapping
            )
            mappings.append(
                {
                    "sheet": sheet.title,
                    "header_row": header_index + 1,
                    "headers": [_text(value) for value in header_values if _text(value)],
                    "field_map": {
                        key: _text(header_values[index]) for key, index in mapping.items()
                    },
                }
            )
            for row_number, values in enumerate(
                sheet.iter_rows(min_row=header_index + 2, values_only=True), start=header_index + 2
            ):
                if len(values) > MAX_IMPORT_COLUMNS:
                    raise ImportInputError(f"Import exceeds the {MAX_IMPORT_COLUMNS}-column limit")
                if any(value not in (None, "") for value in values):
                    if len(rows) >= MAX_IMPORT_ROWS:
                        raise ImportInputError(f"Import exceeds the {MAX_IMPORT_ROWS:,}-row limit")
                    rows.append(
                        (
                            sheet.title,
                            row_number,
                            {
                                key: values[index] if index < len(values) else None
                                for key, index in mapping.items()
                            },
                        )
                    )
    finally:
        workbook.close()
    return rows, {"sheets": mappings}


def _preview_file(
    data: bytes,
    filename: str,
    mapping_override: dict[str, Any] | None = None,
    ai_mapped_sheets: set[str] | None = None,
) -> InboundImportPreviewResponse:
    rows, audit = _file_rows(data, filename, mapping_override)
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for sheet, row_number, row in rows:
        grouped.setdefault(sheet, []).append((row_number, row))
    sheets = []
    for item in audit.get("sheets", []):
        sheet_name = item["sheet"]
        field_map = item.get("field_map", {})
        headers = item.get("headers", [])
        samples = []
        for row_number, row in grouped.get(sheet_name, [])[:5]:
            samples.append(
                {
                    "row": str(row_number),
                    **{
                        key: _redact(_text(value), [])[:160]
                        for key, value in row.items()
                        if value not in (None, "") and key not in {"phone", "email", "whatsapp"}
                    },
                    **{key: "Present" for key in ("phone", "email", "whatsapp") if row.get(key)},
                }
            )
        sheets.append(
            InboundImportPreviewSheet(
                sheet=sheet_name,
                header_row=item.get("header_row", 1),
                headers=headers,
                field_map=field_map,
                sample_rows=samples,
                row_count=len(grouped.get(sheet_name, [])),
                mapping_source=(
                    "ai_assisted" if sheet_name in (ai_mapped_sheets or set()) else "deterministic"
                ),
            )
        )
    warnings = []
    if not any("full_name" in sheet.field_map for sheet in sheets):
        warnings.append("No name column was detected")
    if not any({"phone", "email"} & set(sheet.field_map) for sheet in sheets):
        warnings.append("No phone or email column was detected")
    return InboundImportPreviewResponse(
        original_filename=filename,
        size_bytes=len(data),
        total_rows=len(rows),
        sheets=sheets,
        warnings=warnings,
    )


async def preview_inbound_import(
    upload: UploadFile, campaign_context: str = ""
) -> InboundImportPreviewResponse:
    filename = Path(upload.filename or "inbound-leads.xlsx").name
    if not filename.lower().endswith((".xlsx", ".csv")):
        raise HTTPException(status_code=415, detail="Upload a CSV or XLSX file")
    data = await upload.read(_MAX_FILE_BYTES + 1)
    if len(data) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Inbound import exceeds 50 MB")
    try:
        preview = await run_in_thread(_preview_file, data, filename)
        ai_mapped_sheets: set[str] = set()
        for sheet in preview.sheets:
            has_identity = bool(
                {"full_name", "first_name", "phone", "email"} & set(sheet.field_map)
            )
            if has_identity and len(sheet.field_map) >= 4:
                continue
            suggested = await _ai_header_mapping(sheet.headers, campaign_context.strip()[:4_000])
            for canonical, header in suggested.items():
                sheet.field_map.setdefault(canonical, header)
            if suggested:
                ai_mapped_sheets.add(sheet.sheet)
        if ai_mapped_sheets:
            override = {
                "sheets": [
                    {"sheet": sheet.sheet, "field_map": sheet.field_map} for sheet in preview.sheets
                ]
            }
            preview = await run_in_thread(_preview_file, data, filename, override, ai_mapped_sheets)
            preview.warnings.append(
                "AI suggested mappings are highlighted for review and are not applied until approval"
            )
        return preview
    except Exception as exc:
        logger.warning("Inbound import preview failed", exc_info=True)
        message = client_message(exc, "Check that it is a valid CSV or XLSX file.")
        raise HTTPException(status_code=422, detail=f"Could not read import: {message}") from exc


async def process_inbound_import(
    db: AsyncSession,
    *,
    upload: UploadFile,
    name: str,
    user_id: str,
    organization_id: str,
    campaign_context: str = "",
    mapping_override: dict[str, Any] | None = None,
    assignment_policy: ImportAssignmentPolicy,
) -> InboundImportResponse:
    # Who handles the new leads is settled before the file is read, and checked again when the
    # queued job runs (the importer's teams or the rules may have changed in between).
    await _resolve_policy(db, organization_id, user_id, assignment_policy)
    filename = Path(upload.filename or "inbound-leads.xlsx").name
    if not filename.lower().endswith((".xlsx", ".csv")):
        raise HTTPException(status_code=415, detail="Upload a CSV or XLSX file")
    data = await upload.read(_MAX_FILE_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="File is empty, so nothing was imported.")
    if len(data) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Inbound import exceeds 50 MB")
    record = await import_jobs.enqueue(
        db,
        kind="inbound",
        data=data,
        filename=filename,
        name=name,
        user_id=user_id,
        organization_id=organization_id,
        campaign_context=campaign_context,
        mapping_override=mapping_override,
        assignment_policy=assignment_policy.model_dump(),
    )
    return _import_response(record)


async def _execute_inbound_import(
    db: AsyncSession,
    *,
    upload: UploadFile,
    name: str,
    user_id: str,
    organization_id: str,
    campaign_context: str = "",
    mapping_override: dict[str, Any] | None = None,
    assignment_policy: dict[str, Any] | None = None,
    _record: CrmInboundImport | None = None,
    _commit: Callable[[], Awaitable[None]] | None = None,
) -> InboundImportResponse:
    # Jobs queued before routing existed carry no policy: the importer keeps their leads.
    policy = ImportAssignmentPolicy.model_validate(assignment_policy or {"mode": "self"})
    pool_team, rules = await _resolve_policy(db, organization_id, user_id, policy)
    filename = Path(upload.filename or "inbound-leads.xlsx").name
    if not filename.lower().endswith((".xlsx", ".csv")):
        raise HTTPException(status_code=415, detail="Upload a CSV or XLSX file")
    data = await upload.read(_MAX_FILE_BYTES + 1)
    if len(data) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Inbound import exceeds 50 MB")
    campaign_context = campaign_context.strip()[:4_000]
    digest = hashlib.sha256(data + b"\0" + campaign_context.casefold().encode()).hexdigest()
    now = _utcnow()
    if _record is not None:
        record = _record
    else:
        existing_result = await inbound_repository.find_import_by_digest(
            db, digest, organization_id
        )
        if existing := existing_result:
            return _import_response(existing)

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
        inbound_repository.save(db, record)
        await db.commit()
        await db.refresh(record)
    summary = InboundImportSummary(
        assignment=InboundImportAssignmentSummary(
            mode=policy.mode,
            assignee_user_id=policy.assignee_user_id,
            team_id=pool_team,
        )
    )
    # Each new lead's routing decision: the person it should go to, the rule that chose them and
    # the lead's own language (for rules that route to its speakers only).
    routed: list[tuple[CrmInboundEnquiry, str | None, routing.RuleSnapshot | None, str | None]] = []
    imported_enquiries: list[CrmInboundEnquiry] = []
    imported_contacts: dict[int, CrmInboundContact] = {}
    try:
        rows, mapping = await run_in_thread(_file_rows, data, filename, mapping_override)
        mapping["campaign_context"] = campaign_context
        record.mapping = mapping
        summary.total_rows = len(rows)
        for sheet_mapping in mapping.get("sheets", []):
            fields = set(sheet_mapping.get("field_map", {}))
            if not ({"full_name", "first_name"} & fields):
                raise ImportInputError(
                    f"Map a full-name or first-name column for {sheet_mapping.get('sheet', 'the import')}"
                )
            if not ({"phone", "email", "whatsapp"} & fields):
                raise ImportInputError(
                    f"Map a phone, email, or WhatsApp column for {sheet_mapping.get('sheet', 'the import')}"
                )
        row_fingerprints: set[str] = set()
        for sheet, row_number, row in rows:
            first = _text(row.get("first_name"))
            last = _text(row.get("last_name"))
            full_name = _text(row.get("full_name")) or " ".join(
                part for part in (first, last) if part
            )
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
            # Campaign context describes provenance, not an individual's intent.
            # Only row fields and the person's message may establish observed facts.
            row_context = notes
            intent = _normalize_intent(row.get("intent"), row_context)
            criteria = _deterministic_criteria(row, row_context)
            redacted = _redact(row_context, [full_name, phone or "", email or ""])
            needs_ai = bool(row_context) and (
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
            review: list[str] = []
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
            inferred_data: dict[str, Any] = {}
            if ai_intent in {"buy", "rent", "sell", "let"} and intent is None:
                inferred_data["intent"] = ai_intent
            if ai_values:
                inferred_data["criteria"] = ai_values
            if intent is None:
                review.append("Intent was not explicitly supplied and must be qualified")
            if intent in {"buy", "rent"} and not criteria.get("locations"):
                review.append("Preferred location is missing")
            if confidence and confidence < 0.85:
                review.append("Message extraction should be reviewed")
            record_kind = "opportunity" if intent else "unqualified_contact"
            observed_data = {
                "intent": intent,
                "message": notes or None,
                "criteria": criteria,
                "source": _text(row.get("source")) or "Imported",
                "campaign": _text(row.get("campaign")) or record.name,
                "campaign_context": campaign_context or None,
            }
            enquiry_date = _parse_datetime(row.get("created_at"))
            enquiry = CrmInboundEnquiry(
                organization_id=organization_id,
                contact_id=contact.id or 0,
                source_import_id=record.id,
                created_by_user_id=user_id,
                record_kind=record_kind,
                intent=intent or "unknown",
                status="needs_review" if review else "new",
                source=_text(row.get("source")) or "Imported",
                campaign=_text(row.get("campaign")) or record.name,
                source_lead_id=source_id or None,
                source_sheet=sheet,
                source_row_number=row_number,
                enquiry_date=enquiry_date,
                criteria=criteria,
                strict_fields=strict,
                raw_notes=notes or None,
                observed_data=observed_data,
                inferred_data=inferred_data,
                confirmed_data={},
                qualification={},
                extraction_confidence=confidence or (0.8 if review else 0.9),
                extraction_evidence={
                    "redacted_ai": bool(ai_values),
                    "campaign_context_used": bool(campaign_context),
                    "classification_source": "row_or_message" if intent else "unknown",
                    "mapping": mapping,
                },
                review_reasons=review,
                first_response_due_at=enquiry_date + timedelta(minutes=_FIRST_RESPONSE_MINUTES),
                created_at=now,
                updated_at=now,
            )
            inbound_repository.save(db, enquiry)
            await db.flush()
            imported_enquiries.append(enquiry)
            imported_contacts[contact.id or 0] = contact
            if policy.mode == "self":
                routed.append((enquiry, user_id, None, None))
            elif policy.mode == "agent":
                routed.append((enquiry, policy.assignee_user_id, None, None))
            elif policy.mode == "rules":
                rule = routing.first_match(rules, enquiry, contact)
                language = routing.lead_language(contact) if rule and rule.speakers_only else None
                routed.append((enquiry, rule.destination_user_id if rule else None, rule, language))
            else:
                routed.append((enquiry, None, None, None))
            inbound_repository.save(
                db,
                CrmInboundActivity(
                    enquiry_id=enquiry.id or 0,
                    organization_id=organization_id,
                    user_id=user_id,
                    activity_type="imported",
                    body=f"Imported from {record.name}",
                    metadata_json={"sheet": sheet, "row": row_number},
                    created_at=now,
                ),
            )
            summary.imported += 1
            summary.needs_review += int(bool(review))
            if intent == "buy":
                summary.buyers += 1
            elif intent == "rent":
                summary.tenants += 1
            elif intent == "sell":
                summary.sellers += 1
            elif intent == "let":
                summary.landlords += 1
            else:
                summary.unqualified_contacts += 1
        enrichments = await _bulk_ownership_enrichments(
            db,
            organization_id=organization_id,
            contacts=list(imported_contacts.values()),
        )
        for enquiry in imported_enquiries:
            enrichment = enrichments.get(enquiry.contact_id, InboundOwnershipEnrichmentResponse())
            summary.owner_matches += int(enrichment.matched)
            summary.current_owners += int(enrichment.current_owner)
            summary.former_owners += int(enrichment.former_owner)
            summary.rental_owners += int(enrichment.rental_owner)
            summary.portfolio_owners += int(enrichment.multiple_property_owner)
            summary.high_priority += int(_lead_priority(enquiry, enrichment).band == "high")
        await _assign_imported(
            db, routed, summary.assignment, organization_id, user_id, record.id or 0, pool_team
        )
        record.status = "completed"
        record.summary = summary.model_dump()
        record.completed_at = _utcnow()
        inbound_repository.save(db, record)
        if _commit is not None:
            await _commit()
        else:
            await db.commit()
        await db.refresh(record)
    except Exception as exc:
        if _record is not None:
            await db.rollback()
            raise
        await db.rollback()
        await db.refresh(record)
        # Nothing was assigned: the rollback removed the leads and their history together.
        summary.assignment = InboundImportAssignmentSummary(
            mode=policy.mode,
            assignee_user_id=policy.assignee_user_id,
            team_id=pool_team,
        )
        record.status = "failed"
        logger.exception("Inbound import failed", extra={"import_id": record.id})
        record.error_message = client_message(exc, "The file could not be processed.")[:1_000]
        record.summary = summary.model_dump()
        record.completed_at = _utcnow()
        inbound_repository.save(db, record)
        await db.commit()
    return _import_response(record)


async def _resolve_policy(
    db: AsyncSession, organization_id: str, user_id: str, policy: ImportAssignmentPolicy
) -> tuple[str | None, list[routing.RuleSnapshot]]:
    """The team owning leads nobody receives, and the rules to apply, for this importer.

    An agent imports only for themselves ("self", whatever their teams); every other mode
    distributes leads and needs a manager or organization administrator.
    """
    scope = await assignment.load_scope(db, organization_id, user_id)
    if policy.mode != "self":
        assignment.require_assigner(scope)
    rules: list[routing.RuleSnapshot] = []
    pool_team = _pool_team(scope, policy)
    if policy.mode == "agent":
        pool_team = assignment.assignable_team(scope, policy.assignee_user_id or "", policy.team_id)
    elif policy.mode == "rules":
        rules = await routing.rule_snapshot(db, scope)
        if not rules:
            raise HTTPException(
                status_code=422, detail="There are no enabled routing rules for your teams"
            )
    return pool_team, rules


async def _assign_imported(
    db: AsyncSession,
    routed: list[tuple[CrmInboundEnquiry, str | None, routing.RuleSnapshot | None, str | None]],
    outcome: InboundImportAssignmentSummary,
    organization_id: str,
    user_id: str,
    import_id: int | None,
    pool_team: str | None,
) -> None:
    """Assign the new leads in the transaction that creates them.

    Eligibility is checked again here, after the file work: the importer's teams and every
    destination are reloaded, and a destination that left meanwhile gets no leads. A matching
    rule whose destination is unavailable leaves the lead unassigned; no later rule is tried.
    A "speakers only" rule gives a lead with a known language to the first person in its order
    recorded as speaking it (a lead with no language goes to the destination as usual).
    Leads nobody receives belong to `pool_team` (shared in its pool in "team" mode).
    """
    scope = await assignment.load_scope(db, organization_id, user_id)
    available: dict[tuple[str, frozenset[str]], bool] = {}
    now = _utcnow()
    self_team = assignment.own_team(scope) if outcome.mode == "self" else None

    def leave_unassigned(enquiry: CrmInboundEnquiry, reason: UnassignedReason) -> None:
        outcome.unassigned += 1
        outcome.unassigned_reasons[reason] = outcome.unassigned_reasons.get(reason, 0) + 1
        enquiry.team_id = pool_team
        inbound_repository.save(db, enquiry)

    async def eligible(target: str, teams: frozenset[str]) -> bool:
        key = (target, teams)
        if key not in available:
            available[key] = (
                # A self-import needs no team: only that the importer is still a member.
                await assignment.importer_still_member(db, scope)
                if outcome.mode == "self"
                else await assignment.destination_available(db, scope, target, teams)
            )
        return available[key]

    for enquiry, target, rule, language in routed:
        if target is None and outcome.mode == "team":
            assignment.record_assignment(
                db,
                enquiry,
                None,
                actor_user_id=user_id,
                reason="released",
                now=now,
                team_id=pool_team,
                shared=True,
                import_id=import_id,
            )
            outcome.unassigned += 1
            outcome.shared += 1
            continue
        if target is None:
            leave_unassigned(
                enquiry, "no_matching_rule" if outcome.mode == "rules" else "chosen_unassigned"
            )
            continue
        teams = frozenset({rule.team_id if rule else pool_team or ""})
        if rule and language is not None:
            # The first person in the rule's order who is still eligible and speaks the language.
            target = None
            for person in rule.order:
                if await agent_languages.speaks(
                    db, organization_id, person, language
                ) and await eligible(person, teams):
                    target = person
                    break
            if target is None:
                leave_unassigned(enquiry, "no_language_speaker")
                continue
        elif not await eligible(target, teams):
            leave_unassigned(enquiry, "destination_ineligible")
            continue
        assignment.record_assignment(
            db,
            enquiry,
            target,
            actor_user_id=user_id,
            reason="import_rule" if rule else "import_agent",
            now=now,
            team_id=rule.team_id if rule else (self_team if outcome.mode == "self" else pool_team),
            rule_id=rule.id if rule else None,
            rule_revision=rule.revision if rule else None,
            import_id=import_id,
        )
        if rule:
            rotation.start(db, enquiry, rule, holder=target, required_language=language, now=now)
        outcome.assigned += 1
        outcome.by_assignee[target] = outcome.by_assignee.get(target, 0) + 1
        if rule:
            outcome.by_rule[str(rule.id)] = outcome.by_rule.get(str(rule.id), 0) + 1


def _pool_team(scope: assignment.AssignmentScope, policy: ImportAssignmentPolicy) -> str | None:
    """The team that owns imported leads nobody receives: the one chosen, else the importer's
    only managed team. A manager of several teams must choose; "team" mode always needs one."""
    if policy.mode in {"self", "agent"}:
        return None
    if policy.team_id is not None:
        if policy.team_id not in scope.team_members:
            raise HTTPException(status_code=403, detail="You do not manage that team")
        return policy.team_id
    if len(scope.supervised_team_ids) == 1 and not scope.organization_admin:
        return next(iter(scope.supervised_team_ids))
    if scope.organization_admin and policy.mode != "team":
        return None  # administrators see unowned leads; nothing is guessed for them
    raise HTTPException(
        status_code=422,
        detail={"code": "TEAM_REQUIRED", "message": "Choose the team these leads belong to."},
    )


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


async def list_inbound_imports(
    db: AsyncSession, organization_id: str, *, user_id: str
) -> list[InboundImportResponse]:
    """Administrators see every import of the organization; anyone else their own imports."""
    scope = await assignment.load_scope(db, organization_id, user_id)
    result = await inbound_repository.list_imports(db, organization_id)
    return [
        _import_response(item)
        for item in result
        if scope.organization_admin or item.created_by_user_id == user_id
    ]


async def delete_inbound_import(
    db: AsyncSession, import_id: int, organization_id: str, *, user_id: str
) -> None:
    """Delete an import and every lead it created: only its importer or an administrator."""
    scope = await assignment.load_scope(db, organization_id, user_id)
    record = await inbound_repository.get_import_for_org(db, import_id, organization_id)
    if not record or not (scope.organization_admin or record.created_by_user_id == user_id):
        raise HTTPException(status_code=404, detail="Inbound import not found")
    input_key = await import_jobs.delete_input_for_import(db, record)
    imported_enquiries = await inbound_repository.list_import_contact_ids(
        db, import_id, organization_id
    )
    contact_ids = list(dict.fromkeys(imported_enquiries))
    await inbound_repository.delete_import_enquiries(db, import_id, organization_id)
    if contact_ids:
        await inbound_repository.delete_orphan_contacts(db, contact_ids, organization_id)
    await inbound_repository.delete_record(db, record)
    await db.commit()
    if input_key:
        await import_jobs.remove_input(input_key)
