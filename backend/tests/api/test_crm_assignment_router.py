from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core import dependencies
from app.crm.inbound_models import InboundImportResponse, InboundImportSummary
from app.crm.routing_models import LeadAssignmentResponse

CSV = ("leads.csv", b"Name,Phone\nA,+971500000001\n", "text/csv")


async def test_a_leads_import_must_say_who_handles_the_leads(client, monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr("app.crm.router.process_inbound_import", service)

    # No silent default: neither "give them all to the importer" nor "leave them in the pool".
    missing = await client.post("/api/v1/crm/inbound/imports", files={"file": CSV})
    no_agent = await client.post(
        "/api/v1/crm/inbound/imports", files={"file": CSV}, data={"assignment_mode": "agent"}
    )

    assert (missing.status_code, no_agent.status_code) == (422, 422)
    assert no_agent.json()["detail"] == "Choose the agent who receives the imported leads"
    service.assert_not_awaited()


async def test_import_policy_reaches_the_service_with_the_signed_in_identity(client, monkeypatch):
    service = AsyncMock(
        return_value=InboundImportResponse(
            id=1,
            name="Campaign",
            original_filename="leads.csv",
            status="completed",
            summary=InboundImportSummary(),
            created_at=datetime.now(timezone.utc),
        )
    )
    monkeypatch.setattr("app.crm.router.process_inbound_import", service)

    await client.post(
        "/api/v1/crm/inbound/imports",
        files={"file": CSV},
        data={"assignment_mode": "agent", "assignee_user_id": "omar"},
    )

    kwargs = service.await_args.kwargs
    assert (kwargs["user_id"], kwargs["organization_id"]) == ("test-user-id", "1")
    assert kwargs["assignment_policy"].model_dump() == {
        "mode": "agent",
        "assignee_user_id": "omar",
        "team_id": None,
    }


async def test_an_import_for_myself_takes_no_assignee_from_the_request(client, monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr("app.crm.router.process_inbound_import", service)

    forged = await client.post(
        "/api/v1/crm/inbound/imports",
        files={"file": CSV},
        data={"assignment_mode": "self", "assignee_user_id": "someone-else"},
    )

    assert forged.status_code == 422
    service.assert_not_awaited()


async def test_bulk_assignment_is_bounded_and_uses_the_authenticated_actor(client, monkeypatch):
    service = AsyncMock(return_value=LeadAssignmentResponse(results=[]))
    monkeypatch.setattr("app.crm.assignment.assign_leads", service)

    too_many = await client.post(
        "/api/v1/crm/inbound/assignments",
        json={
            "enquiry_ids": list(range(1, 102)),
            "assignee_user_id": "omar",
            "expected_revisions": {str(i): 0 for i in range(1, 102)},
        },
    )
    ok = await client.post(
        "/api/v1/crm/inbound/assignments",
        json={"enquiry_ids": [5], "assignee_user_id": "omar", "expected_revisions": {"5": 2}},
    )

    assert (too_many.status_code, ok.status_code) == (422, 200)
    organization_id, user_id, request = service.await_args.args[1:]
    assert (organization_id, user_id, request.expected_revisions) == ("1", "test-user-id", {5: 2})


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/crm/assignment/scope",
        "/api/v1/crm/routing/rules",
        "/api/v1/crm/inbound/enquiries/1/assignments",
    ],
)
async def test_assignment_endpoints_require_a_signed_in_member(client_no_auth, path):
    response = await client_no_auth.get(path)
    assert response.status_code in {401, 403}


def _membership_context(role, organization_admin):
    return SimpleNamespace(
        user=SimpleNamespace(id="u"),
        organization=SimpleNamespace(id="org", subscription_status="active"),
        membership=SimpleNamespace(role=role, organization_admin=organization_admin),
        subscription=None,
    )


@pytest.mark.parametrize(
    ("role", "organization_admin", "allowed"),
    [("owner", False, True), ("member", True, True), ("member", False, False)],
)
async def test_only_owners_and_appointed_administrators_manage_teams(
    monkeypatch, role, organization_admin, allowed
):
    context = _membership_context(role, organization_admin)
    monkeypatch.setattr(dependencies, "require_membership", AsyncMock(return_value=context))

    if allowed:
        assert await dependencies.require_active_organization_admin(None, None) is context
    else:
        with pytest.raises(HTTPException) as refused:
            await dependencies.require_active_organization_admin(None, None)
        assert refused.value.status_code == 403


async def test_an_appointed_administrator_cannot_appoint_others(monkeypatch):
    # Granting administration stays with billing ownership.
    context = _membership_context("member", True)
    monkeypatch.setattr(dependencies, "require_membership", AsyncMock(return_value=context))
    with pytest.raises(HTTPException) as refused:
        await dependencies.require_active_owner(None, None)
    assert refused.value.status_code == 403
