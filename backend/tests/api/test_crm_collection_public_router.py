import logging

import pytest
from clickhouse_connect.driver.exceptions import OperationalError
from crm_document_helpers import listing
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import app.postgres.models  # noqa: F401 - registers every table
from app.crm import collection_public_router, collections
from app.crm.collection_models import CollectionCreate, CrmCollection
from app.crm.collections import CollectionActor
from app.organization.models import Organization
from app.postgres import get_db_session

ACTOR = CollectionActor("u1", "org1", True, "Navi", "navi@example.com")
HEADERS = {
    "cache-control": "private, no-store",
    "x-robots-tag": "noindex",
    "referrer-policy": "no-referrer",
}


@pytest.fixture(autouse=True)
def fresh_limiter():
    collection_public_router.reset_rate_limit()
    yield
    collection_public_router.reset_rate_limit()


@pytest.fixture
async def db(client_no_auth):
    from conftest import get_app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Organization(id="org1", name="o", subscription_status="active"))
        await session.commit()

        async def override():
            yield session

        get_app().dependency_overrides[get_db_session] = override
        yield session
    await engine.dispose()


@pytest.fixture
def current(monkeypatch):
    found = {"1": listing("1")}

    async def fake(db, organization_id, keys):
        return {k: found[k] for k in keys if k in found}

    monkeypatch.setattr(collections, "listings_by_keys", fake)
    return found


async def token_for(db):
    created = await collections.create_collection(
        db, actor=ACTOR, payload=CollectionCreate(name="Picks")
    )
    row = await db.get(CrmCollection, created.id)
    row.sharing_enabled = True
    await db.commit()
    return row.share_token


def url(token):
    return f"/api/v1/public/collections/{token}"


def server_log(caplog) -> str:
    # The httpx test client logs the request URL itself; only the server's records matter.
    return "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))


def assert_headers(response):
    for name, value in HEADERS.items():
        assert response.headers[name] == value


async def test_public_needs_no_auth(client_no_auth, db, current):
    response = await client_no_auth.get(url(await token_for(db)))
    assert response.status_code == 200
    assert response.json()["name"] == "Picks"


async def test_public_headers_on_200_404_503(client_no_auth, db, current, monkeypatch):
    token = await token_for(db)
    ok = await client_no_auth.get(url(token))
    assert ok.status_code == 200
    assert_headers(ok)

    missing = await client_no_auth.get(url("x" * 43))
    assert missing.status_code == 404
    assert missing.json() == {"detail": "collection_unavailable"}
    assert_headers(missing)

    malformed = await client_no_auth.get(url("short"))
    assert malformed.status_code == 404
    assert malformed.json() == {"detail": "collection_unavailable"}
    assert_headers(malformed)

    async def down(db, organization_id, keys):
        raise OperationalError("down")

    monkeypatch.setattr(collections, "listings_by_keys", down)
    # Needs an item for the warehouse to be consulted.
    from datetime import datetime, timezone

    from app.crm.collection_models import CrmCollectionItem

    row = (await db.exec(CrmCollection.__table__.select())).first()
    db.add(
        CrmCollectionItem(
            collection_id=row.id,
            organization_id="org1",
            source="property_finder",
            listing_key="1",
            listing_title="t",
            added_by_user_id="u1",
            added_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        )
    )
    await db.commit()
    broken = await client_no_auth.get(url(token))
    assert broken.status_code == 503
    assert broken.json() == {"detail": "listings_unavailable"}
    assert_headers(broken)


async def test_public_rate_limited_after_60(client_no_auth, db, current):
    for _ in range(60):
        assert (await client_no_auth.get(url("x" * 43))).status_code == 404
    limited = await client_no_auth.get(url("x" * 43))
    assert limited.status_code == 429
    assert limited.json() == {"detail": "too_many_requests"}
    assert_headers(limited)


def test_access_log_redacts_token():
    token = "A" * 43
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", f"/api/v1/public/collections/{token}", "1.1", 200),
        None,
    )
    collection_public_router.RedactCollectionToken().filter(record)
    text = record.getMessage()
    assert token not in text
    assert "/api/v1/public/collections/[redacted]" in text


def test_access_log_filter_is_attached():
    filters = logging.getLogger("uvicorn.access").filters
    assert any(isinstance(f, collection_public_router.RedactCollectionToken) for f in filters)


async def test_public_db_error_is_503_without_token_in_logs(
    client_no_auth, db, current, monkeypatch, caplog
):
    from sqlalchemy.exc import OperationalError as DbOperationalError

    token = await token_for(db)

    async def broken(*args, **kwargs):
        raise DbOperationalError("SELECT ... WHERE share_token = :t", {"t": token}, Exception())

    monkeypatch.setattr(db, "exec", broken)
    with caplog.at_level(logging.DEBUG):
        response = await client_no_auth.get(url(token))

    assert response.status_code == 503
    assert response.json() == {"detail": "listings_unavailable"}
    assert_headers(response)
    assert token not in server_log(caplog)


async def test_public_unexpected_error_is_500_with_headers(
    client_no_auth, db, current, monkeypatch, caplog
):
    token = await token_for(db)

    async def boom(db, token):
        raise RuntimeError(f"bad {token}")

    monkeypatch.setattr(collections, "public_collection", boom)
    with caplog.at_level(logging.DEBUG):
        response = await client_no_auth.get(url(token))

    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}
    assert_headers(response)
    assert token not in server_log(caplog)
