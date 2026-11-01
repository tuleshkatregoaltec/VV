from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlmodel import select

from app.crm.import_models import CrmContactImport, CrmContactList, CrmPropertyContactClaim
from app.crm.inbound_models import SOLD_OWNER_SOURCE, CrmInboundEnquiry
from app.crm.recently_sold import sync_recently_sold_inbox

TODAY = date(2026, 10, 27)


async def _seed(pg_session, org, user, rows):
    now = datetime.now(timezone.utc)
    record = CrmContactImport(
        organization_id=org,
        created_by_user_id=user,
        name="Owners",
        original_filename="owners.csv",
        sha256=uuid4().hex,
        size_bytes=100,
        status="completed",
        mapping={"sheets": []},
        created_at=now,
    )
    pg_session.add(record)
    await pg_session.flush()
    contact_list = CrmContactList(
        organization_id=org,
        created_by_user_id=user,
        source_import_id=record.id,
        name="Owners",
        created_at=now,
        updated_at=now,
    )
    pg_session.add(contact_list)
    await pg_session.flush()
    for index, (owner, prop, sold_days_ago, phone) in enumerate(rows, 1):
        pg_session.add(
            CrmPropertyContactClaim(
                organization_id=org,
                import_id=record.id,
                list_id=contact_list.id,
                source_sheet="Owners",
                source_row_number=index,
                row_fingerprint=str(index),
                owner_key=owner,
                property_key=prop,
                contact_name=f"Owner {owner}",
                phone_primary=phone,
                area_name="Dubai Marina",
                building_name="Marina Gate 1",
                unit_number=str(1200 + index),
                ownership_status="former_owner",
                confidence_score=99,
                match_reason="A later sale was recorded",
                later_sale_date=TODAY - timedelta(days=sold_days_ago),
                latest_sale_price_aed=2_400_000,
                created_at=now,
                updated_at=now,
            )
        )
    await pg_session.commit()


async def _items(pg_session, org):
    return (
        await pg_session.exec(
            select(CrmInboundEnquiry).where(
                CrmInboundEnquiry.organization_id == org,
                CrmInboundEnquiry.source == SOLD_OWNER_SOURCE,
            )
        )
    ).all()


async def test_sync_creates_one_unqualified_inbox_item_per_recent_seller(pg_session):
    org, user = str(uuid4()), str(uuid4())
    await _seed(
        pg_session,
        org,
        user,
        [("o1", "p1", 40, "+971500000001"), ("o1", "p2", 10, None), ("o2", "p3", 120, None)],
    )
    result = await sync_recently_sold_inbox(pg_session, organization_id=org, today=TODAY)

    assert result == {"created": 1, "updated": 0}
    (item,) = await _items(pg_session, org)
    assert item.intent == "unknown" and item.record_kind == "unqualified_contact"
    assert item.assigned_user_id is None and item.first_response_due_at is None
    assert item.enquiry_date.date() == TODAY - timedelta(days=10)
    assert len(item.observed_data["recent_sales"]) == 2


async def test_rerunning_the_sync_updates_instead_of_duplicating(pg_session):
    org, user = str(uuid4()), str(uuid4())
    await _seed(pg_session, org, user, [("o1", "p1", 10, None)])
    await sync_recently_sold_inbox(pg_session, organization_id=org, today=TODAY)
    again = await sync_recently_sold_inbox(pg_session, organization_id=org, today=TODAY)

    assert again == {"created": 0, "updated": 0}
    assert len(await _items(pg_session, org)) == 1


async def test_owner_without_contact_details_is_still_listed(pg_session):
    org, user = str(uuid4()), str(uuid4())
    await _seed(pg_session, org, user, [("o1", "p1", 10, None)])
    await sync_recently_sold_inbox(pg_session, organization_id=org, today=TODAY)
    assert len(await _items(pg_session, org)) == 1
