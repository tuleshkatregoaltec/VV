"""Manual owner details survive the agency's shared renewal lead being opened again."""

from uuid import uuid4

import pytest

from app.crm import inbound
from app.crm.inbound_models import InboundEnquiryUpdate


async def _open(db, org, agent, name, source=None, lease=None):
    return await inbound.open_vitevue_lease_enquiry(
        db,
        organization_id=org,
        user_id=agent,
        unit_key="synthetic-owner-provenance",
        owner_name=name,
        owner_phone=None,
        owner_email=None,
        owner_source=source,
        criteria={},
        lease=lease or {},
    )


async def test_workspace_owner_survives_colleague_open_without_owner_or_with_import(pg_session):
    org, agent, colleague = str(uuid4()), str(uuid4()), str(uuid4())
    manual = await _open(pg_session, org, agent, "Synthetic Manual Owner", "workspace")
    assert manual.observed_data["vitevue_owner_source"] == "workspace"

    unknown = await _open(pg_session, org, colleague, "")
    imported = await _open(pg_session, org, colleague, "Synthetic Imported Owner", "owner_import")
    assert unknown.id == imported.id == manual.id
    assert unknown.contact.full_name == imported.contact.full_name == "Synthetic Manual Owner"

    edited = await _open(pg_session, org, agent, "Synthetic Updated Owner", "workspace")
    assert edited.id == manual.id
    assert edited.contact.full_name == "Synthetic Updated Owner"


@pytest.mark.parametrize("confirmed_name", ["Synthetic Imported Owner", ""])
async def test_explicit_inbound_confirmation_or_clear_is_manual_even_if_equal_to_snapshot(
    pg_session, confirmed_name
):
    org, agent = str(uuid4()), str(uuid4())
    original = await _open(pg_session, org, agent, "Synthetic Imported Owner", "owner_import")
    confirmed = await inbound.update_inbound_enquiry(
        pg_session,
        enquiry_id=original.id,
        organization_id=org,
        user_id=agent,
        payload=InboundEnquiryUpdate(full_name=confirmed_name, phone=None, email=None),
    )
    assert confirmed.observed_data["vitevue_owner_source"] == "manual"

    refreshed = await _open(pg_session, org, agent, "Synthetic New Imported Owner", "owner_import")
    assert refreshed.id == original.id
    assert refreshed.contact.full_name == confirmed_name
    assert refreshed.contact.phone is None and refreshed.contact.email is None


async def test_contact_permission_edit_does_not_freeze_derived_owner(pg_session):
    org, agent = str(uuid4()), str(uuid4())
    original = await _open(pg_session, org, agent, "Synthetic Old Owner", "owner_import")
    await inbound.update_inbound_enquiry(
        pg_session,
        enquiry_id=original.id,
        organization_id=org,
        user_id=agent,
        payload=InboundEnquiryUpdate(do_not_contact=True),
    )
    refreshed = await _open(pg_session, org, agent, "Synthetic New Owner", "owner_import")
    assert refreshed.id == original.id
    assert refreshed.contact.full_name == "Synthetic New Owner"
    assert refreshed.contact.do_not_contact is True


async def test_refreshed_lease_updates_without_replacing_manually_confirmed_owner(pg_session):
    org, agent = str(uuid4()), str(uuid4())
    original = await _open(
        pg_session,
        org,
        agent,
        "Synthetic Imported Owner",
        "owner_import",
        lease={"lease_end": "2026-10-31", "annual_rent_aed": 80_000},
    )
    await inbound.update_inbound_enquiry(
        pg_session,
        enquiry_id=original.id,
        organization_id=org,
        user_id=agent,
        payload=InboundEnquiryUpdate(full_name="Synthetic Manual Owner"),
    )

    latest_lease = {"lease_end": "2027-10-31", "annual_rent_aed": 90_000}
    refreshed = await _open(
        pg_session,
        org,
        agent,
        "Synthetic Different Imported Owner",
        "owner_import",
        lease=latest_lease,
    )
    assert refreshed.id == original.id
    assert refreshed.contact.full_name == "Synthetic Manual Owner"
    assert refreshed.observed_data["vitevue_lease"] == latest_lease
    assert refreshed.observed_data["vitevue_owner_source"] == "manual"
