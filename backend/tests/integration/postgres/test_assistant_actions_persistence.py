import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.assistant_actions import service
from app.assistant_actions.models import (
    ActionProposalRequest,
    AssistantAction,
    AssistantOutbox,
    AssistantReminder,
)
from app.chat.models import Conversation
from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry, CrmInboundNote
from app.organization.models import Organization, OrganizationMembership


@pytest.fixture(autouse=True)
def offline_assignment_names(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        service,
        "get_user_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                first_name="Test",
                last_name="Colleague",
            )
        ),
    )


async def actor(db):
    user, colleague, org = (str(uuid4()) for _ in range(3))
    db.add(Organization(id=org, name="Action tests", subscription_status="active"))
    await db.flush()
    db.add(OrganizationMembership(user_id=user, organization_id=org))
    db.add(OrganizationMembership(user_id=colleague, organization_id=org))
    conversation = Conversation(user_id=user, organization_id=org)
    db.add(conversation)
    await db.commit()
    return dict(user_id=user, organization_id=org), colleague, conversation.id


async def propose(db, identity, conversation_id, kind, payload, key=None):
    return await service.propose_action(
        db,
        **identity,
        request=ActionProposalRequest(
            kind=kind,
            payload=payload,
            conversation_id=conversation_id,
            idempotency_key=key or uuid4().hex,
        ),
    )


async def execute(db, identity, conversation_id, kind, payload):
    proposal = await propose(db, identity, conversation_id, kind, payload)
    result = await service.confirm_action(db, **identity, action_id=proposal.id)
    assert result.status == "succeeded", result
    return result


async def test_assistant_actions_proposal_reload_idempotency_and_double_confirm(
    pg_session, postgres_test_url
):
    identity, _, conversation_id = await actor(pg_session)
    proposal = await propose(
        pg_session,
        identity,
        conversation_id,
        "create_lead",
        {"full_name": "One lead"},
        "same-key-123",
    )
    duplicate = await propose(
        pg_session,
        identity,
        conversation_id,
        "create_lead",
        {"full_name": "One lead"},
        "same-key-123",
    )
    assert duplicate.id == proposal.id
    with pytest.raises(HTTPException) as error:
        await propose(
            pg_session,
            identity,
            conversation_id,
            "create_lead",
            {"full_name": "Different"},
            "same-key-123",
        )
    assert error.value.status_code == 409
    await pg_session.rollback()
    engine = create_async_engine(postgres_test_url)

    async def confirm():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            return await service.confirm_action(db, **identity, action_id=proposal.id)

    first, second = await asyncio.gather(confirm(), confirm())
    assert first.status == second.status == "succeeded"
    assert first.result == second.result
    await engine.dispose()
    rows = (
        await pg_session.exec(
            select(CrmInboundEnquiry).where(
                CrmInboundEnquiry.organization_id == identity["organization_id"]
            )
        )
    ).all()
    assert len(rows) == 1


async def test_assistant_actions_cannot_cross_actor_or_organization_and_rechecks_membership(
    pg_session,
):
    identity, colleague, conversation_id = await actor(pg_session)
    proposal = await propose(
        pg_session, identity, conversation_id, "create_lead", {"full_name": "Private"}
    )
    for forged in (
        {**identity, "user_id": colleague},
        {**identity, "organization_id": str(uuid4())},
    ):
        with pytest.raises(HTTPException) as error:
            await service.confirm_action(pg_session, **forged, action_id=proposal.id)
        assert error.value.status_code in {403, 404}
        await pg_session.rollback()
    membership = (
        await pg_session.exec(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == identity["user_id"]
            )
        )
    ).one()
    await pg_session.delete(membership)
    await pg_session.commit()
    with pytest.raises(HTTPException) as error:
        await service.confirm_action(pg_session, **identity, action_id=proposal.id)
    assert error.value.status_code == 403


async def test_assistant_actions_own_leads_reassignment_stale_preview_and_shared_contacts(
    pg_session,
):
    identity, colleague, conversation_id = await actor(pg_session)
    created = await execute(
        pg_session,
        identity,
        conversation_id,
        "create_lead",
        {"full_name": "Original", "phone": "123"},
    )
    lead_id = created.result["lead_id"]
    lead = await pg_session.get(CrmInboundEnquiry, lead_id)
    contact_id = lead.contact_id
    proposal = await propose(
        pg_session, identity, conversation_id, "update_lead", {"lead_id": lead_id, "status": "won"}
    )
    lead = await pg_session.get(CrmInboundEnquiry, lead_id)
    lead.status = "nurture"
    lead.updated_at = datetime.now(timezone.utc)
    await pg_session.commit()
    result = await service.confirm_action(pg_session, **identity, action_id=proposal.id)
    assert result.status == "failed"
    await execute(
        pg_session,
        identity,
        conversation_id,
        "assign_lead",
        {"lead_id": lead_id, "assignee_id": colleague},
    )
    with pytest.raises(HTTPException) as error:
        await propose(
            pg_session,
            identity,
            conversation_id,
            "add_note",
            {"lead_id": lead_id, "body": "Cannot touch reassigned"},
        )
    assert error.value.status_code == 404
    await pg_session.rollback()
    contact = await pg_session.get(CrmInboundContact, contact_id)
    assert contact.full_name == "Original"
    # Same phone creates a new contact rather than mutating a shared organization contact.
    second = await execute(
        pg_session,
        identity,
        conversation_id,
        "create_lead",
        {"full_name": "Separate", "phone": "123"},
    )
    second_lead = await pg_session.get(CrmInboundEnquiry, second.result["lead_id"])
    assert second_lead.contact_id != contact_id


async def test_assistant_actions_deletion_preserves_shared_contact_and_colleague_notes(pg_session):
    identity, colleague, conversation_id = await actor(pg_session)
    created = await execute(
        pg_session, identity, conversation_id, "create_lead", {"full_name": "Keep contact"}
    )
    lead_id = created.result["lead_id"]
    lead = await pg_session.get(CrmInboundEnquiry, lead_id)
    contact_id = lead.contact_id
    note = CrmInboundNote(
        enquiry_id=lead_id,
        organization_id=identity["organization_id"],
        user_id=colleague,
        body="Colleague's work",
        created_at=datetime.now(timezone.utc),
    )
    pg_session.add(note)
    await pg_session.commit()
    note_id = note.id
    with pytest.raises(HTTPException) as error:
        await propose(pg_session, identity, conversation_id, "delete_lead", {"lead_id": lead_id})
    assert error.value.status_code == 409
    await pg_session.rollback()
    assert await pg_session.get(CrmInboundNote, note_id)
    await pg_session.delete(await pg_session.get(CrmInboundNote, note_id))
    await pg_session.commit()
    await execute(
        pg_session, identity, conversation_id, "add_note", {"lead_id": lead_id, "body": "Own note"}
    )
    await execute(pg_session, identity, conversation_id, "delete_lead", {"lead_id": lead_id})
    assert await pg_session.get(CrmInboundEnquiry, lead_id) is None
    assert await pg_session.get(CrmInboundContact, contact_id) is not None


async def test_assistant_actions_persist_reminders_viewings_drafts_and_disconnected_outbox(
    pg_session,
):
    identity, _, conversation_id = await actor(pg_session)
    due = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    created = await execute(
        pg_session,
        identity,
        conversation_id,
        "create_reminder",
        {"title": "Follow up", "due_at": due},
    )
    reminder_id = created.result["reminder_id"]
    assert (await service.list_reminders(pg_session, **identity))[0].id == reminder_id
    await execute(
        pg_session,
        identity,
        conversation_id,
        "update_reminder",
        {"reminder_id": reminder_id, "title": "Changed", "due_at": due},
    )
    await execute(
        pg_session, identity, conversation_id, "delete_reminder", {"reminder_id": reminder_id}
    )
    assert await pg_session.get(AssistantReminder, reminder_id) is None
    lead = await execute(
        pg_session, identity, conversation_id, "create_lead", {"full_name": "Viewer"}
    )
    viewing = await execute(
        pg_session,
        identity,
        conversation_id,
        "schedule_viewing",
        {
            "lead_id": lead.result["lead_id"],
            "title": "Visit",
            "location": "Dubai",
            "starts_at": due,
            "ends_at": (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat(),
        },
    )
    assert (await service.list_viewings(pg_session, **identity))[0].delivery == "internal_only"
    await execute(
        pg_session,
        identity,
        conversation_id,
        "cancel_viewing",
        {"viewing_id": viewing.result["viewing_id"]},
    )
    draft = await execute(
        pg_session,
        identity,
        conversation_id,
        "create_listing_draft",
        {"title": "Home", "description": "Draft", "location": "Dubai", "price_aed": 5_000_000_000},
    )
    assert (await service.list_listing_drafts(pg_session, **identity))[
        0
    ].publication == "draft_only"
    external = await propose(
        pg_session,
        identity,
        conversation_id,
        "publish_listing",
        {"listing_id": draft.result["listing_id"]},
    )
    outcome = await service.confirm_action(pg_session, **identity, action_id=external.id)
    assert outcome.status == "not_connected"
    assert "Nothing was sent" in outcome.result["message"]
    outbox = (
        await pg_session.exec(
            select(AssistantOutbox).where(AssistantOutbox.action_id == external.id)
        )
    ).one()
    assert outbox.status == "not_connected"
    replay = await service.confirm_action(pg_session, **identity, action_id=external.id)
    assert replay.status == "not_connected"


async def test_assistant_actions_expired_cancelled_and_tampered_proposals_never_execute(pg_session):
    identity, _, conversation_id = await actor(pg_session)
    for mode in ("expired", "cancelled", "tampered"):
        proposal = await propose(
            pg_session, identity, conversation_id, "create_lead", {"full_name": mode}
        )
        if mode == "cancelled":
            await service.cancel_action(pg_session, **identity, action_id=proposal.id)
        else:
            row = await pg_session.get(AssistantAction, proposal.id)
            if mode == "expired":
                row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            else:
                row.payload = {"full_name": "Changed after preview"}
            await pg_session.commit()
        result = await service.confirm_action(pg_session, **identity, action_id=proposal.id)
        assert result.status == ("failed" if mode == "tampered" else mode)
    rows = (
        await pg_session.exec(
            select(CrmInboundEnquiry).where(
                CrmInboundEnquiry.organization_id == identity["organization_id"]
            )
        )
    ).all()
    assert not rows


async def test_assistant_actions_history_and_task_lists_hide_reassigned_lead_evidence(pg_session):
    identity, colleague, conversation_id = await actor(pg_session)
    created = await execute(
        pg_session, identity, conversation_id, "create_lead", {"full_name": "Sensitive name"}
    )
    lead_id = created.result["lead_id"]
    reminder = await execute(
        pg_session,
        identity,
        conversation_id,
        "create_reminder",
        {
            "lead_id": lead_id,
            "title": "Sensitive reminder",
            "due_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    note = await propose(
        pg_session,
        identity,
        conversation_id,
        "add_note",
        {"lead_id": lead_id, "body": "Sensitive note"},
    )
    await execute(
        pg_session,
        identity,
        conversation_id,
        "assign_lead",
        {"lead_id": lead_id, "assignee_id": colleague},
    )
    for proposal_id in (created.id, reminder.id, note.id):
        value = await service.get_action(pg_session, **identity, action_id=proposal_id)
        assert "Sensitive" not in value.model_dump_json()
    assert not await service.list_reminders(pg_session, **identity)
    values = await service.list_actions(pg_session, **identity, conversation_id=conversation_id)
    assert "Sensitive" not in str([value.model_dump() for value in values])


async def test_assistant_actions_trialing_org_matches_canonical_entitlement(pg_session):
    identity, _, conversation_id = await actor(pg_session)
    org = await pg_session.get(Organization, identity["organization_id"])
    org.subscription_status = "trialing"
    await pg_session.commit()
    created = await execute(
        pg_session, identity, conversation_id, "create_lead", {"full_name": "Trial lead"}
    )
    assert created.status == "succeeded"


async def test_assistant_actions_external_claim_is_durable_unknown_and_never_retried(pg_session):
    from unittest.mock import AsyncMock

    from app.assistant_actions.adapters import dispatch_queued

    identity, _, conversation_id = await actor(pg_session)
    created = await execute(
        pg_session, identity, conversation_id, "create_lead", {"full_name": "Recipient"}
    )
    proposal = await propose(
        pg_session,
        identity,
        conversation_id,
        "send_message",
        {"lead_id": created.result["lead_id"], "channel": "email", "body": "Synthetic test"},
    )
    await service.confirm_action(pg_session, **identity, action_id=proposal.id)
    adapter = AsyncMock()
    adapter.dispatch.side_effect = TimeoutError("Simulated ambiguous acceptance")
    # Runtime disconnected proposals cannot dispatch even when handed an adapter.
    assert (
        await dispatch_queued(pg_session, **identity, action_id=proposal.id, adapter=adapter)
        is None
    )
    adapter.dispatch.assert_not_called()
    # Simulate a future configured connector queuing a confirmed action, in this fixture only.
    row = await pg_session.get(AssistantAction, proposal.id)
    outbox = (
        await pg_session.exec(
            select(AssistantOutbox).where(AssistantOutbox.action_id == proposal.id)
        )
    ).one()
    row.status = outbox.status = "queued"
    await pg_session.commit()
    result = await dispatch_queued(pg_session, **identity, action_id=proposal.id, adapter=adapter)
    assert result.status == "unknown"
    assert (
        await dispatch_queued(pg_session, **identity, action_id=proposal.id, adapter=adapter)
        is None
    )
    assert adapter.dispatch.await_count == 1
    await pg_session.refresh(outbox)
    assert outbox.claimed_at is not None and outbox.status == "unknown"


async def test_assistant_actions_previews_identify_authorized_targets_and_consequences(pg_session):
    identity, colleague, conversation_id = await actor(pg_session)
    created = await execute(
        pg_session,
        identity,
        conversation_id,
        "create_lead",
        {"full_name": "Preview target", "phone": "private-phone", "email": "private@example.test"},
    )
    lead_id = created.result["lead_id"]
    proposals = []
    for kind, payload, consequence in (
        ("update_lead", {"lead_id": lead_id, "status": "qualified"}, "enquiry fields"),
        ("assign_lead", {"lead_id": lead_id, "assignee_id": colleague}, "lose assistant access"),
        ("delete_lead", {"lead_id": lead_id}, "cannot be undone"),
        ("add_note", {"lead_id": lead_id, "body": "Test note"}, "enquiry history"),
        (
            "create_reminder",
            {"lead_id": lead_id, "title": "Follow up", "due_at": "2027-01-01T10:00:00Z"},
            "notification delivery",
        ),
        (
            "schedule_viewing",
            {
                "lead_id": lead_id,
                "title": "Visit",
                "location": "Dubai",
                "starts_at": "2027-01-01T10:00:00Z",
                "ends_at": "2027-01-01T11:00:00Z",
            },
            "no invitations",
        ),
        (
            "send_message",
            {"lead_id": lead_id, "channel": "email", "body": "Hello"},
            "nothing is sent",
        ),
    ):
        proposal = await propose(pg_session, identity, conversation_id, kind, payload)
        proposals.append(proposal)
        assert proposal.preview["lead"] == f"Preview target (lead #{lead_id})"
        assert consequence in proposal.preview["consequence"]
        assert "private-phone" not in str(proposal.preview)
        assert "private@example.test" not in str(proposal.preview)
    reminder = await execute(
        pg_session,
        identity,
        conversation_id,
        "create_reminder",
        {"lead_id": lead_id, "title": "Named reminder", "due_at": "2027-01-01T10:00:00Z"},
    )
    deletion = await propose(
        pg_session,
        identity,
        conversation_id,
        "delete_reminder",
        {"reminder_id": reminder.result["reminder_id"]},
    )
    assert deletion.preview["target"].startswith("Named reminder (reminder #")
    assert deletion.preview["lead"] == f"Preview target (lead #{lead_id})"
    assert "cannot be undone" in deletion.preview["consequence"]
    proposals.append(deletion)
    await execute(
        pg_session,
        identity,
        conversation_id,
        "assign_lead",
        {"lead_id": lead_id, "assignee_id": colleague},
    )
    for proposal in proposals:
        hidden = await service.get_action(pg_session, **identity, action_id=proposal.id)
        assert hidden.preview["available"] is False
        assert "Preview target" not in hidden.model_dump_json()
        assert "Named reminder" not in hidden.model_dump_json()
    with pytest.raises(HTTPException) as error:
        await propose(pg_session, identity, conversation_id, "delete_lead", {"lead_id": lead_id})
    assert error.value.status_code == 404


async def test_assistant_actions_changed_confirmation_label_requires_new_preview(pg_session):
    identity, _, conversation_id = await actor(pg_session)
    created = await execute(
        pg_session, identity, conversation_id, "create_lead", {"full_name": "Original label"}
    )
    lead_id = created.result["lead_id"]
    proposal = await propose(
        pg_session, identity, conversation_id, "delete_lead", {"lead_id": lead_id}
    )
    lead = await pg_session.get(CrmInboundEnquiry, lead_id)
    contact = await pg_session.get(CrmInboundContact, lead.contact_id)
    contact.full_name = "Changed label"
    await pg_session.commit()
    result = await service.confirm_action(pg_session, **identity, action_id=proposal.id)
    assert result.status == "failed"
    assert await pg_session.get(CrmInboundEnquiry, lead_id) is not None


async def test_assistant_actions_assignee_lookup_names_are_scoped_and_ambiguous(
    pg_session, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.organization import service as organizations

    identity, colleague, conversation_id = await actor(pg_session)
    foreign, _, _ = await actor(pg_session)
    looked_up = []

    async def profile(user_id):
        looked_up.append(user_id)
        return SimpleNamespace(first_name="Ali", last_name="Broker", email="private@example.test")

    monkeypatch.setattr(organizations, "get_user_by_id", profile)
    result = await service.lookup_assignees(pg_session, **identity, search="ali b")
    assert {item["id"] for item in result["matches"]} == {identity["user_id"], colleague}
    assert result["clarification_required"] is True
    assert all(set(item) == {"id", "display_name"} for item in result["matches"])
    assert foreign["user_id"] not in looked_up
    assert "email" not in str(result) and "role" not in str(result)
    assert "private@example.test" not in str(result)
    extra_ids = [str(uuid4()) for _ in range(12)]
    for user_id in extra_ids:
        pg_session.add(
            OrganizationMembership(user_id=user_id, organization_id=identity["organization_id"])
        )
    await pg_session.commit()
    bounded = await service.lookup_assignees(pg_session, **identity, search="Ali")
    assert len(bounded["matches"]) == 10
    assert bounded["truncated"] is True and bounded["clarification_required"] is True
    # Assignment preview resolves its already verified member to a human name only.
    monkeypatch.setattr(
        service,
        "get_user_by_id",
        AsyncMock(return_value=SimpleNamespace(first_name="Ali", last_name="Broker")),
    )
    created = await execute(
        pg_session, identity, conversation_id, "create_lead", {"full_name": "Owner lead"}
    )
    proposal = await propose(
        pg_session,
        identity,
        conversation_id,
        "assign_lead",
        {"lead_id": created.result["lead_id"], "assignee_id": colleague},
    )
    assert proposal.preview["assignee"] == "Ali Broker"
    lookup = AsyncMock(
        side_effect=AssertionError("Cross-org assignee must fail before profile lookup")
    )
    monkeypatch.setattr(service, "get_user_by_id", lookup)
    with pytest.raises(HTTPException) as error:
        await propose(
            pg_session,
            identity,
            conversation_id,
            "assign_lead",
            {"lead_id": created.result["lead_id"], "assignee_id": foreign["user_id"]},
        )
    assert error.value.status_code == 404
    lookup.assert_not_called()


@pytest.mark.parametrize("removed", ["actor", "candidate"])
async def test_assistant_actions_assignee_lookup_rechecks_membership_after_directory(
    pg_session, monkeypatch, removed
):
    from types import SimpleNamespace

    from app.organization import service as organizations

    identity, colleague, _ = await actor(pg_session)
    changed = False

    async def profile(user_id):
        nonlocal changed
        if not changed:
            changed = True
            target = identity["user_id"] if removed == "actor" else colleague
            membership = (
                await pg_session.exec(
                    select(OrganizationMembership).where(OrganizationMembership.user_id == target)
                )
            ).one()
            await pg_session.delete(membership)
            await pg_session.commit()
        return SimpleNamespace(first_name="Ali", last_name="Broker", email="private@example.test")

    monkeypatch.setattr(organizations, "get_user_by_id", profile)
    if removed == "actor":
        with pytest.raises(HTTPException) as error:
            await service.lookup_assignees(pg_session, **identity, search="Ali")
        assert error.value.status_code == 403
    else:
        result = await service.lookup_assignees(pg_session, **identity, search="Ali")
        assert result["matches"] == [{"id": identity["user_id"], "display_name": "Ali Broker"}]
        assert result["clarification_required"] is False
