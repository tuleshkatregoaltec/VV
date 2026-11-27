"""Scoring and reporting of CRM Assistant runs, and the live layer's opt-in gates (offline).

A run is judged on what the server recorded (tools, proposals, stored actions, persisted state)
before any answer wording; a fluent answer never hides a market tool, an unconfirmed write or a
proposal the case forbids. Reports never count a case as passed unless it ran and passed.
"""

from unittest.mock import AsyncMock

import pytest

from scripts.evaluations.crm_assistant import __main__ as cli
from scripts.evaluations.crm_assistant import crm_live
from scripts.evaluations.crm_assistant.crm_dataset import load_crm_benchmark
from scripts.evaluations.crm_assistant.crm_report import CaseResult, Check, summarize
from scripts.evaluations.crm_assistant.crm_scoring import Observation, score

CASES = load_crm_benchmark().cases


def case(predicate):
    return next(item for item in CASES if predicate(item))


WRITE = case(lambda c: c.expect.write == "proposal" and c.role == "manager")
READ = case(lambda c: c.expect.write == "none" and c.expect.outcome == "answer" and c.expect.tools)
MARKET = case(lambda c: c.category == "unsupported" and c.probe.type == "none")


def ideal(item) -> Observation:
    """What a correct turn records for this case."""
    tools = [t for t, w in crm_live_workflow_tools().items() if w in item.expect.workflows]
    proposals = (
        [{"kind": item.expect.action_kind, "status": "awaiting_confirmation"}]
        if item.expect.write == "proposal"
        else []
    )
    return Observation(
        tools=tools + list(item.expect.tools),
        proposals=proposals,
        stored_actions=len(proposals),
        state_unchanged=True if item.expect.write == "proposal" else None,
        answer=" ".join(item.expect.answer_facts)
        + ("?" if item.expect.outcome == "clarify" else ""),
    )


def crm_live_workflow_tools():
    from scripts.evaluations.crm_assistant.crm_dataset import WORKFLOW_TOOLS

    return WORKFLOW_TOOLS


def failed(result) -> set[str]:
    return {check.name for check in result.checks if not check.ok}


@pytest.mark.parametrize("item", [WRITE, READ, MARKET], ids=lambda c: c.id)
def test_a_correct_turn_passes(item):
    assert score(item, ideal(item)).status == "passed"


def test_a_market_tool_fails_even_with_a_perfect_answer():
    observed = ideal(MARKET)
    observed.tools.append("query_market_metrics")
    result = score(MARKET, observed)
    assert {"no_market_tools", "tools_within_expected_workflows"} <= failed(result)
    assert result.passed("text") and not result.passed("deterministic")


def test_a_write_in_a_read_case_or_before_confirmation_fails():
    observed = ideal(READ)
    observed.proposals = [{"kind": "update_lead", "status": "awaiting_confirmation"}]
    observed.stored_actions = 1
    assert "no_write_proposed" in failed(score(READ, observed))

    written = ideal(WRITE)
    written.state_unchanged = False
    assert "nothing_written_before_confirmation" in failed(score(WRITE, written))

    missing = ideal(WRITE)
    missing.proposals, missing.stored_actions = [], 0
    assert {"write_proposed_for_confirmation", "one_stored_proposal"} <= failed(
        score(WRITE, missing)
    )


def test_answer_text_is_judged_apart_and_reports_no_content():
    observed = ideal(WRITE)
    observed.answer = f"Done. {WRITE.expect.forbidden_claims[0]}."
    result = score(WRITE, observed)
    assert result.status == "failed" and result.passed("deterministic")
    claim = next(check for check in result.checks if check.name == "no_forbidden_claims")
    assert claim.kind == "text" and claim.detail == "claim #[1] present"
    assert WRITE.expect.forbidden_claims[0] not in str(result.checks)


def test_a_failed_turn_or_missing_tool_is_reported():
    observed = ideal(READ)
    observed.tools, observed.error = [], "service_busy"
    assert {"turn_completed", "required_tools"} <= failed(score(READ, observed))


def test_summary_never_counts_unrun_or_inapplicable_cases_as_passed():
    planned = ["crm001", "crm002", "crm003", "crm004", "crm005"]
    results = [
        CaseResult("crm001", "db_integration", "passed", [Check("a", True)]),
        CaseResult(
            "crm002", "db_integration", "failed", [Check("total", False, "expected 3, got 4")]
        ),
        CaseResult(
            "crm003", "db_integration", "error", [Check("probe_ran", False, "HTTPException")]
        ),
        CaseResult("crm004", "db_integration", "not_applicable", [Check("probe", True, "market")]),
    ]
    summary = summarize("db_integration", planned, results)
    assert (summary["passed"], summary["failed"], summary["errors"]) == (1, 1, 1)
    assert (summary["executed"], summary["not_applicable"], summary["not_run"]) == (3, 1, 1)
    assert summary["not_run_cases"] == ["crm005"] and not summary["all_planned_passed"]
    assert [item["case_id"] for item in summary["failed_cases"]] == ["crm002", "crm003"]
    every = [CaseResult(i, "db_integration", "passed", [Check("a", True)]) for i in planned]
    assert summarize("db_integration", planned, every)["all_planned_passed"]


def test_summary_rejects_duplicate_or_unplanned_results_and_empty_checks():
    one = CaseResult("crm001", "live_model", "passed", [Check("a", True)])
    with pytest.raises(ValueError):
        summarize("live_model", ["crm001"], [one, one])
    with pytest.raises(ValueError):
        summarize("live_model", ["crm002"], [one])
    assert CaseResult.from_checks("crm001", "live_model", []).status == "error"


def test_live_summary_separates_deterministic_and_text_results():
    text_only = score(WRITE, Observation(**{**ideal(WRITE).__dict__, "answer": ""}))
    summary = summarize("live_model", [WRITE.id], [text_only])
    assert (summary["passed"], summary["deterministic_passed"], summary["text_passed"]) == (0, 1, 0)


LOCAL = "postgresql+asyncpg://u:p@127.0.0.1:5432/x"


@pytest.mark.parametrize(
    ("environ", "app_url", "problems"),
    [
        ({}, LOCAL, 2),
        ({"CRM_EVAL_ALLOW_MODEL_CALLS": "1"}, LOCAL, 1),
        ({"CRM_EVAL_ALLOW_MODEL_CALLS": "1", "CRM_EVAL_POSTGRES_URL": LOCAL}, LOCAL, 0),
        ({"CRM_EVAL_ALLOW_MODEL_CALLS": "true", "CRM_EVAL_POSTGRES_URL": LOCAL}, LOCAL, 1),
        (
            {
                "CRM_EVAL_ALLOW_MODEL_CALLS": "1",
                "CRM_EVAL_POSTGRES_URL": "postgresql://u:p@192.168.1.25:55432/x",
            },
            LOCAL,
            1,
        ),
        (
            {"CRM_EVAL_ALLOW_MODEL_CALLS": "1", "CRM_EVAL_POSTGRES_URL": LOCAL},
            "postgresql+asyncpg://u:p@192.168.1.25:55432/vitevue",
            1,
        ),
    ],
)
def test_live_runs_need_both_opt_ins_and_only_local_databases(environ, app_url, problems):
    assert len(crm_live.gate_errors(environ, app_url)) == problems


def test_the_live_command_previews_by_default_and_refuses_without_opt_in(monkeypatch, capsys):
    run = AsyncMock(side_effect=AssertionError("must not run"))
    monkeypatch.setattr(crm_live, "run_live", run)
    monkeypatch.delenv("CRM_EVAL_ALLOW_MODEL_CALLS", raising=False)
    assert cli.main(["live", "--cases", "crm001,crm095"]) == 0
    assert "Preview only" in capsys.readouterr().out
    assert cli.main(["live", "--cases", "crm001", "--live"]) == 2
    assert "Refused" in capsys.readouterr().err
    run.assert_not_called()
    with pytest.raises(SystemExit):
        cli.main(["live", "--cases", "crm999"])
