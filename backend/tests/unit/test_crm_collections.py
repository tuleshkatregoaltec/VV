import pytest
from crm_document_helpers import listing
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import app.postgres.models  # noqa: F401 - registers every table
from app.crm import collections
from app.crm.collection_models import CollectionCreate, CollectionItemAdd, CollectionUpdate
from app.crm.collections import CollectionActor
from app.crm.models import CrmCompanyListingDetail
from app.organization.models import Organization

ALICE = CollectionActor("alice", "org-a", False, "Alice Agent", "alice@example.com")
BOB = CollectionActor("bob", "org-a", False, "Bob Agent", "bob@example.com")
OWNER = CollectionActor("boss", "org-a", True, "Boss Owner", "boss@example.com")
OTHER_ORG = CollectionActor("eve", "org-b", True, "Eve", "eve@example.com")


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        for org in ("org-a", "org-b"):
            session.add(Organization(id=org, name=org))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.fixture
def listings(monkeypatch):
    current: dict[str, CrmCompanyListingDetail] = {"123": listing(), "456": listing("456")}

    async def fake_managed(db, organization_id, listing_key):
        found = current.get(listing_key)
        if found is None or not found.managed:
            raise HTTPException(status_code=404, detail="Listing not found")
        return found

    async def fake_by_keys(db, organization_id, keys):
        return {key: current[key] for key in keys if key in current}

    monkeypatch.setattr(collections, "managed_listing", fake_managed)
    monkeypatch.setattr(collections, "listings_by_keys", fake_by_keys)
    return current


def add(key: str) -> CollectionItemAdd:
    return CollectionItemAdd(source="property_finder", listing_key=key)


async def make(db, actor=ALICE, name="Picks"):
    return await collections.create_collection(db, actor=actor, payload=CollectionCreate(name=name))


async def status_of(coro) -> tuple[int, str]:
    with pytest.raises(HTTPException) as error:
        await coro
    return error.value.status_code, error.value.detail


async def test_member_cannot_see_other_members_collection(db, listings):
    made = await make(db, ALICE)
    assert await status_of(collections.get_collection(db, actor=BOB, collection_id=made.id)) == (
        404,
        "collection_not_found",
    )
    assert (await collections.list_collections(db, actor=BOB, limit=10, offset=0)).total == 0


async def test_owner_sees_all_org_collections(db, listings):
    made = await make(db, ALICE)
    assert (await collections.get_collection(db, actor=OWNER, collection_id=made.id)).id == made.id
    listed = await collections.list_collections(db, actor=OWNER, limit=10, offset=0)
    assert [item.id for item in listed.items] == [made.id]


async def test_list_is_newest_updated_first_and_paged(db, listings):
    first = await make(db, ALICE, "First")
    second = await make(db, ALICE, "Second")
    await collections.update_collection(
        db, actor=ALICE, collection_id=first.id, payload=CollectionUpdate(name="First again")
    )
    listed = await collections.list_collections(db, actor=ALICE, limit=1, offset=0)
    assert [item.id for item in listed.items] == [first.id]
    assert listed.total == 2
    rest = await collections.list_collections(db, actor=ALICE, limit=1, offset=1)
    assert [item.id for item in rest.items] == [second.id]


async def test_other_org_gets_404_on_get_update_delete_add_remove(db, listings):
    made = await make(db, ALICE)
    item, _ = await collections.add_item(db, actor=ALICE, collection_id=made.id, payload=add("123"))
    calls = [
        collections.get_collection(db, actor=OTHER_ORG, collection_id=made.id),
        collections.update_collection(
            db, actor=OTHER_ORG, collection_id=made.id, payload=CollectionUpdate(name="x")
        ),
        collections.delete_collection(db, actor=OTHER_ORG, collection_id=made.id),
        collections.add_item(db, actor=OTHER_ORG, collection_id=made.id, payload=add("456")),
        collections.remove_item(db, actor=OTHER_ORG, collection_id=made.id, item_id=item.id),
        collections.share_url(db, actor=OTHER_ORG, collection_id=made.id),
        collections.rotate_token(db, actor=OTHER_ORG, collection_id=made.id),
    ]
    for call in calls:
        assert await status_of(call) == (404, "collection_not_found")
    # Nothing changed.
    detail = await collections.get_collection(db, actor=ALICE, collection_id=made.id)
    assert detail.name == "Picks" and [i.id for i in detail.items] == [item.id]


async def test_add_rejects_unmanaged_listing(db, listings):
    listings["777"] = listing("777", managed=False)
    made = await make(db)
    for key in ("777", "999"):
        assert await status_of(
            collections.add_item(db, actor=ALICE, collection_id=made.id, payload=add(key))
        ) == (404, "Listing not found")
    assert (await collections.get_collection(db, actor=ALICE, collection_id=made.id)).items == []


async def test_add_is_idempotent(db, listings):
    made = await make(db)
    first, created = await collections.add_item(
        db, actor=ALICE, collection_id=made.id, payload=add("123")
    )
    second, created_again = await collections.add_item(
        db, actor=ALICE, collection_id=made.id, payload=add("123")
    )
    assert (created, created_again) == (True, False)
    assert first.id == second.id
    assert first.listing_title == "Marina Gate 2BR"
    detail = await collections.get_collection(db, actor=ALICE, collection_id=made.id)
    assert detail.item_count == 1 and detail.items[0].listing.listing_key == "123"


async def test_collection_rejects_the_51st_item_but_not_a_repeat(db, listings, monkeypatch):
    monkeypatch.setattr(collections, "MAX_COLLECTION_ITEMS", 2)
    listings["789"] = listing("789")
    made = await make(db)
    for key in ("123", "456"):
        await collections.add_item(db, actor=ALICE, collection_id=made.id, payload=add(key))
    assert await status_of(
        collections.add_item(db, actor=ALICE, collection_id=made.id, payload=add("789"))
    ) == (409, "collection_full")
    _, created = await collections.add_item(
        db, actor=ALICE, collection_id=made.id, payload=add("123")
    )
    assert created is False


async def test_remove_missing_item_is_noop(db, listings):
    from uuid import uuid4

    made = await make(db)
    await collections.remove_item(db, actor=ALICE, collection_id=made.id, item_id=uuid4())


async def test_remove_only_affects_one_collection(db, listings):
    one, two = await make(db, name="One"), await make(db, name="Two")
    item_one, _ = await collections.add_item(
        db, actor=ALICE, collection_id=one.id, payload=add("123")
    )
    await collections.add_item(db, actor=ALICE, collection_id=two.id, payload=add("123"))
    await collections.remove_item(db, actor=ALICE, collection_id=one.id, item_id=item_one.id)
    assert (await collections.get_collection(db, actor=ALICE, collection_id=one.id)).items == []
    assert (await collections.get_collection(db, actor=ALICE, collection_id=two.id)).item_count == 1
    # An item id from another collection is not removable through this one.
    item_two = (await collections.get_collection(db, actor=ALICE, collection_id=two.id)).items[0]
    await collections.remove_item(db, actor=ALICE, collection_id=one.id, item_id=item_two.id)
    assert (await collections.get_collection(db, actor=ALICE, collection_id=two.id)).item_count == 1


async def test_detail_marks_item_without_listing_when_not_managed(db, listings):
    made = await make(db)
    await collections.add_item(db, actor=ALICE, collection_id=made.id, payload=add("123"))
    listings["123"] = listing("123", managed=False)
    detail = await collections.get_collection(db, actor=ALICE, collection_id=made.id)
    assert detail.items[0].listing is None
    del listings["123"]
    detail = await collections.get_collection(db, actor=ALICE, collection_id=made.id)
    assert detail.items[0].listing is None


async def test_new_collection_has_sharing_disabled_and_43_char_token(db, listings):
    made = await make(db)
    assert made.sharing_enabled is False
    row = await db.get(collections.CrmCollection, made.id)
    assert len(row.share_token) == 43
    assert "share_token" not in made.model_dump()


async def test_share_url_requires_sharing_enabled(db, listings):
    made = await make(db)
    assert await status_of(collections.share_url(db, actor=ALICE, collection_id=made.id)) == (
        409,
        "sharing_disabled",
    )


async def test_share_url_is_stable_across_calls(db, listings, monkeypatch):
    monkeypatch.setattr(collections.settings, "FRONTEND_URL", "https://app.example.com/")
    made = await make(db)
    await collections.update_collection(
        db, actor=ALICE, collection_id=made.id, payload=CollectionUpdate(sharing_enabled=True)
    )
    first = await collections.share_url(db, actor=ALICE, collection_id=made.id)
    second = await collections.share_url(db, actor=ALICE, collection_id=made.id)
    row = await db.get(collections.CrmCollection, made.id)
    assert first == second
    assert first.url == f"https://app.example.com/collections/{row.share_token}"


async def test_rotate_changes_url(db, listings):
    made = await make(db)
    await collections.update_collection(
        db, actor=ALICE, collection_id=made.id, payload=CollectionUpdate(sharing_enabled=True)
    )
    before = await collections.share_url(db, actor=ALICE, collection_id=made.id)
    rotated = await collections.rotate_token(db, actor=ALICE, collection_id=made.id)
    after = await collections.share_url(db, actor=ALICE, collection_id=made.id)
    assert rotated.url != before.url and after == rotated


async def test_rename_keeps_token(db, listings):
    made = await make(db)
    before = (await db.get(collections.CrmCollection, made.id)).share_token
    renamed = await collections.update_collection(
        db, actor=ALICE, collection_id=made.id, payload=CollectionUpdate(name="  New name ")
    )
    assert renamed.name == "New name"
    assert (await db.get(collections.CrmCollection, made.id)).share_token == before


async def test_agent_contact_defaults_from_actor(db, listings):
    made = await make(db)
    assert (made.agent_name, made.agent_email, made.agent_phone) == (
        "Alice Agent",
        "alice@example.com",
        None,
    )


async def test_update_applies_only_sent_fields_and_null_clears_contact(db, listings):
    made = await make(db)
    updated = await collections.update_collection(
        db,
        actor=ALICE,
        collection_id=made.id,
        payload=CollectionUpdate(agent_phone="+971 50 000 0000"),
    )
    assert updated.agent_phone == "+971 50 000 0000" and updated.agent_email == "alice@example.com"
    cleared = await collections.update_collection(
        db,
        actor=ALICE,
        collection_id=made.id,
        payload=CollectionUpdate.model_validate({"agent_email": None, "agent_phone": None}),
    )
    assert cleared.agent_email is None and cleared.agent_phone is None
    assert cleared.name == "Picks" and cleared.agent_name == "Alice Agent"


@pytest.mark.parametrize("field", ["name", "agent_name", "sharing_enabled"])
def test_update_rejects_explicit_null_for_required_fields(field):
    with pytest.raises(ValidationError):
        CollectionUpdate.model_validate({field: None})


async def test_delete_removes_collection(db, listings):
    made = await make(db)
    await collections.delete_collection(db, actor=ALICE, collection_id=made.id)
    assert await status_of(collections.get_collection(db, actor=ALICE, collection_id=made.id)) == (
        404,
        "collection_not_found",
    )


# The list card shows a cover built from the first properties' photos, so agents can tell
# collections apart at a glance. Only listings we may republish (managed) give a cover.
async def test_list_covers_use_first_three_managed_photos(db, listings):
    for key in ("1", "2", "3", "4"):
        listings[key] = listing(key).model_copy(update={"photos": [f"https://p/{key}a.jpg", "x"]})
    col = await make(db)
    for key in ("1", "2", "3", "4"):
        await collections.add_item(db, actor=ALICE, collection_id=col.id, payload=add(key))
    # The org later switched company: "2" is no longer ours to republish.
    listings["2"] = listings["2"].model_copy(update={"managed": False})

    [row] = (await collections.list_collections(db, actor=ALICE, limit=10, offset=0)).items

    # First three items in the order they were added; the unmanaged one gives no photo.
    assert row.cover_photos == ["https://p/1a.jpg", "https://p/3a.jpg"]


async def test_list_still_loads_without_covers_when_warehouse_is_down(db, listings, monkeypatch):
    col = await make(db)
    await collections.add_item(db, actor=ALICE, collection_id=col.id, payload=add("123"))

    async def down(db, organization_id, keys):
        raise OSError("warehouse unreachable")

    monkeypatch.setattr(collections, "listings_by_keys", down)
    [row] = (await collections.list_collections(db, actor=ALICE, limit=10, offset=0)).items

    assert row.item_count == 1
    assert row.cover_photos == []


async def test_empty_collection_has_no_cover(db, listings):
    await make(db)
    [row] = (await collections.list_collections(db, actor=ALICE, limit=10, offset=0)).items
    assert row.cover_photos == []
