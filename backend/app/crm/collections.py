"""Shareable property collections: who may manage them, their membership and their share link.

A collection belongs to an organization. Its creator manages it, and so do the organization's
owners; to everyone else it does not exist (404). The share token is never logged or returned
outside `share_url` / `rotate_token`.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import NamedTuple
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.crm.collection_models import (
    MAX_COLLECTION_ITEMS,
    CollectionCreate,
    CollectionDetailResponse,
    CollectionItemAdd,
    CollectionItemResponse,
    CollectionListResponse,
    CollectionResponse,
    CollectionUpdate,
    CrmCollection,
    CrmCollectionItem,
    ShareLinkResponse,
)
from app.crm.company_listings import listings_by_keys
from app.crm.documents import managed_listing

logger = logging.getLogger(__name__)

COLLECTION_NOT_FOUND = "collection_not_found"
COLLECTION_FULL = "collection_full"
SHARING_DISABLED = "sharing_disabled"


class CollectionActor(NamedTuple):
    user_id: str
    organization_id: str
    is_owner: bool
    name: str
    email: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log(action: str, collection_id: UUID, actor: CollectionActor) -> None:
    # Identifiers only: never the share token.
    logger.info(
        "crm.collection.%s",
        action,
        extra={
            "collection_id": str(collection_id),
            "organization_id": actor.organization_id,
            "user_id": actor.user_id,
        },
    )


def _visible(actor: CollectionActor):
    clause = CrmCollection.organization_id == actor.organization_id
    if actor.is_owner:
        return clause
    return clause & (CrmCollection.created_by_user_id == actor.user_id)


async def _get(
    db: AsyncSession, actor: CollectionActor, collection_id: UUID, *, lock: bool = False
) -> CrmCollection:
    statement = select(CrmCollection).where(CrmCollection.id == collection_id, _visible(actor))
    if lock:
        statement = statement.with_for_update()
    row = (await db.exec(statement)).first()
    if row is None:
        raise HTTPException(status_code=404, detail=COLLECTION_NOT_FOUND)
    return row


async def _item_count(db: AsyncSession, collection_id: UUID) -> int:
    return (
        await db.exec(
            select(func.count())
            .select_from(CrmCollectionItem)
            .where(CrmCollectionItem.collection_id == collection_id)
        )
    ).one()


def _response(row: CrmCollection, item_count: int) -> CollectionResponse:
    return CollectionResponse(
        id=row.id,
        name=row.name,
        sharing_enabled=row.sharing_enabled,
        item_count=item_count,
        created_by_user_id=row.created_by_user_id,
        agent_name=row.agent_name,
        agent_email=row.agent_email,
        agent_phone=row.agent_phone,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _item_response(item: CrmCollectionItem, listing=None) -> CollectionItemResponse:
    return CollectionItemResponse(
        id=item.id,
        source=item.source,
        listing_key=item.listing_key,
        listing_title=item.listing_title,
        added_at=item.added_at,
        listing=listing,
    )


async def list_collections(
    db: AsyncSession, *, actor: CollectionActor, limit: int, offset: int
) -> CollectionListResponse:
    total = (
        await db.exec(select(func.count()).select_from(CrmCollection).where(_visible(actor)))
    ).one()
    counts = (
        select(CrmCollectionItem.collection_id, func.count().label("n"))
        .group_by(CrmCollectionItem.collection_id)
        .subquery()
    )
    rows = (
        await db.exec(
            select(CrmCollection, func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.collection_id == CrmCollection.id)
            .where(_visible(actor))
            .order_by(col(CrmCollection.updated_at).desc(), col(CrmCollection.id))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return CollectionListResponse(
        items=[_response(row, int(count)) for row, count in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def create_collection(
    db: AsyncSession, *, actor: CollectionActor, payload: CollectionCreate
) -> CollectionResponse:
    now = _now()
    row = CrmCollection(
        organization_id=actor.organization_id,
        created_by_user_id=actor.user_id,
        name=payload.name,
        share_token=secrets.token_urlsafe(32),
        sharing_enabled=False,
        agent_name=actor.name,
        agent_email=actor.email or None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    _log("create", row.id, actor)
    return _response(row, 0)


async def get_collection(
    db: AsyncSession, *, actor: CollectionActor, collection_id: UUID
) -> CollectionDetailResponse:
    row = await _get(db, actor, collection_id)
    items = (
        await db.exec(
            select(CrmCollectionItem)
            .where(CrmCollectionItem.collection_id == collection_id)
            .order_by(col(CrmCollectionItem.added_at), col(CrmCollectionItem.id))
        )
    ).all()
    current = await listings_by_keys(
        db, actor.organization_id, [item.listing_key for item in items]
    )
    return CollectionDetailResponse(
        **_response(row, len(items)).model_dump(),
        items=[
            _item_response(
                item,
                found if (found := current.get(item.listing_key)) and found.managed else None,
            )
            for item in items
        ],
    )


async def update_collection(
    db: AsyncSession, *, actor: CollectionActor, collection_id: UUID, payload: CollectionUpdate
) -> CollectionResponse:
    row = await _get(db, actor, collection_id)
    # Only fields the client sent: an explicit null clears the optional contact fields.
    for field in payload.model_fields_set:
        setattr(row, field, getattr(payload, field))
    row.updated_at = _now()
    db.add(row)
    await db.commit()
    _log("update", row.id, actor)
    return _response(row, await _item_count(db, row.id))


async def delete_collection(
    db: AsyncSession, *, actor: CollectionActor, collection_id: UUID
) -> None:
    row = await _get(db, actor, collection_id)
    await db.delete(row)  # items go with it (ON DELETE CASCADE)
    await db.commit()
    _log("delete", collection_id, actor)


def _insert_item(db: AsyncSession, values: dict):
    dialect = postgresql if db.get_bind().dialect.name == "postgresql" else sqlite
    return (
        dialect.insert(CrmCollectionItem)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["collection_id", "source", "listing_key"])
        .returning(CrmCollectionItem.id)
    )


async def _existing_item(
    db: AsyncSession, collection_id: UUID, payload: CollectionItemAdd
) -> CrmCollectionItem | None:
    return (
        await db.exec(
            select(CrmCollectionItem).where(
                CrmCollectionItem.collection_id == collection_id,
                CrmCollectionItem.source == payload.source,
                CrmCollectionItem.listing_key == payload.listing_key,
            )
        )
    ).first()


async def _item(db: AsyncSession, item_id: UUID) -> CrmCollectionItem:
    return (await db.exec(select(CrmCollectionItem).where(CrmCollectionItem.id == item_id))).one()


async def add_item(
    db: AsyncSession, *, actor: CollectionActor, collection_id: UUID, payload: CollectionItemAdd
) -> tuple[CollectionItemResponse, bool]:
    listing = await managed_listing(db, actor.organization_id, payload.listing_key)
    # The row lock serializes concurrent adds, so the count below cannot go stale.
    row = await _get(db, actor, collection_id, lock=True)
    existing = await _existing_item(db, row.id, payload)
    if existing is not None:
        response = _item_response(existing, listing)
        await db.rollback()  # release the lock; rollback expires loaded rows
        return response, False
    if await _item_count(db, row.id) >= MAX_COLLECTION_ITEMS:
        await db.rollback()
        raise HTTPException(status_code=409, detail=COLLECTION_FULL)

    now = _now()
    item_id = uuid4()
    inserted = (
        await db.exec(
            _insert_item(
                db,
                {
                    "id": item_id,
                    "collection_id": row.id,
                    "organization_id": row.organization_id,
                    "source": payload.source,
                    "listing_key": payload.listing_key,
                    "listing_title": listing.title,
                    "added_by_user_id": actor.user_id,
                    "added_at": now,
                },
            )
        )
    ).first()
    if inserted is None:  # Lost a race the lock should have prevented: report the existing row.
        await db.rollback()
        return _item_response(await _existing_item(db, row.id, payload), listing), False
    await db.exec(update(CrmCollection).where(CrmCollection.id == row.id).values(updated_at=now))
    await db.commit()
    _log("add_item", row.id, actor)
    return _item_response(await _item(db, item_id), listing), True


async def remove_item(
    db: AsyncSession, *, actor: CollectionActor, collection_id: UUID, item_id: UUID
) -> None:
    row = await _get(db, actor, collection_id)
    result = await db.exec(
        delete(CrmCollectionItem).where(
            CrmCollectionItem.id == item_id, CrmCollectionItem.collection_id == row.id
        )
    )
    if result.rowcount:
        await db.exec(
            update(CrmCollection).where(CrmCollection.id == row.id).values(updated_at=_now())
        )
        _log("remove_item", row.id, actor)
    await db.commit()


def _share_link(token: str) -> ShareLinkResponse:
    base = str(settings.FRONTEND_URL).rstrip("/")
    return ShareLinkResponse(url=f"{base}/collections/{token}")


async def share_url(
    db: AsyncSession, *, actor: CollectionActor, collection_id: UUID
) -> ShareLinkResponse:
    row = await _get(db, actor, collection_id)
    if not row.sharing_enabled:
        raise HTTPException(status_code=409, detail=SHARING_DISABLED)
    return _share_link(row.share_token)


async def rotate_token(
    db: AsyncSession, *, actor: CollectionActor, collection_id: UUID
) -> ShareLinkResponse:
    row = await _get(db, actor, collection_id)
    row.share_token = secrets.token_urlsafe(32)
    row.updated_at = _now()
    db.add(row)
    await db.commit()
    _log("rotate_token", row.id, actor)
    return _share_link(row.share_token)
