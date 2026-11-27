"""CRM Assistant evaluation, database-integration layer: every case's reference probe.

Each case seeds a fresh copy of the synthetic fixture (crm_fixture.py) into the disposable
database conftest.py creates, then runs the CRM's real tools and services as the case's actor
(scripts/evaluations/crm_assistant/crm_probes.py). No model is called. Failures name the case
and the failing checks (counts, statuses, fixture keys), never record contents.

Run with `just crm-eval-db` (dummy offline settings plus an explicit local TEST_POSTGRES_URL).
"""

import os
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from app.config import settings
from scripts.evaluations.crm_assistant.crm_dataset import NoProbe, load_crm_benchmark
from scripts.evaluations.crm_assistant.crm_probes import run_case

LOOPBACK = {"localhost", "127.0.0.1", "::1"}
BENCHMARK = load_crm_benchmark()
EXECUTABLE = [case for case in BENCHMARK.cases if not isinstance(case.probe, NoProbe)]
NOT_APPLICABLE = [case for case in BENCHMARK.cases if isinstance(case.probe, NoProbe)]


@pytest.fixture(scope="session", autouse=True)
def local_databases_only():
    """Write cases run only against an explicitly local disposable database, and the app's own
    engine must be local too, so no code path can reach a shared database such as .env.dev's."""
    explicit = os.environ.get("TEST_POSTGRES_URL")
    if not explicit or make_url(explicit).host not in LOOPBACK:
        pytest.fail("Set TEST_POSTGRES_URL to a local PostgreSQL (localhost) for this evaluation")
    if make_url(str(settings.POSTGRES_URL)).host not in LOOPBACK:
        pytest.fail("POSTGRES_URL must be local; run through `just crm-eval-db`, not .env.dev")


@pytest.mark.parametrize("case", EXECUTABLE, ids=lambda case: case.id)
async def test_case_matches_the_crm(pg_session, case):
    result = await run_case(pg_session, case)
    failed = [f"{check.name}: {check.detail}" for check in result.checks if not check.ok]
    assert result.status == "passed", f"{case.id} {result.status}: {failed}"


def test_every_case_is_executed_here_or_explicitly_not_applicable():
    # Nothing is skipped silently: a case without a probe is listed with its reason.
    assert len(BENCHMARK.cases) == 30
    assert len(EXECUTABLE) + len(NOT_APPLICABLE) == 30
    assert {case.category for case in NOT_APPLICABLE} <= {"unsupported", "clarification"}
    assert all(case.expect.write == "none" for case in NOT_APPLICABLE)


# --- The probes can fail: wrong expectations are caught for the sample's probe types --------

BY_ID = {case.id: case for case in BENCHMARK.cases}


def first(predicate):
    return next(case for case in BENCHMARK.cases if predicate(case))


def corrupt(case, mutate):
    from scripts.evaluations.crm_assistant.crm_dataset import CrmCase

    data = case.model_dump(mode="json", exclude_unset=True)
    mutate(data["probe"])
    return CrmCase.model_validate(data)


def changed_after(probe):
    item = next(i for i in probe["state"] if "after" in i)
    item["after"] = "not-what-the-crm-does"


CORRUPTIONS = {
    "read_total": (
        lambda c: c.probe.type == "read" and c.probe.expect.total is not None,
        lambda p: p["expect"].update(total=p["expect"]["total"] + 1),
    ),
    "calendar_events": (
        lambda c: c.probe.type == "calendar",
        lambda p: p.update(events=[*p["events"], "E06"]),
    ),
    "lookup_matches": (
        lambda c: c.probe.type == "lookup" and c.probe.matches,
        lambda p: p.update(matches=[]),
    ),
    "state_after_confirmation": (
        lambda c: c.probe.type == "action"
        and any("after" in i.model_fields_set for i in c.probe.state),
        changed_after,
    ),
    "final_status": (
        lambda c: c.probe.type == "action" and c.probe.final_status == "succeeded",
        lambda p: p.update(final_status="failed"),
    ),
}


@pytest.mark.parametrize("name", sorted(CORRUPTIONS))
async def test_a_wrong_expectation_fails(pg_session, name):
    select_case, mutate = CORRUPTIONS[name]
    result = await run_case(pg_session, corrupt(first(select_case), mutate))
    assert result.status == "failed", (name, result.checks)


async def test_a_guarded_probe_fails_for_a_question_the_guard_lets_through(pg_session):
    from scripts.evaluations.crm_assistant.crm_dataset import CrmCase

    case = first(lambda c: c.probe.type == "input_guard")
    data = case.model_dump(mode="json", exclude_unset=True)
    data["question"] = "How many leads do I have?"
    assert (await run_case(pg_session, CrmCase.model_validate(data))).status == "failed"


# --- The live runner's plumbing, with scripted models (no provider call is possible) ---------


@pytest.fixture
def scripted(monkeypatch):
    from test_assistant_lead_contact_turns import call, delegate, last_return, say, script

    from app.crm.assistant import service

    monkeypatch.setattr(service.settings, "ASSISTANT_TYPED_ROUTING_ENABLED", False)
    return SimpleNamespace(
        call=call, delegate=delegate, last_return=last_return, say=say, script=script
    )


async def scripted_turn(db, case, seeded, **models):
    from contextlib import ExitStack

    from app.crm.assistant.agent import agent
    from app.crm.assistant.workflows import action_agent, crm_agent
    from scripts.evaluations.crm_assistant.crm_live import run_turn

    agents = {"coordinator": agent, "crm": crm_agent, "action": action_agent}
    with ExitStack() as stack:
        for name, model in models.items():
            stack.enter_context(agents[name].override(model=model))
        return await run_turn(db, seeded, case)


async def test_live_runner_records_and_scores_a_read_turn(pg_session, scripted):
    from scripts.evaluations.crm_assistant import crm_fixture
    from scripts.evaluations.crm_assistant.crm_scoring import score

    s = scripted
    case = BY_ID["crm001"]
    seeded = await crm_fixture.seed(pg_session)
    crm = s.script(
        s.call("query_my_crm_records", resource="leads", summary_only=True),
        lambda m: s.say(f"You can see {s.last_return(m)['total']} leads, by status."),
    )
    observed = await scripted_turn(
        pg_session,
        case,
        seeded,
        coordinator=s.delegate("retrieve_personal_crm", case.question),
        crm=crm,
    )
    assert observed.error is None
    assert observed.tools == ["retrieve_personal_crm", "query_my_crm_records"]
    assert (observed.proposals, observed.stored_actions) == ([], 0)
    assert "25 leads" in observed.answer
    assert score(case, observed).status == "passed"


async def test_live_runner_sees_a_proposal_that_writes_nothing_until_confirmed(
    pg_session, scripted
):
    from scripts.evaluations.crm_assistant import crm_fixture
    from scripts.evaluations.crm_assistant.crm_scoring import score

    s = scripted
    case = first(
        lambda c: c.actor == "nadia"
        and c.expect.action_kind == "assign_lead"
        and not c.probe.between
    )
    seeded = await crm_fixture.seed(pg_session)

    def propose(messages):
        [match] = s.last_return(messages)["matches"]
        return s.call(
            "propose_crm_action",
            kind="assign_lead",
            payload={"lead_id": seeded.leads["L01"], "assignee_id": match["id"]},
        )

    action = s.script(
        s.call("query_my_crm_records", resource="leads", search="Aaliyah Brooks", limit=5),
        s.call("find_assignment_colleagues", search="Sara"),
        propose,
        s.say("Prepared: Aaliyah Brooks to Sara Khan, for your confirmation."),
    )
    observed = await scripted_turn(
        pg_session,
        case,
        seeded,
        coordinator=s.delegate("prepare_action", case.question),
        action=action,
    )
    assert observed.error is None
    assert observed.proposals == [{"kind": "assign_lead", "status": "awaiting_confirmation"}]
    assert (observed.stored_actions, observed.state_unchanged) == (1, True)
    assert score(case, observed).passed("deterministic")


async def test_live_runner_scores_a_market_question_answered_without_tools(pg_session, scripted):
    from app.crm.assistant.workflows import MARKET_UNAVAILABLE
    from scripts.evaluations.crm_assistant import crm_fixture
    from scripts.evaluations.crm_assistant.crm_scoring import score

    s = scripted
    case = first(lambda c: c.category == "unsupported" and c.probe.type == "none")
    seeded = await crm_fixture.seed(pg_session)
    observed = await scripted_turn(
        pg_session, case, seeded, coordinator=s.script(s.say(MARKET_UNAVAILABLE))
    )
    assert (observed.tools, observed.proposals, observed.error) == ([], [], None)
    assert score(case, observed).status == "passed"
