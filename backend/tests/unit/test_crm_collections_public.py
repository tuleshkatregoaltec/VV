from datetime import datetime, timezone

import pytest
from clickhouse_connect.driver.exceptions import OperationalError
from crm_document_helpers import listing
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.postgres.models  # noqa: F401 - registers every table
from app.crm import collections
from app.crm.collection_models import (
    CollectionCreate,
    CollectionUpdate,
    CrmCollection,
    CrmCollectionItem,
)
from app.crm.collections import CollectionActor
from app.organization.models import Organization

ACTOR = CollectionActor("u1", "org1", True, "Navi Agent", "navi@example.com")


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Organization(id="org1", name="o", subscription_status="active"))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.fixture
def current(monkeypatch):
    found = {}

    async def fake(db, organization_id, keys):
        return {k: found[k] for k in keys if k in found}

    monkeypatch.setattr(collections, "listings_by_keys", fake)
    return found


async def shared(db, keys=(), *, enabled=True):
    created = await collections.create_collection(
        db, actor=ACTOR, payload=CollectionCreate(name="Picks")
    )
    row = await db.get(CrmCollection, created.id)
    row.sharing_enabled = enabled
    for n, key in enumerate(keys):
        db.add(
            CrmCollectionItem(
                collection_id=row.id,
                organization_id="org1",
                source="property_finder",
                listing_key=key,
                listing_title="snap",
                added_by_user_id="u1",
                added_at=datetime(2026, 11, 1, 0, n, tzinfo=timezone.utc),
            )
        )
    await db.commit()
    return row.share_token


async def test_public_unknown_token_404(db, current):
    with pytest.raises(HTTPException) as exc:
        await collections.public_collection(db, "x" * 43)
    assert (exc.value.status_code, exc.value.detail) == (404, "collection_unavailable")


async def test_public_disabled_404_same_body(db, current):
    token = await shared(db, enabled=False)
    with pytest.raises(HTTPException) as exc:
        await collections.public_collection(db, token)
    assert (exc.value.status_code, exc.value.detail) == (404, "collection_unavailable")


async def test_public_suspended_org_404(db, current):
    token = await shared(db)
    (await db.get(Organization, "org1")).subscription_status = "past_due"
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await collections.public_collection(db, token)
    assert (exc.value.status_code, exc.value.detail) == (404, "collection_unavailable")


async def test_public_trialing_org_allowed(db, current):
    token = await shared(db)
    (await db.get(Organization, "org1")).subscription_status = "trialing"
    await db.commit()
    assert (await collections.public_collection(db, token)).items == []


async def test_public_empty_collection_returns_empty_items(db, current):
    result = await collections.public_collection(db, await shared(db))
    assert result.items == []
    assert result.name == "Picks"
    assert result.agent.name == "Navi Agent"


async def test_public_marks_missing_listing_unavailable(db, current):
    current["1"] = listing("1")
    result = await collections.public_collection(db, await shared(db, ["1", "gone"]))
    assert [i.status for i in result.items] == ["available", "unavailable"]
    gone = result.items[1].model_dump(exclude={"status", "source_label"})
    assert all(v in (None, []) for v in gone.values())


async def test_public_hides_items_no_longer_managed(db, current):
    current["1"] = listing("1", managed=False)
    result = await collections.public_collection(db, await shared(db, ["1"]))
    item = result.items[0]
    assert item.status == "unavailable"
    assert item.price_aed is None and item.title is None and item.photos == []


async def test_public_orders_items_by_added_at(db, current):
    for key in ("1", "2", "3"):
        current[key] = listing(key, title=f"T{key}")
    result = await collections.public_collection(db, await shared(db, ["3", "1", "2"]))
    assert [i.title for i in result.items] == ["T3", "T1", "T2"]


async def test_public_warehouse_error_is_503(db, current, monkeypatch):
    token = await shared(db, ["1"])

    async def down(db, organization_id, keys):
        raise OperationalError("down")

    monkeypatch.setattr(collections, "listings_by_keys", down)
    with pytest.raises(HTTPException) as exc:
        await collections.public_collection(db, token)
    assert (exc.value.status_code, exc.value.detail) == (503, "listings_unavailable")


async def test_public_os_error_is_503(db, current, monkeypatch):
    token = await shared(db, ["1"])

    async def down(db, organization_id, keys):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(collections, "listings_by_keys", down)
    with pytest.raises(HTTPException) as exc:
        await collections.public_collection(db, token)
    assert exc.value.status_code == 503


async def test_public_response_keys_are_allowlist(db, current):
    current["1"] = listing("1")
    token = await shared(db, ["1"])
    row = (await db.exec(select(CrmCollection))).one()
    await collections.update_collection(
        db,
        actor=ACTOR,
        collection_id=row.id,
        payload=CollectionUpdate(agent_phone="+971500000000"),
    )
    body = (await collections.public_collection(db, token)).model_dump()
    assert set(body) == {"name", "agent", "items", "fetched_at"}
    assert set(body["agent"]) == {"name", "email", "phone"}
    assert set(body["items"][0]) == {
        "status", "title", "area_name", "building_name", "property_type", "bedrooms",
        "size_sqft", "price_aed", "mode", "rent_period", "photos", "description",
        "source_label", "updated_at",
    }  # fmt: skip


async def test_public_rejects_non_https_photo(db, current):
    detail = listing("1")
    detail.photos = ["http://x/a.jpg", "https://x/b.jpg", "javascript:alert(1)", "//x/c.jpg"]
    current["1"] = detail
    result = await collections.public_collection(db, await shared(db, ["1"]))
    assert result.items[0].photos == ["https://x/b.jpg"]
