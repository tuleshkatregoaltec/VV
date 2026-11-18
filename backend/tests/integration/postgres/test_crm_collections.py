"""Collection constraints against the migrated PostgreSQL schema."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from crm_document_helpers import listing
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import collections
from app.crm.collection_models import (
    CollectionItemAdd,
    CrmCollection,
    CrmCollectionItem,
)
from app.crm.collections import CollectionActor
from app.organization.models import Organization


def _now():
    return datetime.now(timezone.utc)


async def _org(session) -> str:
    org = str(uuid4())
    session.add(Organization(id=org, name=org))
    await session.commit()
    return org


async def _collection(session, org: str) -> CrmCollection:
    row = CrmCollection(
        organization_id=org,
        created_by_user_id="u1",
        name="Marina picks",
        share_token=uuid4().hex + uuid4().hex[:11],
        agent_name="Agent One",
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(row)
    await session.commit()
    return row


def _item(collection_id, org: str, key: str = "L1") -> CrmCollectionItem:
    return CrmCollectionItem(
        collection_id=collection_id,
        organization_id=org,
        source="property_finder",
        listing_key=key,
        listing_title="Marina Gate 2BR",
        added_by_user_id="u1",
        added_at=_now(),
    )


async def test_duplicate_listing_in_collection_rejected(pg_session):
    org = await _org(pg_session)
    col = await _collection(pg_session, org)
    pg_session.add(_item(col.id, org))
    await pg_session.commit()
    pg_session.add(_item(col.id, org))
    with pytest.raises(IntegrityError):
        await pg_session.commit()
    await pg_session.rollback()


async def test_same_listing_in_two_collections_allowed(pg_session):
    org = await _org(pg_session)
    first = await _collection(pg_session, org)
    second = await _collection(pg_session, org)
    pg_session.add(_item(first.id, org))
    pg_session.add(_item(second.id, org))
    await pg_session.commit()


async def test_item_cannot_point_at_other_org_collection(pg_session):
    org_a = await _org(pg_session)
    org_b = await _org(pg_session)
    col = await _collection(pg_session, org_a)
    pg_session.add(_item(col.id, org_b))
    with pytest.raises(IntegrityError):
        await pg_session.commit()
    await pg_session.rollback()


async def test_deleting_collection_cascades_items(pg_session):
    org = await _org(pg_session)
    col = await _collection(pg_session, org)
    pg_session.add(_item(col.id, org))
    await pg_session.commit()
    await pg_session.delete(col)
    await pg_session.commit()
    count = await pg_session.scalar(
        select(func.count())
        .select_from(CrmCollectionItem)
        .where(CrmCollectionItem.collection_id == col.id)
    )
    assert count == 0


ACTOR = CollectionActor("u1", "", False, "Agent One", "one@example.com")


@pytest.fixture
def listings(monkeypatch):
    async def fake_managed(db, organization_id, listing_key):
        return listing(listing_key)

    monkeypatch.setattr(collections, "managed_listing", fake_managed)


async def _concurrent_adds(url, org, collection_id, keys):
    """One session per add, as two requests on two connections would be."""
    engine = create_async_engine(url)
    actor = ACTOR._replace(organization_id=org)

    async def one(key):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                return await collections.add_item(
                    session,
                    actor=actor,
                    collection_id=collection_id,
                    payload=CollectionItemAdd(source="property_finder", listing_key=key),
                )
            except HTTPException as error:
                return error

    try:
        return await asyncio.gather(*(one(key) for key in keys))
    finally:
        await engine.dispose()


async def _count(session, collection_id) -> int:
    await session.rollback()  # fresh snapshot
    return await session.scalar(
        select(func.count())
        .select_from(CrmCollectionItem)
        .where(CrmCollectionItem.collection_id == collection_id)
    )


async def test_concurrent_duplicate_adds_produce_one_item(pg_session, postgres_test_url, listings):
    org = await _org(pg_session)
    col = await _collection(pg_session, org)
    first, second = await _concurrent_adds(postgres_test_url, org, col.id, ["L1", "L1"])
    assert sorted([first[1], second[1]]) == [False, True]
    assert first[0].id == second[0].id
    assert await _count(pg_session, col.id) == 1


async def test_concurrent_adds_respect_limit(pg_session, postgres_test_url, listings):
    org = await _org(pg_session)
    col = await _collection(pg_session, org)
    pg_session.add_all([_item(col.id, org, f"S{n}") for n in range(49)])
    await pg_session.commit()
    results = await _concurrent_adds(postgres_test_url, org, col.id, ["A", "B"])
    errors = [r for r in results if isinstance(r, HTTPException)]
    assert len(errors) == 1 and (errors[0].status_code, errors[0].detail) == (
        409,
        "collection_full",
    )
    assert len(results) - len(errors) == 1
    assert await _count(pg_session, col.id) == 50


async def test_concurrent_adds_of_different_listings_both_persist(
    pg_session, postgres_test_url, listings
):
    org = await _org(pg_session)
    col = await _collection(pg_session, org)
    results = await _concurrent_adds(postgres_test_url, org, col.id, ["A", "B"])
    assert [r[1] for r in results] == [True, True]
    assert await _count(pg_session, col.id) == 2
