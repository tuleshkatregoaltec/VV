"""Listing documents: who may see a listing's private information, saving it, and its PDFs.

Only listings of the organization's connected Property Finder company carry private owner and
agreement information. Anything else answers exactly like a listing that does not exist.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import anyio
from fastapi import HTTPException
from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.company_listings import get_company_listing
from app.crm.document_models import (
    DOC_TYPES,
    CrmGeneratedDocument,
    CrmListingDocumentInfo,
    DocType,
    DocumentDownloadResponse,
    DocumentFields,
    GeneratedDocumentListResponse,
    GeneratedDocumentResponse,
    GenerateDocumentRequest,
    ListingDocumentInfoResponse,
    ListingDocumentInfoUpdate,
)
from app.crm.document_rendering import RenderError, render_pdf
from app.crm.document_storage import signed_pdf_url, store_pdf
from app.crm.document_templates import TEMPLATES, build_snapshot, missing_fields
from app.crm.models import CrmCompanyListingDetail

logger = logging.getLogger(__name__)

SOURCE = "property_finder"
LISTING_NOT_FOUND = "Listing not found"
DOCUMENT_NOT_FOUND = "Document not found"
STALE_REVISION = "stale_revision"
# Per API process: rendering is CPU-bound and runs in worker threads.
RENDER_CONCURRENCY = 2
RENDER_TIMEOUT_SECONDS = 30
_render_slots = asyncio.Semaphore(RENDER_CONCURRENCY)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def managed_listing(
    db: AsyncSession, organization_id: str, listing_key: str
) -> CrmCompanyListingDetail:
    """The listing, if this organization manages it; otherwise the same 404 as a missing one."""
    listing = await get_company_listing(db, organization_id, listing_key)
    if listing is None or not listing.managed:
        raise HTTPException(status_code=404, detail=LISTING_NOT_FOUND)
    return listing


async def info_record(
    db: AsyncSession, *, organization_id: str, listing_key: str
) -> CrmListingDocumentInfo | None:
    result = await db.exec(
        select(CrmListingDocumentInfo).where(
            CrmListingDocumentInfo.organization_id == organization_id,
            CrmListingDocumentInfo.source == SOURCE,
            CrmListingDocumentInfo.listing_key == listing_key,
        )
    )
    return result.first()


def _response(
    listing: CrmCompanyListingDetail, record: CrmListingDocumentInfo | None
) -> ListingDocumentInfoResponse:
    if record is None:
        return ListingDocumentInfoResponse(listing=listing, fields=DocumentFields(), revision=0)
    return ListingDocumentInfoResponse(
        listing=listing,
        fields=DocumentFields.model_validate(record.fields),
        revision=record.revision,
    )


async def get_document_info(
    db: AsyncSession, *, organization_id: str, listing_key: str
) -> ListingDocumentInfoResponse:
    listing = await managed_listing(db, organization_id, listing_key)
    record = await info_record(db, organization_id=organization_id, listing_key=listing_key)
    return _response(listing, record)


async def save_document_info(
    db: AsyncSession, *, organization_id: str, user_id: str, payload: ListingDocumentInfoUpdate
) -> ListingDocumentInfoResponse:
    """Save the information; a save based on an older revision is refused, never merged."""
    listing = await managed_listing(db, organization_id, payload.listing_key)
    fields = payload.fields.model_dump(mode="json")
    now = _now()
    if payload.expected_revision == 0:
        db.add(
            CrmListingDocumentInfo(
                organization_id=organization_id,
                source=SOURCE,
                listing_key=payload.listing_key,
                listing_title=listing.title,
                fields=fields,
                revision=1,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=409, detail=STALE_REVISION) from None
    else:
        result = await db.exec(
            update(CrmListingDocumentInfo)
            .where(
                CrmListingDocumentInfo.organization_id == organization_id,
                CrmListingDocumentInfo.source == SOURCE,
                CrmListingDocumentInfo.listing_key == payload.listing_key,
                CrmListingDocumentInfo.revision == payload.expected_revision,
            )
            .values(
                fields=fields,
                listing_title=listing.title,
                revision=CrmListingDocumentInfo.revision + 1,
                updated_by_user_id=user_id,
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            await db.rollback()
            raise HTTPException(status_code=409, detail=STALE_REVISION)
        await db.commit()
    record = await info_record(db, organization_id=organization_id, listing_key=payload.listing_key)
    if record is not None:
        await db.refresh(record)
    return _response(listing, record)


async def _render(doc_type: str, snapshot: dict[str, Any]) -> bytes:
    """Render off the event loop, a bounded number at a time, within the request deadline."""
    async with _render_slots, asyncio.timeout(RENDER_TIMEOUT_SECONDS):
        return await anyio.to_thread.run_sync(
            render_pdf, doc_type, snapshot, abandon_on_cancel=True
        )


async def _by_idempotency_key(
    db: AsyncSession, organization_id: str, key: UUID
) -> CrmGeneratedDocument | None:
    result = await db.exec(
        select(CrmGeneratedDocument).where(
            CrmGeneratedDocument.organization_id == organization_id,
            CrmGeneratedDocument.idempotency_key == key,
        )
    )
    return result.first()


def _document_response(document: CrmGeneratedDocument) -> GeneratedDocumentResponse:
    # Company and area as printed on the PDF, from its snapshot: stable after the listing changes.
    printed = (document.snapshot or {}).get("listing") or {}
    response = GeneratedDocumentResponse.model_validate(document, from_attributes=True)
    response.company_name = printed.get("broker_name")
    response.listing_area = printed.get("area_name")
    return response


async def _finish(db: AsyncSession, document: CrmGeneratedDocument, **values: Any) -> None:
    for name, value in values.items():
        setattr(document, name, value)
    document.updated_at = _now()
    db.add(document)
    await db.commit()


async def generate_document(
    db: AsyncSession, *, organization_id: str, user_id: str, payload: GenerateDocumentRequest
) -> tuple[GeneratedDocumentResponse, bool]:
    """Generate one PDF; returns (document, created). A repeated key returns the first result."""
    existing = await _by_idempotency_key(db, organization_id, payload.idempotency_key)
    if existing is not None:
        return _document_response(existing), False

    listing = await managed_listing(db, organization_id, payload.listing_key)
    record = await info_record(db, organization_id=organization_id, listing_key=payload.listing_key)
    if record is None or record.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail=STALE_REVISION)
    spec = TEMPLATES[payload.doc_type]
    snapshot = build_snapshot(
        listing, DocumentFields.model_validate(record.fields), payload.doc_type
    )
    missing = missing_fields(payload.doc_type, snapshot)
    if missing:
        raise HTTPException(status_code=422, detail={"code": "missing_fields", "fields": missing})

    now = _now()
    document = CrmGeneratedDocument(
        organization_id=organization_id,
        info_id=record.id,
        source=SOURCE,
        listing_key=payload.listing_key,
        listing_title=listing.title,
        doc_type=payload.doc_type,
        template_version=spec.version,
        snapshot=snapshot,
        input_revision=record.revision,
        idempotency_key=payload.idempotency_key,
        status="generating",
        created_by_user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(document)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent retry with the same key won; answer with its document.
        await db.rollback()
        winner = await _by_idempotency_key(db, organization_id, payload.idempotency_key)
        if winner is None:
            raise
        return _document_response(winner), False

    started = time.perf_counter()
    failure: str | None = None
    try:
        pdf = await _render(payload.doc_type, snapshot)
    except TimeoutError:
        failure = "render_timeout"
    except RenderError:
        failure = "render_failed"
    if failure is None:
        try:
            key = await store_pdf(
                organization_id, document.id, f"{payload.doc_type}-{payload.listing_key}.pdf", pdf
            )
        except Exception:
            failure = "storage_failed"
    if failure is None:
        await _finish(
            db,
            document,
            status="ready",
            object_key=key,
            size_bytes=len(pdf),
            sha256=hashlib.sha256(pdf).hexdigest(),
        )
    else:
        await _finish(db, document, status="failed", failure_code=failure)
    # No owner details, agreement terms or links in logs: identifiers and outcome only.
    logger.info(
        "crm document %s",
        document.status,
        extra={
            "document_id": str(document.id),
            "user_id": user_id,
            "doc_type": payload.doc_type,
            "template_version": spec.version,
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "failure_code": failure,
        },
    )
    if failure is not None:
        raise HTTPException(
            status_code=502, detail={"code": failure, "document_id": str(document.id)}
        )
    return _document_response(document), True


async def reconcile_stale_documents(
    db: AsyncSession, *, older_than: timedelta = timedelta(minutes=10)
) -> int:
    """Mark documents left `generating` by a crashed process as failed; returns how many."""
    now = _now()
    result = await db.exec(
        update(CrmGeneratedDocument)
        .where(
            CrmGeneratedDocument.status == "generating",
            CrmGeneratedDocument.updated_at < now - older_than,
        )
        .values(status="failed", failure_code="interrupted", updated_at=now)
    )
    await db.commit()
    return result.rowcount


async def list_documents(
    db: AsyncSession,
    *,
    organization_id: str,
    listing_key: str | None = None,
    doc_type: DocType | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> GeneratedDocumentListResponse:
    """The organization's documents, newest first. Independent of the listing still existing."""
    conditions = [
        CrmGeneratedDocument.organization_id == organization_id,
        # Older rows may hold retired types (the listing brochure); they are no longer shown.
        CrmGeneratedDocument.doc_type.in_(DOC_TYPES),  # type: ignore[attr-defined]
    ]
    if listing_key:
        conditions.append(CrmGeneratedDocument.listing_key == listing_key)
    if doc_type:
        conditions.append(CrmGeneratedDocument.doc_type == doc_type)
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(CrmGeneratedDocument.listing_title).like(term),
                CrmGeneratedDocument.listing_key.like(term),
            )
        )
    total = (
        await db.exec(select(func.count()).select_from(CrmGeneratedDocument).where(*conditions))
    ).one()
    rows = (
        await db.exec(
            select(CrmGeneratedDocument)
            .where(*conditions)
            .order_by(CrmGeneratedDocument.created_at.desc(), CrmGeneratedDocument.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return GeneratedDocumentListResponse(
        items=[_document_response(row) for row in rows], total=total, limit=limit, offset=offset
    )


async def _owned_document(
    db: AsyncSession, organization_id: str, document_id: UUID
) -> CrmGeneratedDocument:
    document = await db.get(CrmGeneratedDocument, document_id)
    if (
        document is None
        or document.organization_id != organization_id
        or document.doc_type not in DOC_TYPES
    ):
        raise HTTPException(status_code=404, detail=DOCUMENT_NOT_FOUND)
    return document


async def get_document(
    db: AsyncSession, *, organization_id: str, document_id: UUID
) -> GeneratedDocumentResponse:
    return _document_response(await _owned_document(db, organization_id, document_id))


async def download_document(
    db: AsyncSession, *, organization_id: str, document_id: UUID, inline: bool = False
) -> DocumentDownloadResponse:
    """A fresh short-lived link, issued only after the organization's access is checked."""
    document = await _owned_document(db, organization_id, document_id)
    if document.status != "ready" or not document.object_key:
        raise HTTPException(status_code=409, detail="not_ready")
    url, expires_at = await signed_pdf_url(document.object_key, inline=inline)
    return DocumentDownloadResponse(url=url, expires_at=expires_at)
