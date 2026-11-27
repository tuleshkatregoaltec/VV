"""The CRM Assistant's 30 selected evaluation cases are grounded in supported CRM behavior.

These run offline (no database, model or network). They fail when the dataset drifts from the
code: a tool, resource or action kind the assistant does not have, a Market AI tool reachable
from the CRM, a write without confirmation, a probe that cannot be executed, or a question the
chat input guard would refuse before the assistant sees it.
"""

import json
import re
from typing import get_args

import pytest
from pydantic import ValidationError

from scripts.evaluations.crm_assistant import crm_fixture as fixture
from scripts.evaluations.crm_assistant.crm_dataset import (
    ACTION_KINDS,
    BENCHMARK,
    CRM_TOOLS,
    FINAL_STATUSES,
    MARKET_TOOLS,
    RESOURCES,
    SPECIALIST_TOOLS,
    WORKFLOW_TOOLS,
    ActionProbe,
    CrmBenchmark,
    GuardProbe,
    NoProbe,
    ReadProbe,
    load_crm_benchmark,
)

benchmark = load_crm_benchmark()
CASES = benchmark.cases


def registered(agent) -> set[str]:
    return set(agent._function_toolset.tools)


def test_exactly_30_selected_unique_versioned_cases():
    assert benchmark.version == 2 and benchmark.assistant == "crm"
    assert benchmark.fixture == fixture.FIXTURE_ID
    assert benchmark.reference_date == fixture.REFERENCE_DATE
    assert [case.id for case in CASES] == [
        "crm001",
        "crm002",
        "crm005",
        "crm017",
        "crm028",
        "crm035",
        "crm042",
        "crm045",
        "crm053",
        "crm059",
        "crm064",
        "crm071",
        "crm075",
        "crm084",
        "crm089",
        "crm095",
        "crm102",
        "crm107",
        "crm109",
        "crm112",
        "crm119",
        "crm125",
        "crm132",
        "crm139",
        "crm147",
        "crm158",
        "crm167",
        "crm179",
        "crm185",
        "crm198",
    ]
    assert len({case.question.casefold() for case in CASES}) == 30
    assert re.fullmatch(r"[0-9a-f]{64}", benchmark.digest)


def test_tool_registry_is_the_crm_assistants_own():
    from app.crm.assistant.agent import agent
    from app.crm.assistant.workflows import action_agent, crm_agent, followup_agent

    assert registered(agent) == set(WORKFLOW_TOOLS)
    assert registered(crm_agent) == SPECIALIST_TOOLS["crm"]
    assert registered(followup_agent) == SPECIALIST_TOOLS["followup"]
    assert registered(action_agent) == SPECIALIST_TOOLS["action"]


def test_no_market_ai_tool_is_reachable_from_the_crm_assistant():
    from pydantic_ai import Agent

    from app.crm.assistant import agent, routing, workflows
    from app.market_ai import agent as market_agent
    from app.market_ai import workflows as market_workflows

    market = set()
    for module in (market_agent, market_workflows):
        market |= {
            tool
            for value in vars(module).values()
            if isinstance(value, Agent)
            for tool in registered(value)
        }
    assert market == MARKET_TOOLS
    crm = set()
    for module in (agent, workflows, routing):
        crm |= {
            tool
            for value in vars(module).values()
            if isinstance(value, Agent)
            for tool in registered(value)
        }
    assert crm == CRM_TOOLS
    assert not crm & MARKET_TOOLS
    for case in CASES:
        assert set(case.expect.tools) <= CRM_TOOLS, case.id


def test_resources_action_kinds_and_statuses_are_the_codes():
    from app.assistant_actions.models import ActionKind, ActionStatus
    from app.crm.assistant.models import CrmAssistantResource

    assert RESOURCES == set(get_args(CrmAssistantResource))
    assert ACTION_KINDS == {kind.value for kind in ActionKind}
    assert set(get_args(ActionStatus)) <= FINAL_STATUSES


def test_every_probe_is_executable_against_the_crms_own_models():
    from app.assistant_actions.models import PAYLOAD_TYPES, ActionKind
    from app.crm.assistant.models import CrmAssistantQuery

    seeded = fixture.Seeded(
        orgs={"A": "a", "B": "b"},
        people={key: f"user-{key}" for key in fixture.PEOPLE},
        teams={key: f"team-{key}" for key in fixture.TEAMS},
        leads={key: n for n, key in enumerate(fixture.LEADS, 1)},
        events={key: n for n, key in enumerate(fixture.EVENTS, 1)},
        reminders={key: n for n, key in enumerate(fixture.REMINDERS, 1)},
        viewings={key: n for n, key in enumerate(fixture.VIEWINGS, 1)},
        listings={key: n for n, key in enumerate(fixture.LISTING_DRAFTS, 1)},
    )
    for case in CASES:
        if isinstance(case.probe, ReadProbe):
            CrmAssistantQuery(**case.probe.query)
        if isinstance(case.probe, ActionProbe):
            kind = ActionKind(case.probe.kind)
            PAYLOAD_TYPES[kind].model_validate(seeded.resolve(case.probe.payload))


def test_the_input_guard_refuses_exactly_the_guarded_questions():
    from app.chat.security import input_refusal

    for case in CASES:
        refused = input_refusal(case.question) is not None
        assert refused == isinstance(case.probe, GuardProbe), case.id


def test_roles_and_scenarios_are_all_covered():
    def ids(predicate):
        return [case.id for case in CASES if predicate(case)]

    for role in ("owner", "manager", "agent"):
        mine = [case for case in CASES if case.role == role]
        assert mine, role
        assert any(c.expect.write == "proposal" for c in mine), role
        assert any(c.expect.outcome == "refuse" for c in mine), role
        assert any(isinstance(c.probe, ReadProbe) for c in mine), role
    # The selected sample covers representative writes; the registry test above covers all kinds.
    assert {c.expect.action_kind for c in CASES} - {None} <= ACTION_KINDS
    categories = {case.category for case in CASES}
    assert {
        "tenant_isolation",
        "stale_context",
        "clarification",
        "unsupported",
        "security",
    } <= categories
    market = ids(lambda c: c.category == "unsupported" and isinstance(c.probe, NoProbe))
    assert len(market) == 1
    assert all(not next(c for c in CASES if c.id == i).expect.tools for i in market)
    # Pagination, confirmed-write success/failure, cancellation and stale proposals.
    assert ids(lambda c: isinstance(c.probe, ReadProbe) and (c.probe.query.get("offset") or 0) > 0)
    finals = {c.probe.final_status for c in CASES if isinstance(c.probe, ActionProbe)}
    assert {"succeeded", "failed"} <= finals
    assert ids(lambda c: isinstance(c.probe, ActionProbe) and c.probe.between)
    # At least one selected probe checks a record from the other organization.
    assert ids(lambda c: "B01" in json.dumps(c.probe.model_dump(mode="json")))


def test_every_allowed_write_is_proved_unwritten_until_confirmed():
    for case in CASES:
        if case.expect.write != "proposal":
            continue
        assert case.expect.confirmation_required, case.id
        probe = case.probe
        assert isinstance(probe, ActionProbe) and probe.proposal == "created", case.id
        assert probe.decision != "none", case.id
        if probe.final_status in {"succeeded", "not_connected"}:
            # A state that changes only after confirmation (or an outbox row nothing sends).
            assert any("after" in item.model_fields_set for item in probe.state), case.id


def test_the_fixture_is_synthetic():
    emails = [f"{key.lower()}@example.test" for key in fixture.LEADS]
    assert all(email.endswith("@example.test") for email in emails)
    assert all(fixture._contact_phone(n).startswith("+97150000") for n in range(1, 99))
    # Every actor is a fixture person whose CRM role is what the case says.
    assert all(fixture.role_of(case.actor) == case.role for case in CASES)


def raw():
    return json.loads(BENCHMARK.read_text())


def invalid(mutate) -> None:
    document = raw()
    mutate(document)
    with pytest.raises(ValidationError):
        CrmBenchmark.model_validate(document)


def case_with(document, case_id):
    return next(case for case in document["cases"] if case["id"] == case_id)


def first(predicate):
    return next(case.id for case in CASES if predicate(case))


def test_the_schema_rejects_cases_that_could_not_be_trusted():
    write = first(lambda c: c.expect.write == "proposal")
    read = first(lambda c: isinstance(c.probe, ReadProbe))
    agent_case = first(lambda c: c.role == "agent")

    # A market tool, a write without confirmation, a role the actor does not hold, an unknown
    # fixture record, an unknown CRM resource, a duplicate ID and a 31st duplicate question.
    invalid(lambda d: case_with(d, read)["expect"]["tools"].append("query_market_metrics"))
    invalid(lambda d: case_with(d, write)["expect"].update(confirmation_required=False))
    invalid(lambda d: case_with(d, agent_case).update(role="owner"))
    invalid(lambda d: case_with(d, write)["probe"]["payload"].update(lead_id="@lead:L99"))
    invalid(lambda d: case_with(d, read)["probe"]["query"].update(resource="market_prices"))
    invalid(lambda d: d["cases"][1].update(id=d["cases"][0]["id"]))
    invalid(lambda d: d["cases"][1].update(question=d["cases"][0]["question"]))
    invalid(lambda d: d.update(fixture="another-fixture"))
