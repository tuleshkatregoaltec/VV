"""Many buyers writing to one agent at once: no enquiry may be silently dropped.

Chat admission allows one assistant turn per user at a time and a daily token allowance.
Simultaneous enquiries to one agent must wait for a busy admission (text in memory only), an
exhausted allowance goes to the agent at once, and an enquiry that still cannot be classified
ends in a visible, content-free notice.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.usage import RunUsage

from app.chat import admission
from app.config import settings
from app.whatsapp import customer_agent as customer
from app.whatsapp import customer_intake as intake
from app.whatsapp import customer_queue as queue

FACTS = [{"id": "villa-1", "text": "The villa has three bedrooms and a garden."}]
PERSONAL = "Dinner at mum's tonight? Bring the kids"


@pytest.fixture(autouse=True)
def enable_offline_assistant(monkeypatch):
    monkeypatch.setattr(customer.settings, "ASSISTANT_ENABLED", True)


class OneTurnPerUser:
    """The real admission rule (USER_CONCURRENCY=1), without a database."""

    def __init__(self, *, refuse=None, turn_seconds=0.02):
        self.active: dict[str, int] = {}
        self.refusals = 0
        self.admitted = 0
        self.refuse = refuse
        self.turn_seconds = turn_seconds

    @asynccontextmanager
    async def budget(self, *, user_id, organization_id, conversation_id):
        if self.refuse or self.active.get(user_id, 0) >= admission.USER_CONCURRENCY:
            self.refusals += 1
            raise admission.AdmissionRefused(self.refuse or "busy")
        self.active[user_id] = self.active.get(user_id, 0) + 1
        self.admitted += 1
        try:
            await asyncio.sleep(self.turn_seconds)  # the model call holds the lease
            yield RunUsage()
        finally:
            self.active[user_id] -= 1


def decision(message):
    property_enquiry = message != PERSONAL
    return {
        "topic": "property" if property_enquiry else "personal",
        "confidence": 0.99,
        "risk": "routine",
        "reason": "test",
        "next_question": None,
        "retrieval": None,
        "asks_if_automated": False,
    }


@pytest.fixture
def models(monkeypatch):
    seen = []

    async def classify(prompt, **kwargs):
        message = json.loads(prompt)["message"]
        seen.append(message)
        return SimpleNamespace(output=decision(message))

    async def plan(prompt, **kwargs):
        return SimpleNamespace(
            output={"response_kind": "facts", "evidence_ids": ["villa-1"], "risk": "routine"}
        )

    monkeypatch.setattr(customer, "classifier", lambda: SimpleNamespace(run=classify))
    monkeypatch.setattr(customer, "drafter", lambda: SimpleNamespace(run=plan))
    return seen


@pytest.fixture
def waits(monkeypatch):
    """Record admission back-off instead of sleeping it."""
    recorded = []

    async def pause(seconds):
        recorded.append(seconds)
        await asyncio.sleep(0.005)

    monkeypatch.setattr(customer, "_pause", pause)
    return recorded


async def build(message, user_id="agent-a", conversation_id=1):
    return await customer.build_customer_draft(
        message=message,
        knowledge=FACTS,
        history=[],
        user_id=user_id,
        organization_id="org",
        conversation_id=conversation_id,
    )


async def test_simultaneous_enquiries_to_one_agent_are_all_classified(models, waits, monkeypatch):
    gate = OneTurnPerUser()
    monkeypatch.setattr(customer.operations, "channel_budget", gate.budget)
    enquiries = [f"Is villa {n} still available?" for n in range(6)]
    results = await asyncio.gather(
        *(build(text, conversation_id=n) for n, text in enumerate(enquiries))
    )
    assert all(result is not None and result.reply for result in results), results
    assert sorted(models) == sorted(enquiries)
    assert gate.admitted == 6 and gate.refusals > 0, "the test must exercise contention"


async def test_personal_message_in_a_burst_is_still_ignored(models, waits, monkeypatch):
    gate = OneTurnPerUser()
    monkeypatch.setattr(customer.operations, "channel_budget", gate.budget)
    results = await asyncio.gather(
        build("Is the villa still available?", conversation_id=1),
        build(PERSONAL, conversation_id=2),
    )
    assert results[0].reply and results[1] is None


async def test_admission_that_never_frees_ends_in_a_content_free_notice(models, waits, monkeypatch):
    gate = OneTurnPerUser(refuse="busy")
    monkeypatch.setattr(customer.operations, "channel_budget", gate.budget)
    result = await build("Is the villa still available?")
    assert result.silent and result.reply is None
    assert result.store_content is False
    assert result.reason == queue.UNPROCESSED_REASON
    assert result.error_code == "admission_busy"
    assert models == [], "nothing reaches a model without admission"
    assert len(waits) >= 3, "it waits and retries before giving up"
    assert sum(waits) <= customer.ADMISSION_WAIT_SECONDS


async def test_admission_wait_is_bounded_in_real_time(models, monkeypatch):
    gate = OneTurnPerUser(refuse="busy")
    monkeypatch.setattr(customer.operations, "channel_budget", gate.budget)
    monkeypatch.setattr(customer, "ADMISSION_WAIT_SECONDS", 0.3)
    monkeypatch.setattr(customer, "ADMISSION_FIRST_RETRY_SECONDS", 0.02)
    started = asyncio.get_running_loop().time()
    result = await build("Is the villa still available?")
    assert asyncio.get_running_loop().time() - started < 1.0
    assert result.reason == queue.UNPROCESSED_REASON


async def test_identity_question_still_pauses_when_busy_admission_never_frees(
    models, waits, monkeypatch
):
    gate = OneTurnPerUser(refuse="busy")
    monkeypatch.setattr(customer.operations, "channel_budget", gate.budget)
    result = await build("Are you a bot?")
    assert result.silent and result.store_content is False
    assert result.reason == "identity_question"
    assert models == [] and sum(waits) <= customer.ADMISSION_WAIT_SECONDS


async def test_classifier_failure_is_a_content_free_notice_not_a_silent_drop(waits, monkeypatch):
    gate = OneTurnPerUser()
    monkeypatch.setattr(customer.operations, "channel_budget", gate.budget)
    failing = SimpleNamespace(run=AsyncMock(side_effect=RuntimeError("provider 429")))
    monkeypatch.setattr(customer, "classifier", lambda: failing)
    result = await build("Is the villa still available?")
    assert result.silent and result.reply is None and result.store_content is False
    assert result.reason == queue.UNPROCESSED_REASON
    assert result.error_code == "classifier_failed"


async def test_revoked_access_is_still_a_silent_cancel(models, waits, monkeypatch):
    @asynccontextmanager
    async def denied(**kwargs):
        raise PermissionError("revoked")
        yield

    monkeypatch.setattr(customer.operations, "channel_budget", denied)
    assert await build("Is the villa still available?") is None
    assert waits == []


# --- In-process scheduling ------------------------------------------------------------


def job(user, thread, message):
    return queue.ClassificationJob(
        connection_id=f"conn-{user}",
        thread_id=thread,
        message_id=message,
        revision=1,
        content=f"text {message}",
        user_id=user,
    )


async def test_one_agents_backlog_runs_one_at_a_time_without_starving_other_agents(
    monkeypatch,
):
    running: dict[str, int] = {}
    peak: dict[str, int] = {}
    finished = []

    async def classify(job, config):
        running[job.user_id] = running.get(job.user_id, 0) + 1
        peak[job.user_id] = max(peak.get(job.user_id, 0), running[job.user_id])
        await asyncio.sleep(0.02)
        running[job.user_id] -= 1
        finished.append(job.message_id)

    monkeypatch.setattr(intake.automation, "classify", classify)
    config = settings.model_copy(update={"WHATSAPP_CLASSIFIER_CONCURRENCY": 4})
    for n in range(6):
        intake.spawn(job("a", f"a-thread-{n}", f"a{n}"), config)
    intake.spawn(job("b", "b-thread", "b0"), config)
    await intake.drain()
    assert sorted(finished) == sorted([f"a{n}" for n in range(6)] + ["b0"])
    assert peak["a"] == 1, "one agent's enquiries must not race for its single admission"
    assert finished.index("b0") < finished.index("a5"), "another agent is not starved"


async def test_messages_in_one_thread_are_classified_in_arrival_order(monkeypatch):
    order = []

    async def classify(job, config):
        await asyncio.sleep(0.01 if job.message_id == "m1" else 0)
        order.append(job.message_id)

    monkeypatch.setattr(intake.automation, "classify", classify)
    for message_id in ("m1", "m2", "m3"):
        intake.spawn(job("a", "thread", message_id), settings)
    intake.spawn(job("a", "other", "x1"), settings)
    await intake.drain()
    assert [m for m in order if m.startswith("m")] == ["m1", "m2", "m3"]
    assert "x1" in order


# --- Gap 7: identity + enquiry under contention, and exhausted allowance -------------------


async def test_identity_question_with_an_enquiry_waits_for_admission_and_keeps_it(
    models, waits, monkeypatch
):
    """Another enquiry holds the agent's one turn; the mixed message must wait for it rather
    than lose its property text to a content-free notice."""
    gate = OneTurnPerUser(turn_seconds=0.05)
    monkeypatch.setattr(customer.operations, "channel_budget", gate.budget)
    mixed = "are you a bot? also what's the price of 2BR in Marina"
    other, result = await asyncio.gather(
        build("Is the villa still available?", conversation_id=1),
        build(mixed, conversation_id=2),
    )
    assert other.reply
    assert result.silent and result.reply is None and result.reason == "identity_question"
    assert result.store_content is True, "an admitted property enquiry keeps its text"
    assert mixed in models and gate.refusals > 0 and waits


async def test_exhausted_allowance_reaches_the_agent_without_waiting(models, waits, monkeypatch):
    """A spent daily allowance does not free up within minutes: tell the agent at once."""
    gate = OneTurnPerUser(refuse="allowance")
    monkeypatch.setattr(customer.operations, "channel_budget", gate.budget)
    result = await build("Is the villa still available?")
    assert result.silent and result.reply is None and result.store_content is False
    assert result.reason == queue.UNPROCESSED_REASON
    assert result.error_code == "admission_allowance"
    assert waits == [] and gate.refusals == 1 and models == []


async def test_identity_question_on_exhausted_allowance_pauses_at_once(models, waits, monkeypatch):
    gate = OneTurnPerUser(refuse="allowance")
    monkeypatch.setattr(customer.operations, "channel_budget", gate.budget)
    result = await build("r u real?")
    assert result.silent and result.store_content is False
    assert result.reason == "identity_question"
    assert waits == [] and models == []
