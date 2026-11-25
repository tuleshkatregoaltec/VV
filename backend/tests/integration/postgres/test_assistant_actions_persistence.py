import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.assistant_actions import service
from app.assistant_actions.models import (
    ActionProposalRequest,
    AssistantAction,
    AssistantOutbox,
    AssistantReminder,
)
from app.chat.models import Conversation
from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry
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


async def supervise(db, identity, *members):
    """Make the actor a manager of a team holding themselves and `members` as agents."""
    from app.organization.models import OrganizationTeam, OrganizationTeamMember

    team = OrganizationTeam(organization_id=identity["organization_id"], name=uuid4().hex[:8])
    db.add(team)
    await db.flush()
    for user_id, role in [(identity["user_id"], "supervisor"), *((m, "agent") for m in members)]:
        db.add(
            OrganizationTeamMember(
                team_id=team.id,
                organization_id=identity["organization_id"],
                user_id=user_id,
                role=role,
            )
        )
    await db.commit()
    return team.id


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


async def reassigned_by_someone_else(db, lead_id, assignee):
    """A colleague's manager moves the lead: only they, not the agent, may reassign it."""
    lead = await db.get(CrmInboundEnquiry, lead_id)
    lead.assigned_user_id = assignee
    db.add(lead)
    await db.commit()


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
    await reassigned_by_someone_else(pg_session, lead_id, colleague)
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


async def test_delete_lead_is_refused_because_the_crm_cannot_delete_leads(pg_session):
    """The CRM has no lead deletion; the assistant must not offer more than the CRM does,
    whoever asks: not the assignee, and not an organization administrator."""
    from crm_role_support import agency, lead

    ids = await agency(pg_session)
    target = await lead(pg_session, ids, "Keep me", team="north", assignee="omar")
    for person in ("omar", "owner"):
        identity, conversation_id = await _team_actor(pg_session, ids, person)
        with pytest.raises(HTTPException) as error:
            await propose(
                pg_session, identity, conversation_id, "delete_lead", {"lead_id": target.id}
            )
        assert error.value.status_code == 403
        assert "does not support deleting leads" in error.value.detail
        await pg_session.rollback()
    pg_session.expire_all()
    assert await pg_session.get(CrmInboundEnquiry, target.id) is not None


async def test_a_delete_proposal_stored_before_the_refusal_fails_on_confirmation(pg_session):
    """Confirmation re-checks the CRM's rules: an old pending delete never executes."""
    from crm_role_support import agency, lead

    ids = await agency(pg_session)
    target = await lead(pg_session, ids, "Old proposal", team="north", assignee="omar")
    identity, conversation_id = await _team_actor(pg_session, ids, "omar")
    now = datetime.now(timezone.utc)
    # Arguments exactly as stored, so only the rules (not an argument check) can stop it.
    request = ActionProposalRequest(
        kind="delete_lead",
        conversation_id=conversation_id,
        payload={"lead_id": target.id},
        idempotency_key="stored-delete-proposal",
    )
    stored = AssistantAction(
        user_id=ids["omar"],
        organization_id=ids["org"],
        conversation_id=conversation_id,
        kind="delete_lead",
        status="awaiting_confirmation",
        idempotency_key="stored-delete-proposal",
        request_hash=service._request_hash(request, ids["omar"], ids["org"]),
        payload={"lead_id": target.id},
        snapshot={},
        preview={},
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    pg_session.add(stored)
    await pg_session.commit()
    action_id = stored.id
    result = await service.confirm_action(pg_session, **identity, action_id=action_id)
    assert result.status == "failed"
    pg_session.expire_all()
    assert (
        "does not support deleting leads"
        in (await pg_session.get(AssistantAction, action_id)).result["message"]
    )
    assert await pg_session.get(CrmInboundEnquiry, target.id) is not None


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
    await reassigned_by_someone_else(pg_session, lead_id, colleague)
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
        ("log_contact", {"lead_id": lead_id, "activity_type": "call"}, "Log contact"),
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
    await reassigned_by_someone_else(pg_session, lead_id, colleague)
    for proposal in proposals:
        hidden = await service.get_action(pg_session, **identity, action_id=proposal.id)
        assert hidden.preview["available"] is False
        assert "Preview target" not in hidden.model_dump_json()
        assert "Named reminder" not in hidden.model_dump_json()
    with pytest.raises(HTTPException) as error:
        await propose(
            pg_session,
            identity,
            conversation_id,
            "update_lead",
            {"lead_id": lead_id, "status": "won"},
        )
    assert error.value.status_code == 404


async def test_assistant_actions_changed_confirmation_label_requires_new_preview(pg_session):
    identity, _, conversation_id = await actor(pg_session)
    created = await execute(
        pg_session, identity, conversation_id, "create_lead", {"full_name": "Original label"}
    )
    lead_id = created.result["lead_id"]
    proposal = await propose(
        pg_session, identity, conversation_id, "update_lead", {"lead_id": lead_id, "status": "won"}
    )
    lead = await pg_session.get(CrmInboundEnquiry, lead_id)
    contact = await pg_session.get(CrmInboundContact, lead.contact_id)
    contact.full_name = "Changed label"
    await pg_session.commit()
    result = await service.confirm_action(pg_session, **identity, action_id=proposal.id)
    assert result.status == "failed"
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, lead_id)).status != "won"


async def test_assistant_actions_assignee_lookup_names_are_scoped_and_ambiguous(
    pg_session, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.organization import service as organizations

    identity, colleague, conversation_id = await actor(pg_session)
    team_id = await supervise(pg_session, identity, colleague)
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
    from app.organization.models import OrganizationTeamMember

    for user_id in extra_ids:
        pg_session.add(
            OrganizationMembership(user_id=user_id, organization_id=identity["organization_id"])
        )
    await pg_session.flush()
    for user_id in extra_ids:
        pg_session.add(
            OrganizationTeamMember(
                team_id=team_id, organization_id=identity["organization_id"], user_id=user_id
            )
        )
    await pg_session.commit()
    bounded = await service.lookup_assignees(pg_session, **identity, search="Ali")
    assert len(bounded["matches"]) == 10
    assert bounded["truncated"] is True and bounded["clarification_required"] is True
    # Assignment preview resolves its already verified member to a human name only.
    from crm_role_support import agency, lead

    monkeypatch.setattr(
        service,
        "get_user_by_id",
        AsyncMock(return_value=SimpleNamespace(first_name="Ali", last_name="Broker")),
    )
    ids = await agency(pg_session)
    target = await lead(pg_session, ids, "TeamLead", team="north", assignee="omar")
    manager, manager_conversation = await _team_actor(pg_session, ids, "nadia")
    proposal = await propose(
        pg_session,
        manager,
        manager_conversation,
        "assign_lead",
        {"lead_id": target.id, "assignee_id": ids["sara"]},
    )
    assert proposal.preview["new_assignee"] == "Ali Broker"
    assert "assignment history" in proposal.preview["consequence"]
    lookup = AsyncMock(
        side_effect=AssertionError("Cross-org assignee must fail before profile lookup")
    )
    monkeypatch.setattr(service, "get_user_by_id", lookup)
    with pytest.raises(HTTPException) as error:
        await propose(
            pg_session,
            manager,
            manager_conversation,
            "assign_lead",
            {"lead_id": target.id, "assignee_id": foreign["user_id"]},
        )
    assert error.value.status_code == 403
    lookup.assert_not_called()


@pytest.mark.parametrize("removed", ["actor", "candidate"])
async def test_assistant_actions_assignee_lookup_rechecks_membership_after_directory(
    pg_session, monkeypatch, removed
):
    from types import SimpleNamespace

    from app.organization import service as organizations

    identity, colleague, _ = await actor(pg_session)
    await supervise(pg_session, identity, colleague)
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


# --- Assistant actions follow the CRM role (agent / manager / organization admin) ---


async def _team_actor(db, ids, person):
    conversation = Conversation(user_id=ids[person], organization_id=ids["org"])
    db.add(conversation)
    await db.commit()
    return dict(user_id=ids[person], organization_id=ids["org"]), conversation.id


async def _proposal_count(db, ids):
    return (
        await db.exec(
            select(func.count())
            .select_from(AssistantAction)
            .where(AssistantAction.organization_id == ids["org"])
        )
    ).one()


async def test_manager_assigns_team_lead_to_team_agent_with_history(pg_session):
    from crm_role_support import agency, lead

    from app.crm.inbound_models import CrmInboundAssignmentEvent

    ids = await agency(pg_session)
    target = await lead(pg_session, ids, "OmarLead", team="north", assignee="omar")
    identity, conversation_id = await _team_actor(pg_session, ids, "nadia")
    revision = target.assignment_revision
    await execute(
        pg_session,
        identity,
        conversation_id,
        "assign_lead",
        {"lead_id": target.id, "assignee_id": ids["sara"]},
    )
    pg_session.expire_all()
    moved = await pg_session.get(CrmInboundEnquiry, target.id)
    assert (moved.assigned_user_id, moved.team_id) == (ids["sara"], ids["north"])
    assert moved.assignment_revision == revision + 1
    events = (
        await pg_session.exec(
            select(CrmInboundAssignmentEvent).where(
                CrmInboundAssignmentEvent.enquiry_id == target.id
            )
        )
    ).all()
    assert [(e.actor_user_id, e.assigned_user_id, e.reason) for e in events] == [
        (ids["nadia"], ids["sara"], "manual")
    ]


async def test_agent_cannot_propose_assignment(pg_session):
    from crm_role_support import agency, lead

    ids = await agency(pg_session)
    target = await lead(pg_session, ids, "OmarLead", team="north", assignee="omar")
    identity, conversation_id = await _team_actor(pg_session, ids, "omar")
    with pytest.raises(HTTPException) as error:
        await propose(
            pg_session,
            identity,
            conversation_id,
            "assign_lead",
            {"lead_id": target.id, "assignee_id": ids["sara"]},
        )
    assert error.value.status_code == 403
    await pg_session.rollback()
    assert await _proposal_count(pg_session, ids) == 0


async def test_manager_cannot_assign_outside_supervised_teams(pg_session):
    from crm_role_support import agency, lead

    ids = await agency(pg_session)
    south = await lead(pg_session, ids, "LinaLead", team="south", assignee="lina")
    north = await lead(pg_session, ids, "OmarLead", team="north", assignee="omar")
    identity, conversation_id = await _team_actor(pg_session, ids, "nadia")
    for target, assignee, status in ((south, "omar", 404), (north, "lina", 403)):
        with pytest.raises(HTTPException) as error:
            await propose(
                pg_session,
                identity,
                conversation_id,
                "assign_lead",
                {"lead_id": target.id, "assignee_id": ids[assignee]},
            )
        assert error.value.status_code == status
        await pg_session.rollback()


async def test_confirmation_fails_after_lead_leaves_managers_team(pg_session):
    from crm_role_support import agency, lead

    from app.crm import assignment

    ids = await agency(pg_session)
    target = await lead(pg_session, ids, "OmarLead", team="north", assignee="omar")
    identity, conversation_id = await _team_actor(pg_session, ids, "nadia")
    proposal = await propose(
        pg_session,
        identity,
        conversation_id,
        "assign_lead",
        {"lead_id": target.id, "assignee_id": ids["sara"]},
    )
    owner = await assignment.load_scope(pg_session, ids["org"], ids["owner"])
    await assignment.reassign(pg_session, owner, [target.id], ids["lina"], team_id=ids["south"])
    await pg_session.commit()
    result = await service.confirm_action(pg_session, **identity, action_id=proposal.id)
    assert result.status == "failed"
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, target.id)).assigned_user_id == ids["lina"]


async def test_pooled_lead_note_refused_for_agent(pg_session):
    from crm_role_support import agency, lead

    ids = await agency(pg_session)
    pooled = await lead(pg_session, ids, "Pooled", team="north", assignee=None, pooled=True)
    identity, conversation_id = await _team_actor(pg_session, ids, "omar")
    with pytest.raises(HTTPException) as error:
        await propose(
            pg_session, identity, conversation_id, "add_note", {"lead_id": pooled.id, "body": "x"}
        )
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "LEAD_IN_POOL"
    await pg_session.rollback()


async def test_manager_updates_and_notes_agents_lead(pg_session):
    from crm_role_support import agency, lead

    ids = await agency(pg_session)
    target = await lead(pg_session, ids, "OmarLead", team="north", assignee="omar")
    identity, conversation_id = await _team_actor(pg_session, ids, "nadia")
    await execute(
        pg_session,
        identity,
        conversation_id,
        "update_lead",
        {"lead_id": target.id, "status": "won"},
    )
    await execute(
        pg_session, identity, conversation_id, "add_note", {"lead_id": target.id, "body": "Coach"}
    )
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, target.id)).status == "won"


async def test_assistant_created_lead_gets_team_and_history(pg_session):
    from crm_role_support import agency

    from app.crm.inbound_models import CrmInboundAssignmentEvent

    ids = await agency(pg_session)
    identity, conversation_id = await _team_actor(pg_session, ids, "omar")
    created = await execute(
        pg_session, identity, conversation_id, "create_lead", {"full_name": "New buyer"}
    )
    lead_id = created.result["lead_id"]
    row = await pg_session.get(CrmInboundEnquiry, lead_id)
    assert (row.assigned_user_id, row.team_id) == (ids["omar"], ids["north"])
    events = (
        await pg_session.exec(
            select(CrmInboundAssignmentEvent).where(CrmInboundAssignmentEvent.enquiry_id == lead_id)
        )
    ).all()
    assert [(e.reason, e.assigned_user_id) for e in events] == [("created", ids["omar"])]


def _everyone_named_sam(monkeypatch, ids):
    from types import SimpleNamespace

    from app.organization import service as organizations

    people = {user_id: name for name, user_id in ids.items()}

    async def profile(user_id):
        return SimpleNamespace(first_name="Sam", last_name=people.get(user_id, "Other"), email=None)

    monkeypatch.setattr(organizations, "get_user_by_id", profile)


async def test_lookup_returns_only_people_the_user_may_assign_to(pg_session, monkeypatch):
    from crm_role_support import agency

    ids = await agency(pg_session)
    _everyone_named_sam(monkeypatch, ids)
    nadia = await service.lookup_assignees(
        pg_session, user_id=ids["nadia"], organization_id=ids["org"], search="sam"
    )
    assert {item["id"] for item in nadia["matches"]} == {ids["nadia"], ids["omar"], ids["sara"]}
    owner = await service.lookup_assignees(
        pg_session, user_id=ids["owner"], organization_id=ids["org"], search="sam"
    )
    # Administrators assign into every team; the owner is in none, so is not a destination.
    assert {item["id"] for item in owner["matches"]} == {
        ids[name] for name in ("nadia", "omar", "sara", "karim", "lina")
    }


async def test_agent_lookup_explains_assignment_is_for_managers(pg_session, monkeypatch):
    from crm_role_support import agency

    ids = await agency(pg_session)
    _everyone_named_sam(monkeypatch, ids)
    result = await service.lookup_assignees(
        pg_session, user_id=ids["omar"], organization_id=ids["org"], search="sam"
    )
    assert result == {
        "available": False,
        "reason": "Only managers and organization administrators can assign leads",
    }


@pytest.mark.parametrize(
    ("intent", "record_kind", "confirmed"),
    [
        ("buy", "opportunity", {"intent": "buy"}),
        ("rent", "opportunity", {"intent": "rent"}),
        ("sell", "opportunity", {"intent": "sell"}),
        ("let", "opportunity", {"intent": "let"}),
        ("unknown", "unqualified_contact", {}),
    ],
)
async def test_assistant_created_lead_is_classified_like_a_crm_created_lead(
    pg_session, intent, record_kind, confirmed
):
    """A known intent makes a confirmed opportunity, as in the CRM; otherwise matching, inbox
    triage and lead breakdowns would treat a qualified buyer as an unqualified contact."""
    identity, _, conversation_id = await actor(pg_session)
    created = await execute(
        pg_session,
        identity,
        conversation_id,
        "create_lead",
        {"full_name": f"Classified {intent}", "intent": intent},
    )
    lead = await pg_session.get(CrmInboundEnquiry, created.result["lead_id"])
    await pg_session.refresh(lead)
    assert (lead.intent, lead.record_kind, lead.confirmed_data) == (intent, record_kind, confirmed)


async def test_assistant_intent_updates_keep_classification_like_the_crm(pg_session):
    """Mirrors crm/inbound.py: a known intent promotes to an opportunity and is confirmed; back
    to unknown is an unqualified contact again; other edits leave the classification alone."""
    identity, _, conversation_id = await actor(pg_session)
    created = await execute(
        pg_session, identity, conversation_id, "create_lead", {"full_name": "Updated intent"}
    )
    lead_id = created.result["lead_id"]

    async def update(**fields):
        await execute(
            pg_session, identity, conversation_id, "update_lead", {"lead_id": lead_id, **fields}
        )
        lead = await pg_session.get(CrmInboundEnquiry, lead_id)
        await pg_session.refresh(lead)
        return lead.intent, lead.record_kind, lead.confirmed_data

    assert await update(intent="rent") == ("rent", "opportunity", {"intent": "rent"})
    assert await update(intent="buy") == ("buy", "opportunity", {"intent": "buy"})
    assert await update(status="contacted") == ("buy", "opportunity", {"intent": "buy"})
    # As in the CRM, confirmed_data keeps the last confirmed intent; the kind is what changes.
    assert await update(intent="unknown") == ("unknown", "unqualified_contact", {"intent": "buy"})


async def _set_admin(db, ids, person, admin: bool):
    from sqlalchemy import update

    await db.execute(
        update(OrganizationMembership)
        .where(OrganizationMembership.user_id == ids[person])
        .values(organization_admin=admin)
    )
    await db.commit()


async def test_member_made_admin_acts_across_teams_until_the_flag_is_revoked(pg_session):
    """Organization administration, not team membership, grants every lead; losing it between
    preview and confirmation must stop the change."""
    from crm_role_support import agency, lead

    ids = await agency(pg_session)
    south = await lead(pg_session, ids, "LinaLead", team="south", assignee="lina")
    identity, conversation_id = await _team_actor(pg_session, ids, "sara")
    # A plain member of North cannot even find South's lead.
    with pytest.raises(HTTPException) as error:
        await propose(
            pg_session,
            identity,
            conversation_id,
            "update_lead",
            {"lead_id": south.id, "status": "contacted"},
        )
    assert error.value.status_code == 404
    await pg_session.rollback()

    await _set_admin(pg_session, ids, "sara", True)
    await execute(
        pg_session,
        identity,
        conversation_id,
        "update_lead",
        {"lead_id": south.id, "status": "contacted"},
    )
    pending = await propose(
        pg_session, identity, conversation_id, "update_lead", {"lead_id": south.id, "status": "won"}
    )
    await _set_admin(pg_session, ids, "sara", False)
    result = await service.confirm_action(pg_session, **identity, action_id=pending.id)
    assert result.status == "failed"
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, south.id)).status == "contacted"


async def test_agent_acts_on_own_leads_and_shared_signals_but_not_colleagues(pg_session):
    from crm_role_support import agency, lead

    from app.crm.inbound_models import SOLD_OWNER_SOURCE

    ids = await agency(pg_session)
    own = await lead(pg_session, ids, "OmarLead", team="north", assignee="omar")
    signal = await lead(
        pg_session, ids, "SoldOwner", team=None, assignee=None, source=SOLD_OWNER_SOURCE
    )
    teammate = await lead(pg_session, ids, "SaraLead", team="north", assignee="sara")
    other_team = await lead(pg_session, ids, "LinaLead", team="south", assignee="lina")
    identity, conversation_id = await _team_actor(pg_session, ids, "omar")
    for target in (own, signal):
        await execute(
            pg_session, identity, conversation_id, "add_note", {"lead_id": target.id, "body": "x"}
        )
    # A teammate's or another team's lead answers like a missing one: nothing is disclosed.
    for target in (teammate, other_team):
        with pytest.raises(HTTPException) as error:
            await propose(
                pg_session,
                identity,
                conversation_id,
                "add_note",
                {"lead_id": target.id, "body": "x"},
            )
        assert error.value.status_code == 404
        await pg_session.rollback()


async def test_shared_signal_action_fails_once_a_colleague_takes_it(pg_session):
    from crm_role_support import agency, lead

    from app.crm import assignment
    from app.crm.inbound_models import SOLD_OWNER_SOURCE

    ids = await agency(pg_session)
    signal = await lead(
        pg_session, ids, "SoldOwner", team=None, assignee=None, source=SOLD_OWNER_SOURCE
    )
    identity, conversation_id = await _team_actor(pg_session, ids, "omar")
    pending = await propose(
        pg_session,
        identity,
        conversation_id,
        "update_lead",
        {"lead_id": signal.id, "status": "contacted"},
    )
    owner = await assignment.load_scope(pg_session, ids["org"], ids["owner"])
    await assignment.reassign(pg_session, owner, [signal.id], ids["lina"], team_id=ids["south"])
    await pg_session.commit()
    result = await service.confirm_action(pg_session, **identity, action_id=pending.id)
    assert result.status == "failed"
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, signal.id)).status == "new"


def _platform_admin_api(pg_session, user_id):
    """The real action routes and auth dependencies; only token verification is replaced by a
    user whose platform metadata says Super Admin."""
    from types import SimpleNamespace

    from fastapi import FastAPI

    from app.assistant_actions import router as actions
    from app.core.dependencies import require_auth
    from app.postgres import get_db_session

    app = FastAPI()
    app.include_router(actions.router)

    async def session():
        yield pg_session

    app.dependency_overrides[get_db_session] = session
    app.dependency_overrides[require_auth] = lambda: SimpleNamespace(
        id=user_id, is_admin=True, app_metadata=SimpleNamespace(is_admin=True)
    )
    return app


async def test_platform_super_admin_without_membership_gets_no_crm_access(pg_session):
    from types import SimpleNamespace

    from httpx import ASGITransport, AsyncClient

    from app.core.dependencies import require_active_subscription

    await actor(pg_session)  # An active organization exists; the admin is not a member of it.
    platform_admin = f"platform-{uuid4().hex[:8]}"
    # The dependency every assistant chat and action route uses refuses before any CRM read.
    with pytest.raises(HTTPException) as error:
        await require_active_subscription(
            SimpleNamespace(id=platform_admin, is_admin=True), pg_session
        )
    assert error.value.status_code == 403
    app = _platform_admin_api(pg_session, platform_admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        refused = await client.post(
            "/api/v1/assistant/actions/proposals",
            json={
                "kind": "create_lead",
                "conversation_id": 1,
                "payload": {"full_name": "Super admin lead"},
                "idempotency_key": uuid4().hex,
            },
        )
        assert refused.status_code == 403
        assert (await client.get("/api/v1/assistant/actions/reminders")).status_code == 403
    count = (
        await pg_session.exec(
            select(func.count())
            .select_from(CrmInboundContact)
            .where(CrmInboundContact.full_name == "Super admin lead")
        )
    ).one()
    assert count == 0


async def test_platform_super_admin_who_is_an_agent_keeps_agent_scope(pg_session):
    """The platform flag adds nothing inside an organization: only the CRM role counts."""
    from crm_role_support import agency, lead
    from httpx import ASGITransport, AsyncClient

    from app.crm.assistant import query_my_records
    from app.crm.assistant.models import CrmAssistantQuery

    ids = await agency(pg_session)
    own = await lead(pg_session, ids, "OmarLead", team="north", assignee="omar")
    other_team = await lead(pg_session, ids, "LinaLead", team="south", assignee="lina")
    _, conversation_id = await _team_actor(pg_session, ids, "omar")
    app = _platform_admin_api(pg_session, ids["omar"])

    async def note(client, target):
        return await client.post(
            "/api/v1/assistant/actions/proposals",
            json={
                "kind": "add_note",
                "conversation_id": conversation_id,
                "payload": {"lead_id": target.id, "body": "x"},
                "idempotency_key": uuid4().hex,
            },
        )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await note(client, own)).status_code == 200
        assert (await note(client, other_team)).status_code == 404
    # Reads take no platform role at all; the agent sees only their own lead.
    result = await query_my_records(
        pg_session,
        CrmAssistantQuery(resource="leads", summary_only=True),
        user_id=ids["omar"],
        organization_id=ids["org"],
    )
    assert result.total == 1
