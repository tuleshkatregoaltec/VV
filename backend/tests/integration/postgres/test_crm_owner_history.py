from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.crm import owner_history, owners
from app.crm.import_events import IMPORT_RESOLVER_VERSION
from app.crm.import_models import CrmContactImport, CrmContactList, CrmPropertyContactClaim


@pytest.fixture
def history_registry(monkeypatch):
    """Separate registry observations from the source rows' saved classifications."""
    registry = {
        unit: [
            {
                "sale_key": f"registry-{unit}-2020",
                "transaction_date": date(2020, 1, 1),
                "sale_amount_aed": 1_000_000,
                "area_name": "Business Bay",
                "building_name": "Aspect Tower",
                "project_name": "Executive Towers",
                "unit_number": unit,
                "property_type": "Apartment",
            }
        ]
        for unit in ("602", "603", "604")
    }

    async def fresh_sales(candidates):
        return {
            candidate.property_key: list(registry.get(candidate.unit_number, []))
            for _, candidate in candidates
        }

    monkeypatch.setattr("app.crm.owner_assessment._fresh_sales", fresh_sales)
    return registry


async def _source(db, org, version=None):
    now = datetime.now(timezone.utc)
    user = str(uuid4())
    record = CrmContactImport(
        organization_id=org,
        created_by_user_id=user,
        name="Synthetic history",
        original_filename=f"{uuid4().hex}.xlsx",
        sha256=uuid4().hex,
        size_bytes=100,
        status="completed",
        mapping={"resolver_version": version} if version else {},
        created_at=now,
    )
    db.add(record)
    await db.flush()
    contact_list = CrmContactList(
        organization_id=org,
        created_by_user_id=user,
        source_import_id=record.id,
        name="Synthetic source",
        created_at=now,
        updated_at=now,
    )
    db.add(contact_list)
    await db.flush()
    return record, contact_list


def _claim(record, contact_list, number, **changes):
    now = datetime.now(timezone.utc)
    return CrmPropertyContactClaim(
        **{
            "organization_id": record.organization_id,
            "import_id": record.id,
            "list_id": contact_list.id,
            "source_sheet": "Owners",
            "source_row_number": number,
            "row_fingerprint": uuid4().hex,
            "owner_key": "owner",
            "property_key": "aspecttower|602",
            "contact_name": "Synthetic same name",
            "phone_primary": "+971501234567",
            "area_name": "Business Bay",
            "building_name": "Aspect Tower",
            "project_name": "Executive Towers",
            "unit_number": "602",
            "party_role": "Buyer",
            "procedure_type": "Sell",
            "property_type": "Apartment",
            "ownership_status": "verified_current_owner",
            "confidence_score": 98,
            "match_reason": "Exact synthetic registry sale",
            "transaction_date": date(2020, 1, 1),
            "transaction_price_aed": 1_000_000,
            "latest_sale_date": date(2020, 1, 1),
            "created_at": now,
            "updated_at": now,
            "evidence": {},
            **changes,
        }
    )


async def test_cross_import_history_reconciles_counts_pagination_and_tenant_boundaries(
    pg_session, monkeypatch, history_registry
):
    history_registry["602"].append(
        {
            **history_registry["602"][0],
            "sale_key": "registry-602-2024",
            "transaction_date": date(2024, 1, 1),
        }
    )
    # A latest Seller label now creates a low-scored possible contact. A later
    # registry sale must still establish a former relationship across imports.
    history_registry["602"].append(
        {
            **history_registry["602"][0],
            "sale_key": "registry-602-2025",
            "transaction_date": date(2025, 1, 1),
            "sale_amount_aed": 1_500_000,
        }
    )
    org, other_org = str(uuid4()), str(uuid4())
    old, old_list = await _source(pg_session, org)
    new, new_list = await _source(pg_session, org, IMPORT_RESOLVER_VERSION)
    private, private_list = await _source(pg_session, other_org, IMPORT_RESOLVER_VERSION)
    first = _claim(old, old_list, 1)
    repeated = _claim(old, old_list, 2)
    sold = _claim(
        new,
        new_list,
        1,
        party_role="Seller",
        ownership_status="former_owner",
        transaction_date=date(2024, 1, 1),
        later_sale_date=date(2024, 1, 1),
        confidence_score=70,
    )
    invalid = _claim(new, new_list, 2, property_key="|null", unit_number="null")
    same_name = _claim(
        new,
        new_list,
        3,
        owner_key="different-identity",
        phone_primary="+971509876543",
        property_key="aspecttower|603",
        unit_number="603",
    )
    hidden = _claim(private, private_list, 1, transaction_date=date(2026, 1, 1))
    pg_session.add_all([first, repeated, sold, invalid, same_name, hidden])
    await pg_session.commit()

    summary = await owner_history.get_owner_history_summary(pg_session, organization_id=org)
    assert summary.source_event_count == 5
    assert summary.identifiable_property_count == summary.owner_property_count == 2
    assert summary.former_count == summary.verified_current_count == 1
    assert summary.invalid_identity_source_count == 1
    assert summary.legacy_source_event_count == 2
    assert summary.resolver_versions == {"legacy": 2, IMPORT_RESOLVER_VERSION: 3}
    assert summary.owner_property_count == (
        summary.verified_current_count
        + summary.probable_current_count
        + summary.former_count
        + summary.unresolved_count
    )

    selected = await owner_history.get_owner_history_summary(
        pg_session, organization_id=org, import_id=old.id
    )
    assert selected.source_event_count == 2
    assert selected.former_count == 1  # The selected file cannot hide the later disposal.
    history = await owner_history.get_owner_history(
        pg_session, organization_id=org, owner_key="owner", limit=2, offset=0
    )
    next_page = await owner_history.get_owner_history(
        pg_session, organization_id=org, owner_key="owner", limit=2, offset=2
    )
    assert history.total == next_page.total == 4
    assert len({event.id for event in history.events + next_page.events}) == 4
    assert history.events[0].id == sold.id
    by_id = {event.id: event for event in history.events + next_page.events}
    assert by_id[first.id].observed_ownership_status == "verified_current_owner"
    assert by_id[first.id].current_ownership_status == "former_owner"
    assert by_id[first.id].source_filename == old.original_filename
    assert by_id[invalid.id].property_key is None
    assert by_id[invalid.id].current_ownership_status == "insufficient_property_data"
    assert by_id[sold.id].event_family == "sale"
    assert by_id[sold.id].resolver_version == IMPORT_RESOLVER_VERSION
    assert "phone_primary" not in by_id[first.id].model_dump()
    assert "evidence" not in by_id[first.id].model_dump()
    assert (
        await owner_history.get_owner_history(
            pg_session, organization_id=org, owner_key="owner", limit=2, offset=100
        )
    ).total == 4
    for read in (
        owner_history.get_owner_history_summary(
            pg_session, organization_id=org, import_id=private.id
        ),
        owner_history.get_owner_history(
            pg_session, organization_id=other_org, owner_key="different-identity"
        ),
    ):
        with pytest.raises(HTTPException) as error:
            await read
        assert error.value.status_code == 404

    async def no_registry(profile):
        return profile

    monkeypatch.setattr(owners, "_enrich_owner_profile_registry", no_registry)
    profile = await owners.get_owner_profile(pg_session, organization_id=org, owner_key="owner")
    assert profile.history_summary == history.summary
    valid = next(item for item in profile.properties if item.property_key == "aspecttower|602")
    assert valid.ownership_status == "former_owner"
    assert profile.contact_ready_count == 0


async def test_legacy_aliases_expand_history_without_changing_workspace_identity(
    pg_session, monkeypatch, history_registry
):
    org = str(uuid4())
    old, old_list = await _source(pg_session, org, IMPORT_RESOLVER_VERSION)
    new, new_list = await _source(pg_session, org, IMPORT_RESOLVER_VERSION)
    first = _claim(old, old_list, 1, owner_key="legacy-key", phone_primary="050 123 4567")
    alias = _claim(new, new_list, 1, owner_key="canonical-key", phone_primary="+971501234567")
    other_property = _claim(
        new,
        new_list,
        2,
        owner_key="canonical-key",
        phone_primary="+971501234567",
        property_key="aspecttower|603",
        unit_number="603",
    )
    different_name = _claim(
        new,
        new_list,
        3,
        owner_key="another-person",
        phone_primary="+971501234567",
        contact_name="Another Person",
        property_key="aspecttower|604",
        unit_number="604",
    )
    pg_session.add_all([first, alias, other_property, different_name])
    await pg_session.commit()
    summary = await owner_history.get_owner_history_summary(pg_session, organization_id=org)
    assert summary.source_event_count == 4
    assert summary.owner_property_count == 3
    assert summary.verified_current_count == 3
    history = await owner_history.get_owner_history(
        pg_session, organization_id=org, owner_key="legacy-key"
    )
    assert history.owner_key == "legacy-key"
    assert history.total == history.summary.source_event_count == 3
    assert history.summary.owner_property_count == 2
    assert {event.id for event in history.events} == {first.id, alias.id, other_property.id}
    selected = await owner_history.get_owner_history(
        pg_session, organization_id=org, owner_key="legacy-key", import_id=new.id
    )
    assert selected.total == 2

    async def no_registry(profile):
        return profile

    monkeypatch.setattr(owners, "_enrich_owner_profile_registry", no_registry)
    profile = await owners.get_owner_profile(
        pg_session, organization_id=org, owner_key="legacy-key"
    )
    assert profile.owner_key == "legacy-key"
    assert profile.property_count == len(profile.properties) == 2
    assert profile.history_summary == history.summary
    assert {item.property_key for item in profile.properties} == {
        "aspecttower|602",
        "aspecttower|603",
    }
    assert first.owner_key == "legacy-key"
