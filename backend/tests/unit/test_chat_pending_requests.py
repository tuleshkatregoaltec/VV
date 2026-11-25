"""Clarifications are merged into the request they answer, never silently dropped or mixed
with a different request; workflows receive the held request from the server itself."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from pydantic_ai.usage import RunUsage

from app.crm.assistant import workflows
from app.crm.assistant.dependencies import ChatDependencies
from app.crm.assistant.workflows import PendingDetails, merge_pending, pending_note

BOOKING = {
    "kind": "book_calendar_meeting",
    "lead_id": None,
    "details": {"starts_at": "2026-11-24T17:00:00+04:00", "missing": ["duration", "who"]},
}


def test_a_clarification_adds_to_what_was_already_given():
    reply = {
        "kind": "book_calendar_meeting",
        "lead_id": None,
        "details": {"duration_minutes": 30, "people": ["Manager 1"], "title": "JVC sales"},
    }
    merged = merge_pending(BOOKING, reply, new_request=False)
    assert merged["details"] == {
        "starts_at": "2026-11-24T17:00:00+04:00",
        "duration_minutes": 30,
        "people": ["Manager 1"],
        "title": "JVC sales",
    }
    # Nothing is left to ask, so the earlier question is not repeated.
    assert "missing" not in merged["details"]


def test_a_correction_replaces_only_that_value():
    reply = {"kind": None, "lead_id": None, "details": {"starts_at": "2026-11-24T18:00:00+04:00"}}
    merged = merge_pending(BOOKING, reply, new_request=False)
    assert merged["kind"] == "book_calendar_meeting"
    assert merged["details"] == {"starts_at": "2026-11-24T18:00:00+04:00"}


@pytest.mark.parametrize(
    "other",
    [
        {"kind": "create_reminder", "lead_id": None, "details": {"title": "Call"}},
        {"kind": None, "lead_id": None, "details": {"task": "find_leads"}},
    ],
)
def test_a_different_request_starts_afresh(other):
    task_hold = {"kind": None, "lead_id": None, "details": {"task": "check_calendar"}}
    prior = BOOKING if other["kind"] else task_hold
    assert merge_pending(prior, other, new_request=False) == other


def test_a_different_lead_or_an_explicit_new_request_starts_afresh():
    prior = {"kind": "update_lead", "lead_id": 1, "details": {"other": "status contacted"}}
    other_lead = {"kind": "update_lead", "lead_id": 2, "details": {}}
    assert merge_pending(prior, other_lead, new_request=False) == other_lead
    same_lead = {"kind": "update_lead", "lead_id": 1, "details": {}}
    assert merge_pending(prior, same_lead, new_request=True) == same_lead


def test_held_details_are_typed_and_bounded():
    with pytest.raises(ValidationError):
        PendingDetails(phone="+971500000000")  # Only the listed fields can be carried.
    with pytest.raises(ValidationError):
        PendingDetails(people=["A", "B", "C", "D", "E", "F"])
    with pytest.raises(ValidationError):
        PendingDetails(starts_at="2026-11-24T17:00:00")  # A time needs its offset.


async def test_every_workflow_task_carries_the_held_request():
    deps = ChatDependencies(user_id="u", organization_id="o", pending=dict(BOOKING))
    tasks = []

    class Specialist:
        name = "action_preparation"

        async def run(self, task, **_):
            tasks.append(task)
            return SimpleNamespace(output="How long?")

    ctx = SimpleNamespace(deps=deps, tool_name="prepare_action", usage=RunUsage())
    await workflows.run_workflow(Specialist(), ctx, "30 min Manager 1 team JVC sales")
    assert "30 min Manager 1 team JVC sales" in tasks[0]
    assert "2026-11-24T17:00:00+04:00" in tasks[0] and "book_calendar_meeting" in tasks[0]
    assert pending_note(ChatDependencies(user_id="u", organization_id="o")) == ""
