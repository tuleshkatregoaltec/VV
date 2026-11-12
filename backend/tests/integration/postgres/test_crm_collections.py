"""Collection constraints against the migrated PostgreSQL schema."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.crm.collection_models import CrmCollection, CrmCollectionItem
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
    count = await pg_session.scalar(select(func.count()).select_from(CrmCollectionItem))
    assert count == 0
