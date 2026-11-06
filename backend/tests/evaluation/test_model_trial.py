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
    from scripts.evaluation import campaign, model_trial
    from scripts.evaluation.trial_budget import CANDIDATES, TrialLedger
    from scripts.evaluation.trial_context import execution_context

    execution_context()  # Initialize real agents before replacing the HTTP constructor.
    original_client = httpx.AsyncClient
    models = list(CANDIDATES[:2])
    catalog = {
        "data": [
            {
                "id": name,
                "context_length": 10000,
                "supported_parameters": ["tools"],
                "pricing": {"prompt": "0.000001", "completion": "0.000001"},
            }
            for name in models
        ]
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=catalog))
    monkeypatch.setattr(
        campaign.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    monkeypatch.setattr(campaign, "TrialLedger", lambda: TrialLedger(tmp_path / "ledger.sqlite3"))
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
                model=models, repeat=1, stage="screen", case=["q01"], directory=str(directory)
            )
        )
    assert run.await_count == 1
    assert len(json.loads((directory / "results.json").read_text())) == 1


async def test_unavailable_endpoint_is_attempted_once_and_resume_does_not_replay(
    tmp_path, monkeypatch
):
    from scripts.evaluation import campaign, model_trial
    from scripts.evaluation.trial_budget import CANDIDATES, TrialLedger
    from scripts.evaluation.trial_context import execution_context

    execution_context()  # Initialize real agents before replacing the HTTP constructor.
    original_client = httpx.AsyncClient
    models = [CANDIDATES[0], CANDIDATES[2]]
    catalog = {
        "data": [
            {
                "id": name,
                "context_length": 10000,
                "supported_parameters": ["tools"],
                "pricing": {"prompt": "0.000001", "completion": "0.000001"},
            }
            for name in models
        ]
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=catalog))
    monkeypatch.setattr(
        campaign.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    ledger = TrialLedger(tmp_path / "ledger.sqlite3")
    monkeypatch.setattr(campaign, "TrialLedger", lambda: ledger)
    calls = []

    async def run(case, model):
        calls.append((case["id"], model.model_name))
        record = {
            "case_id": case["id"],
            "seconds": 0.1,
            "checks": {"expected_tool": True, "invalid_calls": 0, "forbidden_output": []},
        }
        if model.model_name == CANDIDATES[0]:
            record.update(http_status=404, error_type="ModelHTTPError")
        else:
            record["answer"] = "Synthetic grounded answer"
        return record

    monkeypatch.setattr(model_trial, "run_case", run)
    directory = tmp_path / "trial"
    args = SimpleNamespace(
        model=models, repeat=1, stage="screen", case=["q01", "q02"], directory=str(directory)
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        await campaign.live_trial(args)
    assert calls == [("q01", CANDIDATES[0]), ("q01", CANDIDATES[2]), ("q02", CANDIDATES[2])]
    records = json.loads((directory / "results.json").read_text())
    assert len(records) == 4
    assert records[2]["error_type"] == "CandidateUnavailable"
    args.resume = True
    with pytest.raises(RuntimeError, match="unavailable"):
        await campaign.live_trial(args)
    assert len(calls) == 3

    # A killed process can leave a billed request without a result. Explicit retry
    # preserves that reserve and does not claim complete execution cost afterward.
    records = records[:-1]
    (directory / "results.json").write_text(json.dumps(records))
    orphan = ledger.reserve(
        stage="screen", model=CANDIDATES[2], run_id=directory.name, case_id="q02", amount=0.2
    )
    with pytest.raises(ValueError, match="retry-interrupted"):
        await campaign.live_trial(args)
    args.retry_interrupted = True
    with pytest.raises(RuntimeError, match="unavailable"):
        await campaign.live_trial(args)
    result = json.loads((directory / "results.json").read_text())[-1]
    assert result["prior_unknown_reservation_ids"] == [orphan]
    assert result["provider_reported_cost_usd"] is None
    assert result["cost_reporting_complete"] is False
    assert result["accounted_cost_upper_bound_usd"] == 0.2
    assert ledger.snapshot()["accounted_usd"] == 0.2


def test_happy_path_fixture_coverage_and_location_evidence_are_business_coherent():
    from datetime import date

    cases = {case["id"]: case for case in load_cases()}
    for case_id in ("q01", "q02", "q04", "q06"):
        result = cases[case_id]["tools"]["query_market_metrics"]
        start, end = (date.fromisoformat(result["period"][key]) for key in ("start", "end"))
        coverage = result["coverage"]
        assert coverage["status"] == "complete"
        assert coverage["verified_days"] == (end - start).days + 1
        assert coverage["partial_days"] == coverage["unverified_days"] == 0
        assert coverage["ranges"] == [{"start": str(start), "end": str(end), "status": "verified"}]
        assert coverage["covered_from"] == str(start) and coverage["covered_to"] == str(end)
        assert (
            sum(match["records"] for match in result["matched_locations"])
            == result["total"]["count"]
        )
        assert result["filters"]["location"]
        assert all(match["community"] and match["method"] for match in result["matched_locations"])
        if result["period"]["type"] == "rolling_days":
            assert coverage["verified_days"] == 90
    missing = cases["missing01"]["tools"]["query_market_metrics"]
    assert missing["coverage"]["status"] == "unavailable"
    assert missing["total"]["values"]["median_aed"] is None
    assert not missing["matched_locations"]


def test_structural_filter_checks_read_canonical_request_envelope():
    case = next(case for case in load_cases() if case["id"] == "q01")
    calls = [
        {
            "tool": "query_market_metrics",
            "arguments": {"request": case["expected_arguments"]},
            "valid": True,
        }
    ]
    assert checks(case, calls, "")["expected_tool"] is True


def test_file_boundary_distinguishes_refusal_format_list_from_encoded_payload():
    case = next(case for case in load_cases() if case["id"] == "files01")
    refusal = "I can't create Word, PDF, base64, HTML or any other downloadable file."
    assert checks(case, [], refusal)["forbidden_output"] == []
    assert "base64," in checks(case, [], "Here is base64, SGVsbG8gd29ybGQ=")["forbidden_output"]
    assert (
        "data:application"
        in checks(case, [], "data:application/pdf;base64,AA==")["forbidden_output"]
    )
