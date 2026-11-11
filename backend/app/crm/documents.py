"""Listing documents: who may see a listing's private information, saving it, and its PDFs.

Only listings of the organization's connected Property Finder company carry private owner and
agreement information. Anything else answers exactly like a listing that does not exist.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.company_listings import get_company_listing
from app.crm.document_models import (
    CrmListingDocumentInfo,
    DocumentFields,
    ListingDocumentInfoResponse,
    ListingDocumentInfoUpdate,
)
from app.crm.models import CrmCompanyListingDetail

SOURCE = "property_finder"
LISTING_NOT_FOUND = "Listing not found"
STALE_REVISION = "stale_revision"


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
