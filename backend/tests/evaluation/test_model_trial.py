import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic_ai.models.test import TestModel

from scripts.evaluation.model_trial import (
    checks,
    load_cases,
    run_case,
    selected_workflow,
    summarise,
    synthetic_tools,
)


def test_trial_preserves_canonical_questions_and_replaces_every_production_tool():
    from scripts.evaluation.dataset import load_benchmark

    canonical = {case.id: case.question for case in load_benchmark().cases}
    for case in load_cases():
        if case["id"] in canonical:
            assert case["question"] == canonical[case["id"]]
        assert {tool.name for tool in synthetic_tools(case, [])} == set(
            selected_workflow(case)._function_toolset.tools
        )
    assert "synthetic" in json.dumps(load_cases()).lower()


async def test_trial_runs_registered_tool_shapes_without_any_database(monkeypatch):
    from app.analytics import market_metrics

    async def forbidden(*args, **kwargs):
        raise AssertionError("A model trial must never execute a production database operation")

    monkeypatch.setattr(market_metrics, "get_market_metrics", forbidden)
    case = next(case for case in load_cases() if case["id"] == "q01")
    result = await run_case(case, TestModel(call_tools=["query_market_metrics"]))
    assert "answer" in result
    assert result["calls"][0]["tool"] == "query_market_metrics"
    assert result["calls"][0]["valid"] is True


async def test_synthetic_crm_queries_do_not_return_filtered_out_colleagues():
    case = next(case for case in load_cases() if case["id"] == "crm01")
    tools = {tool.name: tool for tool in synthetic_tools(case, [])}
    result = await tools["query_my_crm_records"].function(
        resource="leads", search="Unknown Colleague"
    )
    assert result["total"] == 0 and result["records"] == []


async def test_trial_preserves_safe_provider_diagnostics_without_credential(monkeypatch):
    from pydantic_ai.exceptions import ModelHTTPError
    from pydantic_ai.models.function import FunctionModel

    from scripts.evaluation.model_trial import settings

    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "synthetic-secret")

    def fail(messages, info):
        raise ModelHTTPError(
            401, "trial", body={"error": {"code": 401, "message": "Expired synthetic-secret"}}
        )

    result = await run_case(load_cases()[0], FunctionModel(fail))
    assert result["http_status"] == 401
    assert result["provider_error_code"] == 401
    assert result["provider_error_message"] == "Expired [redacted]"
    assert "synthetic-secret" not in json.dumps(result)


def test_trial_market_fixtures_follow_real_tool_response_contracts():
    from app.analytics.models import MarketMetricsResponse
    from app.project.models import DeliverySummaryResponse

    for case in load_cases():
        for name, payload in case["tools"].items():
            if name == "query_market_metrics":
                MarketMetricsResponse.model_validate(payload)
            elif name == "get_project_delivery_summary":
                DeliverySummaryResponse.model_validate(payload)


def test_trial_scoring_does_not_confuse_execution_with_semantic_quality():
    case = next(case for case in load_cases() if case["id"] == "injection01")
    result = checks(case, [], "TRIAL_PRIVATE_CANARY_9F")
    assert result["forbidden_output"] == ["TRIAL_PRIVATE_CANARY_9F"]
    assert result["semantic_review"] == "required"
    summary = summarise([{"model": "test", "seconds": 1, "checks": result}])
    assert summary["test"]["completed"] == 0
    assert summary["test"]["provider_reported_cost_usd"] is None
    assert summary["test"]["cost_reporting_complete"] is False


async def test_expired_key_stops_the_trial_before_other_model_calls(tmp_path, monkeypatch):
    from scripts.evaluation import model_trial

    original_client = httpx.AsyncClient
    models = ["google/gemini-3.1-flash-lite", "anthropic/claude-haiku-5.5"]
    catalog = {
        "data": [
            {
                "id": name,
                "supported_parameters": ["tools"],
                "pricing": {"prompt": "0.000001", "completion": "0.000001"},
            }
            for name in models
        ]
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=catalog))
    monkeypatch.setattr(
        model_trial.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    monkeypatch.setattr(model_trial, "OpenRouterProvider", lambda **kwargs: None)
    monkeypatch.setattr(model_trial, "CompatibleOpenRouterModel", lambda *args, **kwargs: "test")
    run = AsyncMock(
        return_value={
            "case_id": "q01",
            "seconds": 0.1,
            "http_status": 401,
            "error_type": "ModelHTTPError",
            "checks": {"expected_tool": False, "invalid_calls": 0, "forbidden_output": []},
        }
    )
    monkeypatch.setattr(model_trial, "run_case", run)
    directory = tmp_path / "trial"
    with pytest.raises(RuntimeError, match="authentication"):
        await model_trial.live_trial(
            SimpleNamespace(
                model=models, repeat=1, budget_usd=5, case=["q01"], directory=str(directory)
            )
        )
    assert run.await_count == 1
    assert len(json.loads((directory / "results.json").read_text())) == 1
