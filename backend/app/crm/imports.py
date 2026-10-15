from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import import_repository
from app.crm.ai import _llm_mapping
from app.crm.identity import (
    _candidate_owner_key,
    _dedupe_candidates,
    _drop_candidates_without_unit,
)
from app.crm.import_models import (
    CrmContactImport,
    CrmContactImportResponse,
    CrmContactImportSummary,
    CrmContactList,
    CrmPropertyContactClaim,
    CrmSheetMapping,
)
from app.crm.import_parsing import (
    _inspect_csv,
    _inspect_xlsx,
    _mapping_response,
    _parse_csv,
    _parse_xlsx,
    _summary,
)
from app.crm.owners import _invalidate_owner_summary_cache
from app.crm.ownership import (
    _apply_evidence,
    _recover_property_identity_from_near_transaction,
    _recover_property_identity_from_transaction,
    _rental_evidence,
    _sales_evidence,
)
from app.crm.workspaces import _enrich_workspaces

logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 50 * 1024 * 1024
_EMPTY_FILE = "File is empty, so nothing was imported."


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
        raise HTTPException(status_code=400, detail=_EMPTY_FILE)
    if len(data) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="The uploaded file exceeds 50 MB")
    sha256 = hashlib.sha256(data).hexdigest()
    existing_result = await import_repository.find_import_by_digest(db, organization_id, sha256)
    existing = existing_result
    if existing:
        return await _import_response(db, existing)

    now = datetime.now(timezone.utc)
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
    import_repository.save(db, record)
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
        if not total_rows:
            # Nothing to import: remove the record so no empty import or list is left behind.
            await import_repository.delete_record(db, record)
            await db.commit()
            raise HTTPException(status_code=400, detail=_EMPTY_FILE)
        await _recover_property_identity_from_transaction(candidates)
        await _recover_property_identity_from_near_transaction(candidates)
        sales = await _sales_evidence(candidates)
        rentals = await _rental_evidence(candidates)
        for candidate in candidates:
            _apply_evidence(candidate, sales=sales, rentals=rentals)
        candidates, dropped_no_unit = _drop_candidates_without_unit(candidates)
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
        import_repository.save(db, contact_list)
        await db.flush()
        if contact_list.id is None:
            raise RuntimeError("Contact list could not be created")

        for start in range(0, len(candidates), 1_000):
            import_repository.save_all(
                db,
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
                ],
            )
            await db.flush()

        await _enrich_workspaces(
            db,
            candidates=candidates,
            user_id=user_id,
            organization_id=organization_id,
            list_name=record.name,
        )
        summary = _summary(candidates, total_rows, duplicate_rows_collapsed, dropped_no_unit)
        record.status = "completed"
        record.mapping = {"sheets": [_mapping_response(profile) for profile in profiles]}
        record.summary = summary.model_dump()
        record.completed_at = datetime.now(timezone.utc)
        import_repository.save(db, record)
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
        record.completed_at = datetime.now(timezone.utc)
        import_repository.save(db, record)
        await db.commit()
        raise HTTPException(status_code=422, detail=f"Import failed: {exc}") from exc


async def _import_response(
    db: AsyncSession,
    record: CrmContactImport,
) -> CrmContactImportResponse:
    list_result = await import_repository.find_import_list(db, record)
    contact_list = list_result
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
    result = await import_repository.list_imports(db, organization_id)
    return [await _import_response(db, record) for record in result]


async def rename_contact_import(
    db: AsyncSession,
    *,
    import_id: int,
    name: str,
    organization_id: str,
) -> CrmContactImportResponse:
    result = await import_repository.get_import_for_org(db, import_id, organization_id)
    record = result
    if not record:
        raise HTTPException(status_code=404, detail="Owner-data import not found")
    cleaned = name.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Import name cannot be empty")
    record.name = cleaned[:200]
    import_repository.save(db, record)
    list_result = await import_repository.find_import_list_for_org(db, import_id, organization_id)
    contact_list = list_result
    if contact_list:
        contact_list.name = record.name
        contact_list.updated_at = datetime.now(timezone.utc)
        import_repository.save(db, contact_list)
    await db.commit()
    await db.refresh(record)
    return await _import_response(db, record)


async def delete_contact_import(
    db: AsyncSession,
    *,
    import_id: int,
    organization_id: str,
) -> None:
    result = await import_repository.get_import_for_org(db, import_id, organization_id)
    record = result
    if not record:
        raise HTTPException(status_code=404, detail="Owner-data import not found")

    # Remove only records published by this import. Agent-maintained lead
    # workspaces, notes, and manually saved properties are intentionally kept.
    await import_repository.delete_import_claims(db, import_id, organization_id)
    await import_repository.delete_import_lists(db, import_id, organization_id)
    await import_repository.delete_record(db, record)
    await db.commit()
    _invalidate_owner_summary_cache(organization_id)
