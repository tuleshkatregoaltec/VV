import json
from types import SimpleNamespace

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from scripts.evaluation.http_trial import (
    CURRENT_CASE,
    HTTPBudgetedModel,
    application_plan,
    load_http_flow_cases,
)
from scripts.evaluation.trial_budget import CANDIDATES, TrialLedger
from scripts.evaluation.trial_context import execution_context, historical_compatibility


async def test_http_nested_model_calls_require_case_context_and_same_global_ledger(tmp_path):
    ledger = TrialLedger(tmp_path / "ledger.sqlite3")
    entry = {
        "id": CANDIDATES[2],
        "context_length": 100000,
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
    }

    def respond(messages, info):
        assert ledger.snapshot()["requests"][-1]["state"] == "pending"
        return ModelResponse(parts=[TextPart("Grounded")], provider_details={"cost": 0.002})

    model = HTTPBudgetedModel(
        FunctionModel(respond, model_name=CANDIDATES[2]),
        plan={"catalog_entry": entry, "run_id": "http-run"},
        directory=tmp_path,
        ledger=ledger,
    )
    with pytest.raises(RuntimeError, match="case context"):
        await Agent(model).run("No authorized case")
    assert ledger.snapshot()["requests"] == []
    token = CURRENT_CASE.set("q01")
    try:
        await Agent(model).run("Router")
        await Agent(model).run("Specialist")
    finally:
        CURRENT_CASE.reset(token)
    assert ledger.snapshot()["accounted_usd"] == 0.004
    assert {row["case_id"] for row in ledger.snapshot()["requests"]} == {"q01"}
    assert {row["stage"] for row in ledger.snapshot()["requests"]} == {"flows"}
    evidence = [
        json.loads(line) for line in (tmp_path / "request-costs.jsonl").read_text().splitlines()
    ]
    assert (
        len(evidence) == 2 and sum(row["provider_reported_cost_usd"] for row in evidence) == 0.004
    )


def test_http_runner_cannot_bypass_selection_or_pinned_database_boundaries(tmp_path, monkeypatch):
    from scripts.evaluation import http_trial

    with pytest.raises(ValueError, match="--model"):
        application_plan(
            model=None, prior=None, snapshot_path=None, data_context="mutable", settings=None
        )
    context = execution_context()
    monkeypatch.setattr(
        http_trial,
        "choose_leaders",
        lambda path: (
            {
                "stage": "challenge",
                "execution_context": context,
                "catalog": {
                    CANDIDATES[2]: {
                        "id": CANDIDATES[2],
                        "context_length": 10000,
                        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    }
                },
            },
            [CANDIDATES[2], CANDIDATES[3]],
        ),
    )
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "snapshot_id": "fixed",
                "postgres_database": "eval_pg",
                "clickhouse_database": "eval_ch",
                "reference_sha256": "a" * 64,
            }
        )
    )
    settings = SimpleNamespace(
        POSTGRES_URL="postgresql+asyncpg://offline:offline@localhost/shared",
        CLICKHOUSE_HOST="localhost",
        CLICKHOUSE_DATABASE="eval_ch",
    )
    with pytest.raises(ValueError, match="do not match"):
        application_plan(
            model=CANDIDATES[2],
            prior=tmp_path,
            snapshot_path=snapshot,
            data_context="pinned:fixed",
            settings=settings,
        )


def test_http_multiturn_cases_are_explicit_and_historical_missing_context_is_not_equivalent(
    tmp_path,
):
    cases = load_http_flow_cases(["route_multiturn"])
    assert len(cases[0].turns) == 2
    with pytest.raises(ValueError, match="customer"):
        load_http_flow_cases(["wa_qualify"])
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "manifest.json").write_text("{}")
    (second / "manifest.json").write_text("{}")
    assert historical_compatibility(first, second)["comparable"] is False


def test_legacy_http_gemini_artifacts_are_preserved_as_incomparable_without_rerun(tmp_path):
    current, old = tmp_path / "current", tmp_path / "old"
    current.mkdir()
    old.mkdir()
    (current / "manifest.json").write_text(json.dumps({"scope": "synthetic", "case_ids": ["q01"]}))
    (old / "run.json").write_text(json.dumps({"case_ids": ["q01"], "dataset_sha256": "legacy"}))
    (old / "runtime.json").write_text(json.dumps({"configured_model": "google/legacy-gemini"}))
    result = historical_compatibility(current, old)
    assert result["comparable"] is False
    assert result["historical_format"] == "run.json"
    assert result["historical_configured_model"] == "google/legacy-gemini"
    assert "execution_context" in result["differences"]


async def test_http_release_pin_failure_blocks_app_before_any_model_call(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from app.market import releases
    from scripts.evaluation import fixture_snapshot
    from scripts.evaluation.http_trial import CaseBudgetContext

    verification = AsyncMock(return_value={"verified": True})
    monkeypatch.setattr(fixture_snapshot, "use_snapshot", verification)

    @asynccontextmanager
    async def changed_pin():
        yield SimpleNamespace(missing=(), versions={"sales": SimpleNamespace(release_id="changed")})

    monkeypatch.setattr(releases, "pin_market_release", changed_pin)
    app = AsyncMock()
    guarded = CaseBudgetContext(
        app,
        {
            "case_ids": ["q01"],
            "snapshot_path": str(tmp_path / "snapshot.json"),
            "snapshot": {"release_ids": {"sales": "fixed"}},
        },
    )
    with pytest.raises(RuntimeError, match="release changed"):
        await guarded(
            {
                "type": "http",
                "path": "/api/v1/chat/conversations/1/messages/stream",
                "headers": [(b"x-vv-evaluation-case", b"q01")],
            },
            AsyncMock(),
            AsyncMock(),
        )
    verification.assert_awaited_once()
    app.assert_not_awaited()
    assert CURRENT_CASE.get() is None
