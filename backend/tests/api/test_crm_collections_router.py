from uuid import uuid4

import pytest
from clickhouse_connect.driver.exceptions import OperationalError
from crm_document_helpers import listing
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import app.postgres.models  # noqa: F401 - registers every table
from app.crm import collections
from app.crm.collection_models import CollectionCreate, CollectionItemAdd
from app.crm.collections import CollectionActor
from app.organization.models import Organization
from app.postgres import get_db_session

BASE = "/api/v1/crm/collections"
ITEM = {"source": "property_finder", "listing_key": "123"}
# The mocked signed-in user (tests/conftest.py): user "test-user-id", organization "1".
MINE = CollectionActor("test-user-id", "1", True, "Test User", "test@example.com")
FOREIGN = CollectionActor("eve", "2", True, "Eve", "eve@example.com")


@pytest.fixture(autouse=True)
def no_postgres_actor_context(monkeypatch):
    """CRM routes stamp each transaction with set_config (PostgreSQL audit context); this
    in-memory SQLite has no such function, and these tests are not about auditing."""

    async def skip(db):
        return None

    monkeypatch.setattr("app.crm.router.apply_actor_context", skip)


@pytest.fixture
async def db(client):
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        for org in ("1", "2"):
            session.add(Organization(id=org, name=org))
        await session.commit()

        async def override():
            yield session

        app.dependency_overrides[get_db_session] = override
        yield session
    await engine.dispose()


@pytest.fixture
def listings(monkeypatch):
    current = {str(n): listing(str(n)) for n in range(1, 200)}

    async def fake_managed(db, organization_id, listing_key):
        found = current.get(listing_key)
        if found is None:
            raise HTTPException(status_code=404, detail="Listing not found")
        return found

    async def fake_by_keys(db, organization_id, keys):
        return {key: current[key] for key in keys if key in current}

    monkeypatch.setattr(collections, "managed_listing", fake_managed)
    monkeypatch.setattr(collections, "listings_by_keys", fake_by_keys)
    return current


async def make(db, actor=MINE, name="Picks"):
    return await collections.create_collection(db, actor=actor, payload=CollectionCreate(name=name))


async def test_routes_require_auth(client_no_auth):
    some = uuid4()
    calls = [
        ("GET", BASE, None),
        ("POST", BASE, {"name": "x"}),
        ("GET", f"{BASE}/{some}", None),
        ("PATCH", f"{BASE}/{some}", {"name": "x"}),
        ("DELETE", f"{BASE}/{some}", None),
        ("PUT", f"{BASE}/{some}/items", ITEM),
        ("DELETE", f"{BASE}/{some}/items/{uuid4()}", None),
        ("POST", f"{BASE}/{some}/share-link", None),
        ("POST", f"{BASE}/{some}/share-link/rotate", None),
    ]
    for method, url, body in calls:
        response = await client_no_auth.request(method, url, json=body)
        assert response.status_code == 401, (method, url)


async def test_create_list_detail_update_delete(client, db, listings):
    created = await client.post(BASE, json={"name": "  Marina picks "})
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Marina picks"
    assert body["agent_name"] == "Test User"
    assert body["agent_email"] == "test@example.com"
    cid = body["id"]

    assert (await client.get(BASE, params={"limit": 10})).json()["total"] == 1
    assert (await client.get(f"{BASE}/{cid}")).json()["items"] == []

    patched = await client.patch(f"{BASE}/{cid}", json={"sharing_enabled": True})
    assert patched.status_code == 200
    assert patched.json()["sharing_enabled"] is True

    assert (await client.delete(f"{BASE}/{cid}")).status_code == 204
    assert (await client.get(f"{BASE}/{cid}")).status_code == 404


async def test_list_limit_is_bounded(client, db):
    assert (await client.get(BASE, params={"limit": 101})).status_code == 422
    assert (await client.get(BASE, params={"limit": 0})).status_code == 422


async def test_put_item_201_then_200(client, db, listings):
    cid = (await make(db)).id

    first = await client.put(f"{BASE}/{cid}/items", json=ITEM)
    second = await client.put(f"{BASE}/{cid}/items", json=ITEM)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert (await client.get(f"{BASE}/{cid}")).json()["item_count"] == 1


async def test_delete_item_twice_is_204(client, db, listings):
    cid = (await make(db)).id
    item_id = (await client.put(f"{BASE}/{cid}/items", json=ITEM)).json()["id"]

    assert (await client.delete(f"{BASE}/{cid}/items/{item_id}")).status_code == 204
    assert (await client.delete(f"{BASE}/{cid}/items/{item_id}")).status_code == 204
    assert (await client.get(f"{BASE}/{cid}")).json()["item_count"] == 0


async def test_add_51st_item_is_409_collection_full(client, db, listings):
    cid = (await make(db)).id
    for n in range(1, 51):
        added = await client.put(f"{BASE}/{cid}/items", json={**ITEM, "listing_key": str(n)})
        assert added.status_code == 201

    over = await client.put(f"{BASE}/{cid}/items", json={**ITEM, "listing_key": "51"})

    assert over.status_code == 409
    assert over.json() == {"detail": "collection_full"}


async def test_share_link_requires_sharing_enabled(client, db):
    cid = (await make(db)).id

    blocked = await client.post(f"{BASE}/{cid}/share-link")
    assert blocked.status_code == 409
    assert blocked.json() == {"detail": "sharing_disabled"}

    await client.patch(f"{BASE}/{cid}", json={"sharing_enabled": True})
    link = await client.post(f"{BASE}/{cid}/share-link")
    assert link.status_code == 200
    assert "/collections/" in link.json()["url"]


async def test_rotate_changes_the_link(client, db):
    cid = (await make(db)).id
    await client.patch(f"{BASE}/{cid}", json={"sharing_enabled": True})
    before = (await client.post(f"{BASE}/{cid}/share-link")).json()["url"]

    rotated = await client.post(f"{BASE}/{cid}/share-link/rotate")

    assert rotated.status_code == 200
    assert rotated.json()["url"] != before
    assert (await client.post(f"{BASE}/{cid}/share-link")).json() == rotated.json()


async def test_foreign_org_collection_is_404_everywhere(client, db, listings):
    other = (await make(db, actor=FOREIGN)).id
    item = uuid4()

    for method, url, body in [
        ("GET", f"{BASE}/{other}", None),
        ("PATCH", f"{BASE}/{other}", {"name": "x"}),
        ("DELETE", f"{BASE}/{other}", None),
        ("PUT", f"{BASE}/{other}/items", ITEM),
        ("DELETE", f"{BASE}/{other}/items/{item}", None),
        ("POST", f"{BASE}/{other}/share-link", None),
        ("POST", f"{BASE}/{other}/share-link/rotate", None),
    ]:
        response = await client.request(method, url, json=body)
        assert response.status_code == 404, (method, url)

    assert (await client.get(BASE)).json()["total"] == 0


async def test_list_and_detail_never_include_share_token(client, db, listings):
    row = await make(db)
    await collections.add_item(
        db,
        actor=MINE,
        collection_id=row.id,
        payload=CollectionItemAdd(source="property_finder", listing_key="123"),
    )
    await client.patch(f"{BASE}/{row.id}", json={"sharing_enabled": True, "agent_phone": "+971"})
    token = (await client.post(f"{BASE}/{row.id}/share-link")).json()["url"].rsplit("/", 1)[1]

    texts = [
        (await client.get(BASE)).text,
        (await client.get(f"{BASE}/{row.id}")).text,
        (await client.patch(f"{BASE}/{row.id}", json={"name": "Renamed"})).text,
        (await client.post(BASE, json={"name": "Another"})).text,
        (await client.put(f"{BASE}/{row.id}/items", json={**ITEM, "listing_key": "456"})).text,
    ]

    assert token
    assert all(token not in text for text in texts)


async def test_invalid_uuid_is_422(client, db):
    assert (await client.get(f"{BASE}/not-a-uuid")).status_code == 422
    assert (await client.delete(f"{BASE}/{uuid4()}/items/not-a-uuid")).status_code == 422


async def test_detail_warehouse_error_is_503(client, db, monkeypatch):
    cid = (await make(db)).id

    async def down(db, organization_id, keys):
        raise OperationalError("warehouse down")

    monkeypatch.setattr(collections, "listings_by_keys", down)

    response = await client.get(f"{BASE}/{cid}")

    assert response.status_code == 503
    assert response.json() == {"detail": "listings_unavailable"}


async def test_detail_os_error_is_503(client, db, monkeypatch):
    cid = (await make(db)).id

    async def down(db, organization_id, keys):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(collections, "listings_by_keys", down)

    response = await client.get(f"{BASE}/{cid}")

    assert response.status_code == 503
    assert response.json() == {"detail": "listings_unavailable"}
