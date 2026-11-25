from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.assistant_actions import service
from app.chat.security import fingerprint
from app.crm.assistant import workflows
from app.crm.assistant.dependencies import ChatDependencies


@pytest.mark.parametrize(
    "arguments",
    [
        {"search": "A"},
        {"search": "A" * 81},
        {"search": "Ali", "organization_id": "forged"},
        {"search": "Ali", "user_id": "forged"},
        {"search": "Ali", "role": "owner"},
    ],
)
def test_colleague_tool_only_accepts_bounded_name_search(arguments):
    validator = workflows.action_agent._function_toolset.tools[
        "find_assignment_colleagues"
    ].function_schema.validator
    with pytest.raises(ValidationError):
        validator.validate_python(arguments)


async def test_colleague_tool_uses_trusted_identity_and_records_canonical_evidence(monkeypatch):
    async def database():
        yield "session"

    result = {
        "available": True,
        "matches": [{"id": "member", "display_name": "Ali Broker"}],
        "clarification_required": False,
        "truncated": False,
    }
    lookup = AsyncMock(return_value=result)
    monkeypatch.setattr(workflows, "get_db_session", database)
    monkeypatch.setattr(service, "lookup_assignees", lookup)
    deps = ChatDependencies(
        user_id="trusted-user", organization_id="trusted-org", conversation_id=1
    )
    actual = await workflows.find_assignment_colleagues(SimpleNamespace(deps=deps), search="Ali")
    assert actual == result
    lookup.assert_awaited_once_with(
        "session", user_id="trusted-user", organization_id="trusted-org", search="Ali"
    )
    assert deps.evidence == [
        {
            "private": True,
            "type": "assignee_lookup",
            "search": "Ali",
            "fingerprint": fingerprint(result),
        }
    ]


async def test_colleague_tool_without_context_cannot_access_directory(monkeypatch):
    def forbidden():
        raise AssertionError("No database may open without trusted identity")

    monkeypatch.setattr(workflows, "get_db_session", forbidden)
    result = await workflows.find_assignment_colleagues(SimpleNamespace(deps=None), search="Ali")
    assert result["available"] is False


@pytest.mark.parametrize(
    "matches,changed",
    [
        (
            [
                {"id": "member", "display_name": "Ali Broker"},
                {"id": "other", "display_name": "Ali Broker"},
            ],
            False,
        ),
        ([{"id": "other", "display_name": "Ali Broker"}], False),
        ([{"id": "member", "display_name": "Ali Changed"}], True),
    ],
)
async def test_assignment_tool_requires_unambiguous_unchanged_current_turn_resolution(
    monkeypatch, matches, changed
):
    from app.assistant_actions.models import ActionKind, AssignLead

    async def database():
        yield "session"

    result = {
        "available": True,
        "matches": matches,
        "clarification_required": len(matches) > 1,
        "truncated": False,
    }
    monkeypatch.setattr(workflows, "get_db_session", database)
    monkeypatch.setattr(service, "lookup_assignees", AsyncMock(return_value=result))
    proposal = AsyncMock(
        side_effect=AssertionError("Ambiguous or changed colleague must not produce a proposal")
    )
    monkeypatch.setattr(service, "propose_action", proposal)
    deps = ChatDependencies(
        user_id="trusted-user", organization_id="trusted-org", conversation_id=1
    )
    deps.evidence.append(
        {
            "type": "assignee_lookup",
            "search": "Ali",
            "fingerprint": "old" if changed else fingerprint(result),
        }
    )
    result = await workflows.propose_crm_action(
        SimpleNamespace(deps=deps, tool_call_id="test"),
        ActionKind.ASSIGN_LEAD,
        AssignLead(lead_id=1, assignee_id="member"),
    )
    assert result["available"] is False
    assert result["clarification_required"] is True
    proposal.assert_not_called()


async def test_assignment_tool_accepts_only_fresh_unique_resolved_member(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.assistant_actions.models import ActionKind, ActionProposalResponse, AssignLead

    async def database():
        yield "session"

    resolved = {
        "available": True,
        "matches": [{"id": "member", "display_name": "Ali Broker"}],
        "clarification_required": False,
        "truncated": False,
    }
    monkeypatch.setattr(workflows, "get_db_session", database)
    monkeypatch.setattr(service, "lookup_assignees", AsyncMock(return_value=resolved))
    now = datetime.now(timezone.utc)
    proposal = AsyncMock(
        return_value=ActionProposalResponse(
            id="action",
            kind="assign_lead",
            status="awaiting_confirmation",
            title="Assign lead",
            preview={"assignee": "Ali Broker"},
            created_at=now,
            expires_at=now + timedelta(minutes=15),
        )
    )
    monkeypatch.setattr(service, "propose_action", proposal)
    deps = ChatDependencies(
        user_id="trusted-user", organization_id="trusted-org", conversation_id=1
    )
    deps.evidence.append(
        {"type": "assignee_lookup", "search": "Ali", "fingerprint": fingerprint(resolved)}
    )
    result = await workflows.propose_crm_action(
        SimpleNamespace(deps=deps, tool_call_id="test"),
        ActionKind.ASSIGN_LEAD,
        AssignLead(lead_id=1, assignee_id="member"),
    )
    assert result["confirmation_required"] is True
    assert proposal.call_args.kwargs["request"].payload.assignee_id == "member"
    assert len(deps.proposals) == 1


@pytest.mark.parametrize(
    ("status", "detail", "reason"),
    [
        (
            409,
            {"code": "LEAD_IN_POOL", "message": "This lead is waiting in your team's pool."},
            "This lead is waiting in your team's pool.",
        ),
        (403, "You cannot reassign this lead", "You cannot reassign this lead"),
        (422, {"code": "TEAM_REQUIRED", "message": "Choose the team."}, "Choose the team."),
    ],
)
async def test_role_refusal_reaches_the_user_with_its_reason(monkeypatch, status, detail, reason):
    """A user told only "unavailable" cannot act on a pool lead or ask the right person."""
    from fastapi import HTTPException

    from app.assistant_actions.models import ActionKind, AddNote

    async def database():
        yield "session"

    monkeypatch.setattr(workflows, "get_db_session", database)
    monkeypatch.setattr(
        service, "propose_action", AsyncMock(side_effect=HTTPException(status, detail))
    )
    deps = ChatDependencies(
        user_id="trusted-user", organization_id="trusted-org", conversation_id=1
    )
    result = await workflows.propose_crm_action(
        SimpleNamespace(deps=deps, tool_call_id="test"),
        ActionKind.ADD_NOTE,
        AddNote(lead_id=1, body="Called"),
    )
    assert result == {"available": False, "reason": reason}
    assert deps.proposals == []
