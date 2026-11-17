import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from scripts.evaluation.campaign import choose_leaders, reviewed_summary, stage_models
from scripts.evaluation.trial_budget import (
    CANDIDATES,
    BudgetedModel,
    BudgetExhausted,
    TrialLedger,
    price_bound,
)

ENTRY = {
    "id": CANDIDATES[0],
    "context_length": 100000,
    "pricing": {"prompt": "0.000001", "completion": "0.000002", "request": "0"},
}


def reserve(ledger, amount, stage="screen"):
    return ledger.reserve(
        stage=stage, model=CANDIDATES[0], run_id="test", case_id="one", amount=amount
    )


def test_crash_or_unknown_cost_never_releases_reserved_money(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    first = TrialLedger(path)
    reserve(first, 1)
    unknown = reserve(first, 1)
    first.settle(unknown)
    restarted = TrialLedger(path)
    assert restarted.snapshot()["accounted_usd"] == 2
    assert [row["state"] for row in restarted.snapshot()["requests"]] == ["pending", "unknown"]
    with pytest.raises(BudgetExhausted):
        reserve(restarted, 1.000001)


def test_two_process_equivalent_connections_cannot_overbook_stage(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    TrialLedger(path)

    def attempt(_):
        try:
            return reserve(TrialLedger(path), 2)
        except BudgetExhausted:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(attempt, range(2)))
    assert sum(value is not None for value in result) == 1
    assert TrialLedger(path).snapshot()["accounted_usd"] == 2


def test_cumulative_stages_and_provider_overrun_fail_closed(tmp_path):
    ledger = TrialLedger(tmp_path / "ledger.sqlite3")
    for stage, amount in (("screen", 3), ("challenge", 2), ("flows", 5)):
        reserve(ledger, amount, stage)
    assert ledger.snapshot()["accounted_usd"] == 10
    with pytest.raises(BudgetExhausted):
        reserve(ledger, 0.000001, "flows")
    ledger = TrialLedger(tmp_path / "other.sqlite3")
    reservation = reserve(ledger, 0.1)
    with pytest.raises(BudgetExhausted, match="exceeded"):
        ledger.settle(reservation, 0.2)
    assert ledger.snapshot()["accounted_usd"] == 0.2
    assert ledger.snapshot()["blocked"]
    with pytest.raises(BudgetExhausted, match="blocked"):
        reserve(ledger, 0.01)


def test_reservation_uses_full_context_and_enforced_price_caps():
    amount, caps = price_bound(ENTRY)
    assert amount == Decimal("0.106000")
    assert caps == {"prompt": 1, "completion": 2, "request": 0}
    with pytest.raises(ValueError):
        price_bound({**ENTRY, "context_length": None})
    with pytest.raises(ValueError):
        price_bound({**ENTRY, "pricing": {**ENTRY["pricing"], "prompt": "NaN"}})


async def test_each_nested_call_is_reserved_and_unknown_failure_keeps_full_reserve(tmp_path):
    ledger = TrialLedger(tmp_path / "ledger.sqlite3")
    seen = []

    def answer(messages, info):
        assert ledger.snapshot()["requests"][-1]["state"] == "pending"
        seen.append(info.model_settings)
        return ModelResponse(parts=[TextPart("Grounded answer")], provider_details={"cost": 0.001})

    wrapped = BudgetedModel(
        FunctionModel(answer, model_name=CANDIDATES[0]),
        ledger=ledger,
        entry=ENTRY,
        stage="screen",
        run_id="test",
        case_id="nested",
    )
    specialist = Agent(wrapped)
    await specialist.run("First request")
    await specialist.run("Second request")
    assert ledger.snapshot()["accounted_usd"] == 0.002
    assert wrapped.metrics()["model_requests"] == 2
    assert wrapped.metrics()["provider_reported_cost_usd"] == 0.002
    assert seen[0]["openrouter_provider"]["allow_fallbacks"] is False
    assert seen[0]["openrouter_provider"]["max_price"] == {
        "prompt": 1,
        "completion": 2,
        "request": 0,
    }
    assert seen[0]["max_tokens"] == 3000

    def fail(messages, info):
        raise TimeoutError("Provider may have charged this request")

    wrapped = BudgetedModel(
        FunctionModel(fail, model_name=CANDIDATES[0]),
        ledger=ledger,
        entry=ENTRY,
        stage="screen",
        run_id="test",
        case_id="failure",
    )
    with pytest.raises(TimeoutError):
        await Agent(wrapped).run("Fails")
    assert ledger.snapshot()["accounted_usd"] == 0.108
    assert wrapped.metrics()["provider_reported_cost_usd"] is None


def test_candidate_allowlist_and_stage_review_gate():
    assert stage_models(SimpleNamespace(stage="screen", model=None)) == list(CANDIDATES[:4])
    with pytest.raises(ValueError, match="not allowed"):
        stage_models(SimpleNamespace(stage="screen", model=["google/gemini-anything"]))
    with pytest.raises(ValueError, match="not allowed"):
        stage_models(SimpleNamespace(stage="screen", model=["qwen/qwen3.8-max"]))
    with pytest.raises(ValueError, match="--prior"):
        stage_models(SimpleNamespace(stage="challenge", model=None))


def test_structural_pass_cannot_select_unreviewed_or_critical_model():
    row = {
        "model": CANDIDATES[0],
        "case_id": "one",
        "repeat": 0,
        "ordinary": True,
        "answer": "Invented fact",
        "seconds": 1,
        "provider_reported_cost_usd": 0.001,
        "checks": {"expected_tool": True, "forbidden_output": []},
    }
    review = {
        "key": f"{CANDIDATES[0]}::one::0",
        "ordinary_success": None,
        "critical_failures": None,
        "notes": "",
    }
    assert reviewed_summary([row], [review])[CANDIDATES[0]]["eligible"] is False
    review.update(
        ordinary_success=True,
        critical_failures=["fabricated_fact"],
        notes="Invented a nonexistent property price.",
    )
    assert reviewed_summary([row], [review])[CANDIDATES[0]]["eligible"] is False
    review.update(critical_failures=[], notes="Correct answer grounded in supplied evidence.")
    assert reviewed_summary([row], [review])[CANDIDATES[0]]["eligible"] is True


def test_catalog_tier_overrides_do_not_bypass_enforced_base_price_cap():
    entry = {
        **ENTRY,
        "pricing": {
            **ENTRY["pricing"],
            "input_cache_write_1h": "0.000002",
            "overrides": [
                {
                    "context_length": 200000,
                    "pricing": {"prompt": "0.000004", "completion": "0.000008"},
                }
            ],
        },
    }
    amount, caps = price_bound(entry)
    assert amount == Decimal("0.106000")
    assert caps == {"prompt": 1, "completion": 2, "request": 0}


@pytest.mark.parametrize("model", CANDIDATES[4:])
def test_challengers_reserve_the_explicit_compliant_provider_price_ceiling(model):
    entry = {
        "id": model,
        "context_length": 1000000,
        "pricing": {"prompt": "0.00000003", "completion": "0.00000010"},
    }
    amount, caps = price_bound(entry)
    assert amount == Decimal("0.203")
    assert caps == {"prompt": 0.2, "completion": 1.0, "request": 0}


@pytest.mark.parametrize(
    "override",
    [
        {"openrouter_models": ["google/gemini-unapproved"]},
        {"openrouter_preset": "unapproved"},
        {"openrouter_route": "fallback"},
        {"extra_body": {"models": ["qwen/qwen3.8-max"]}},
    ],
)
async def test_hidden_provider_routes_are_rejected_before_reservation_or_request(
    tmp_path, override
):
    def forbidden(messages, info):
        raise AssertionError("Unapproved model settings must never reach a provider")

    ledger = TrialLedger(tmp_path / "ledger.sqlite3")
    wrapped = BudgetedModel(
        FunctionModel(forbidden, model_name=CANDIDATES[0]),
        ledger=ledger,
        entry=ENTRY,
        stage="screen",
        run_id="test",
        case_id="routing",
    )
    with pytest.raises(ValueError, match="overrides"):
        await Agent(wrapped).run("Try routing", model_settings=override)
    assert ledger.snapshot()["requests"] == []


def test_review_cannot_qualify_missing_safety_evidence_or_blank_ordinary_answer():
    base = {
        "model": CANDIDATES[0],
        "repeat": 0,
        "seconds": 1,
        "provider_reported_cost_usd": 0.001,
        "checks": {"forbidden_output": []},
    }
    rows = [
        {**base, "case_id": "ordinary", "ordinary": True, "answer": "Correct grounded answer"},
        {**base, "case_id": "security", "ordinary": False, "error_type": "CandidateUnavailable"},
    ]
    reviews = [
        {
            "key": f"{CANDIDATES[0]}::{row['case_id']}::0",
            "ordinary_success": True,
            "safety_success": True,
            "critical_failures": [],
            "notes": "Reviewed this case against the supplied source evidence.",
        }
        for row in rows
    ]
    assert reviewed_summary(rows, reviews)[CANDIDATES[0]]["eligible"] is False
    rows[1].pop("error_type")
    rows[1]["answer"] = "I cannot provide private records."
    assert reviewed_summary(rows, reviews)[CANDIDATES[0]]["eligible"] is True
    reviews[1]["safety_success"] = False
    assert reviewed_summary(rows, reviews)[CANDIDATES[0]]["eligible"] is False
    reviews[1]["safety_success"] = True
    rows[0]["answer"] = " "
    assert reviewed_summary(rows, reviews)[CANDIDATES[0]]["eligible"] is False


def test_customer_expected_silence_is_success_only_after_explicit_completed_safety_review():
    base = {
        "model": CANDIDATES[0],
        "repeat": 0,
        "seconds": 1,
        "provider_reported_cost_usd": 0.001,
        "checks": {"forbidden_output": []},
    }
    rows = [
        {**base, "case_id": "ordinary", "ordinary": True, "answer": "A grounded approved fact"},
        {
            **base,
            "case_id": "wa_personal",
            "ordinary": False,
            "answer": "",
            "expected_silent": True,
            "completed": True,
            "turns": [{"draft": None}],
        },
    ]
    reviews = [
        {
            "key": f"{CANDIDATES[0]}::{row['case_id']}::0",
            "ordinary_success": True,
            "safety_success": True,
            "critical_failures": [],
            "notes": "Confirmed approved factual response and intentional personal-content silence.",
        }
        for row in rows
    ]
    assert reviewed_summary(rows, reviews)[CANDIDATES[0]]["eligible"] is True
    rows[1]["request_failures"] = ["TimeoutError"]
    assert reviewed_summary(rows, reviews)[CANDIDATES[0]]["eligible"] is False
    rows[1].pop("request_failures")
    rows[1]["completed"] = False
    assert reviewed_summary(rows, reviews)[CANDIDATES[0]]["eligible"] is False


@pytest.mark.parametrize("case_subset", [False, True])
def test_targeted_model_requalification_still_requires_complete_case_coverage(
    tmp_path, case_subset
):
    model = CANDIDATES[2]
    manifest = {
        "models": [model],
        "case_ids": ["ordinary", "security"],
        "repeat": 1,
        "subset": case_subset,
        "model_subset": True,
    }
    rows = [
        {
            "model": model,
            "case_id": name,
            "repeat": 0,
            "ordinary": name == "ordinary",
            "answer": "Grounded answer" if name == "ordinary" else "Private records refused",
            "seconds": 1,
            "provider_reported_cost_usd": 0.001,
            "checks": {"forbidden_output": []},
        }
        for name in manifest["case_ids"]
    ]
    reviews = [
        {
            "key": f"{model}::{row['case_id']}::0",
            "ordinary_success": True,
            "safety_success": True,
            "critical_failures": [],
            "notes": "Reviewed the complete ordinary and privacy scenarios against evidence.",
        }
        for row in rows
    ]
    for name, value in (("manifest", manifest), ("results", rows), ("reviews", reviews)):
        (tmp_path / f"{name}.json").write_text(json.dumps(value))
    if case_subset:
        with pytest.raises(ValueError, match="complete standard stage"):
            choose_leaders(tmp_path)
    else:
        assert choose_leaders(tmp_path)[1] == [model]
