from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.assistant_actions.adapters import dispatch_claimed
from app.assistant_actions.models import ActionProposalRequest, SendMessage


def request(kind, payload, **extra):
    return ActionProposalRequest(
        kind=kind,
        payload=payload,
        conversation_id=1,
        idempotency_key="test-key-123",
        **extra,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"lead_id": 1, "full_name": "Overwrite shared contact"},
        {"lead_id": 1, "organization_id": "victim", "status": "won"},
        {"lead_id": 1, "assigned_user_id": "victim"},
        {"lead_id": 1, "status": None},
        {"lead_id": 1},
    ],
)
def test_lead_changes_cannot_modify_identity_or_shared_contact(payload):
    with pytest.raises(ValidationError):
        request("update_lead", payload)


def test_unknown_operation_actor_and_connector_url_are_rejected():
    for kind, payload, extra in [
        ("delete_organization", {}, {}),
        ("create_lead", {"full_name": "Test"}, {"user_id": "victim"}),
        (
            "send_message",
            {"lead_id": 1, "channel": "email", "body": "Hi", "url": "https://bad"},
            {},
        ),
    ]:
        with pytest.raises(ValidationError):
            request(kind, payload, **extra)


def test_scheduling_requires_explicit_timezone_and_ordered_times():
    with pytest.raises(ValidationError):
        request("create_reminder", {"title": "Call", "due_at": "2026-11-01T12:00:00"})
    with pytest.raises(ValidationError):
        request(
            "schedule_viewing",
            {
                "lead_id": 1,
                "title": "Visit",
                "location": "Dubai",
                "starts_at": "2026-11-01T12:00:00Z",
                "ends_at": "2026-11-01T11:00:00Z",
            },
        )


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("update_lead", {"lead_id": 1, "status": "won"}),
        ("assign_lead", {"lead_id": 1, "assignee_id": "member"}),
        (
            "update_listing_draft",
            {
                "listing_id": 2,
                "title": "Home",
                "description": "Draft",
                "price_aed": 100,
                "location": "Dubai",
            },
        ),
        ("send_message", {"lead_id": 1, "channel": "email", "body": "Hi"}),
    ],
)
def test_kind_specific_payload_roundtrip_preserves_exact_confirmed_fields(kind, payload):
    value = request(kind, payload)
    assert value.payload.model_dump(mode="json", exclude_unset=True) == payload
    assert (
        ActionProposalRequest.model_validate(value.model_dump(mode="json", exclude_unset=True))
        == value
    )


async def test_external_timeout_is_unknown_and_never_retried():
    adapter = AsyncMock()
    adapter.dispatch.side_effect = TimeoutError("provider may have accepted")
    result = await dispatch_claimed(
        adapter,
        payload=SendMessage(lead_id=1, channel="email", body="Hi"),
        idempotency_key="proposal-id",
    )
    assert result.status == "unknown"
    assert adapter.dispatch.await_count == 1
    assert adapter.dispatch.call_args.kwargs["idempotency_key"] == "proposal-id"
