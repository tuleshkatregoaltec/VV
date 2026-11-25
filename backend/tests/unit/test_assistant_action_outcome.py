"""The answer beside an action card says what the server recorded, never what the model wrote.

Regression: a confirmed calendar booking showed "Completed" on its card while the answer above
it still said it was only a proposal and nothing had been added.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.assistant_actions import connectors
from app.assistant_actions.models import ActionProposalResponse
from app.assistant_actions.outcome import compose, model_context, strip_outcome_claims
from app.crm import calendar_service

MODEL_AT_PROPOSAL = (
    "You're free on 25 Nov at 15:00. This is only a proposal; nothing has been added to your "
    "calendar yet. Please confirm below."
)
MODEL_CLAIMING_SUCCESS = (
    "You're free on 25 Nov at 15:00. I've added the meeting to your Google Calendar."
)


def action(status, message=None, **preview):
    now = datetime.now(timezone.utc)
    return ActionProposalResponse(
        id="a1",
        kind="book_calendar_meeting",
        status=status,
        title="Book calendar meeting",
        preview=preview,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
        result={"message": message} if message else None,
    )


def test_completed_says_completed_and_drops_the_stale_proposal_wording():
    shown = compose(
        MODEL_AT_PROPOSAL,
        [action("succeeded", "Saved on your CRM calendar and added to your Google Calendar")],
    )
    assert shown.startswith("Book calendar meeting: completed. Saved on your CRM calendar")
    assert "Google Calendar" in shown
    assert "only a proposal" not in shown and "nothing has been added" not in shown
    # Context the model gathered survives.
    assert "You're free on 25 Nov at 15:00." in shown


def test_pending_confirmation_never_claims_it_was_added():
    shown = compose(MODEL_CLAIMING_SUCCESS, [action("awaiting_confirmation")])
    assert "awaiting your confirmation" in shown
    assert "I've added" not in shown
    assert "completed" not in shown


@pytest.mark.parametrize(
    ("status", "expected"),
    [("queued", "in progress"), ("unknown", "outcome is not known")],
)
def test_confirmed_but_unfinished_is_pending_not_done(status, expected):
    shown = compose(MODEL_CLAIMING_SUCCESS, [action(status)])
    assert expected in shown
    assert "I've added" not in shown and "completed" not in shown


def test_execution_failure_says_failed_and_not_done():
    shown = compose(
        MODEL_CLAIMING_SUCCESS,
        [action("failed", "A named colleague is not a current member of your organization")],
    )
    assert shown.startswith("Book calendar meeting: failed. A named colleague")
    assert "not confirmed as done" in shown
    assert "I've added" not in shown and "completed" not in shown


def test_crm_saved_google_failed_is_reported_as_partial():
    message = (
        "Saved on your CRM calendar for 25 Nov 2026 15:00–16:00 Dubai time, but Google "
        "Calendar was not updated (sync failed). Open CRM › Calendar and press Sync."
    )
    shown = compose(MODEL_CLAIMING_SUCCESS, [action("partially_succeeded", message)])
    assert shown.startswith("Book calendar meeting: partly completed. Saved on your CRM calendar")
    assert "Google Calendar was not updated" in shown
    assert "added the meeting to your Google Calendar" not in shown


def test_an_action_the_user_can_no_longer_reach_is_unavailable():
    shown = compose(MODEL_CLAIMING_SUCCESS, [action("succeeded", "x", available=False)])
    assert "no longer available" in shown and "completed" not in shown


def test_the_next_turn_gets_the_servers_status_not_the_models_words():
    context = model_context([action("partially_succeeded", "Saved on your CRM calendar")])
    assert context[0]["status"] == "partially_succeeded"
    assert "partly completed" in context[0]["server_statement"]


@pytest.mark.parametrize(
    "claim",
    [
        "I've booked it for you.",
        "The meeting has been added to your calendar.",
        "Nothing was added yet.",
        "This is only a proposal.",
        "Please confirm it below.",
        "It was saved to the CRM and Google Calendar.",
    ],
)
def test_the_guard_removes_every_kind_of_outcome_claim(claim):
    assert strip_outcome_claims(f"You are free at 15:00. {claim}") == "You are free at 15:00."


# The calendar meeting adapter reports exactly what happened to the CRM event and Google.

MEETING = {
    "title": "Pipeline review",
    "starts_at": "2026-11-25T15:00:00+04:00",
    "ends_at": "2026-11-25T16:00:00+04:00",
}


@pytest.mark.parametrize(
    ("sync", "status", "google_updated"),
    [
        ("synced", "succeeded", True),
        ("local", "succeeded", False),
        ("error", "partially_succeeded", False),
    ],
)
async def test_meeting_outcome_follows_the_saved_events_sync_state(
    monkeypatch, sync, status, google_updated
):
    from app.assistant_actions.models import CalendarMeeting

    async def create(db, **kwargs):
        return {"google_sync_status": sync}

    monkeypatch.setattr(calendar_service, "create_event", create)
    outcome = await connectors.CalendarMeetingAdapter(
        None, user_id="omar", organization_id="org"
    ).dispatch(payload=CalendarMeeting(**MEETING), idempotency_key="a1")
    assert outcome.status == status
    assert outcome.message.startswith("Saved on your CRM calendar")
    assert "25 Nov 2026 15:00–16:00 Dubai time" in outcome.message
    assert ("added to your Google Calendar" in outcome.message) == google_updated


@pytest.mark.parametrize(
    "claim",
    ["Done!", "I've assigned Bilal Hameed's lead to Track 8.", "The lead was moved to Track 8."],
)
def test_an_assignment_is_not_claimed_before_the_server_reports_it(claim):
    shown = compose(
        f"Bilal Hameed is handled by User 10. {claim}", [action("awaiting_confirmation")]
    )
    assert claim not in shown and "awaiting your confirmation" in shown
    assert "Bilal Hameed is handled by User 10." in shown
