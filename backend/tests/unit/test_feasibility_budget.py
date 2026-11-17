"""Feasibility LLM runs share the assistant's per-user admission, and HBU studies are cached.

Before: /hbu/{plot}, /generate-study and /chat/stream ran uncapped model work for any
subscribed user (no cache, no rate limit, no token quota) and returned str(exc) to clients.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.chat import admission, budget
from app.chat import operations as chat_operations
from app.feasibility import chat, generation, hbu_agent
from app.feasibility.models import GenerateStudyRequest, PlotResearch
from app.plots.models import PlotDetails


class DictCache:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, expire=None):
        self.store[key] = json.loads(json.dumps(value))
        self.expire = expire


def _research() -> PlotResearch:
    """The same valid study fixture as tests/test_feasibility_service.py."""
    return PlotResearch.model_validate(
        {
            "plot_number": "L001",
            "usage": "residential",
            "market_area": "Downtown Dubai",
            "headline": "Initial HBU",
            "summary": ["Summary"],
            "constraints": ["Constraint"],
            "pricing_evidence": [],
            "competition_evidence": [],
            "land_sales_evidence": [],
            "market_pricing": [],
            "off_plan_market_pricing": [],
            "off_plan_pricing_confidence": None,
            "off_plan_unit_benchmarks": [],
            "assumptions": {
                "usage": "residential",
                "plotAreaSqm": 1000.0,
                "maxGfaSqm": 4000.0,
                "maxCoveragePct": 60.0,
                "maxStoreys": 20,
                "maxFar": 4.0,
                "numberOfTowers": 1,
                "numberOfFloors": 20,
                "buaMultiplier": 1.3,
                "nsaEfficiencyPct": 80.0,
                "landPricePsqm": 30000.0,
                "constructionCostPsqmBua": 4200.0,
                "designSupervisionPct": 6.0,
                "salesAgentFeePct": 5.0,
                "marketingCostPct": 1.0,
                "contingencyPct": 5.0,
                "financeRatePct": 9.0,
                "arrangementFeePct": 1.0,
                "commitmentFeePct": 0.5,
                "debtToCostRatio": 0.55,
                "presaleThresholdPct": 35.0,
                "escrowRetentionPct": 5.0,
                "standardParkingRatio": 1.0,
                "largeUnitThresholdSqm": 150.0,
                "largeUnitParkingRatio": 2.0,
                "demolitionEnabled": False,
                "salesCommencementDate": "2026-06-01",
                "salesPeriodMonths": 18,
                "demolitionEnablingDate": "2026-04-01",
                "constructionDate": "2026-07-01",
                "handoverDate": "2029-01-01",
                "landAcquisitionCostOverrideAed": None,
                "designSupervisionCostOverrideAed": None,
                "constructionCostOverrideAed": None,
                "demolitionCostAed": 0.0,
                "infrastructureCostAed": 8000000.0,
                "governmentFeesAed": 5000000.0,
                "marketingCostOverrideAed": None,
                "salesAgentFeesOverrideAed": None,
                "masterCommunityFeesAed": 3500000.0,
                "ffeOsePreopeningCostAed": 0.0,
                "contingencyCostOverrideAed": None,
                "midPointInflationPct": 4.0,
                "vatPct": 5.0,
                "debtFundingAed": 0.0,
                "equityFundingAed": 0.0,
                "brokerageFeeAed": 0.0,
                "legalDdCostAed": 0.0,
                "landAcquisitionDate": "2026-03-17",
                "landLoanLtvPct": 65.0,
                "eiborRatePct": 4.85,
                "landLoanSpreadBps": 365.0,
                "constructionLoanSpreadBps": 465.0,
                "preHandoverMilestoneDate": "2028-07-01",
                "debtRepaymentMode": "bullet_at_handover",
                "unitConfigs": [],
                "paymentPlan": {
                    "depositPct": 20.0,
                    "constructionPct": 40.0,
                    "handoverPct": 40.0,
                },
            },
            "warnings": [],
            "land_cost_estimate_aed_low": None,
            "land_cost_estimate_aed_mid": None,
            "land_cost_estimate_aed_high": None,
        }
    )


@pytest.fixture
def admitted(monkeypatch):
    runs = []

    @asynccontextmanager
    async def admitted_run(**kwargs):
        usage = SimpleNamespace(total_tokens=0)
        runs.append(kwargs)
        yield usage, kwargs["token_limit"]

    monkeypatch.setattr(chat_operations, "admitted_run", admitted_run)
    return runs


@pytest.fixture
def cache(monkeypatch):
    fake = DictCache()
    monkeypatch.setattr(generation, "redis_cache", fake)
    return fake


async def test_repeat_hbu_for_the_same_plot_is_served_from_cache_without_quota(
    monkeypatch, admitted, cache
):
    study = AsyncMock(return_value=_research())
    monkeypatch.setattr(generation, "generate_hbu_study", study)
    first = await generation.generate_hbu_for_plot("P1", user_id="u", organization_id="o")
    second = await generation.generate_hbu_for_plot("P1", user_id="u2", organization_id="o")
    assert first == second
    assert study.await_count == 1
    assert len(admitted) == 1  # the cached repeat reserves and spends nothing
    assert admitted[0] == {
        "user_id": "u",
        "organization_id": "o",
        "token_limit": generation.settings.FEASIBILITY_RUN_TOKEN_LIMIT,
    }
    kwargs = study.await_args.kwargs
    assert kwargs["token_budget"] == generation.settings.FEASIBILITY_RUN_TOKEN_LIMIT
    assert kwargs["run_usage"] is not None
    assert cache.expire == generation.settings.FEASIBILITY_HBU_CACHE_SECONDS


async def test_different_usage_or_model_is_a_different_cached_study(monkeypatch, admitted, cache):
    study = AsyncMock(return_value=_research())
    monkeypatch.setattr(generation, "generate_hbu_study", study)
    await generation.generate_hbu_for_plot("P1", user_id="u", organization_id="o")
    await generation.generate_hbu_for_plot("P1", "commercial", user_id="u", organization_id="o")
    await generation.generate_hbu_for_plot(
        "P1", development_model="build_to_rent_residential", user_id="u", organization_id="o"
    )
    assert study.await_count == 3


async def test_admission_refusal_stops_hbu_before_any_model_work(monkeypatch, cache):
    study = AsyncMock(side_effect=AssertionError("must not run without admission"))
    monkeypatch.setattr(generation, "generate_hbu_study", study)

    @asynccontextmanager
    async def refuse(**kwargs):
        raise admission.AdmissionRefused("allowance")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_operations, "admitted_run", refuse)
    with pytest.raises(HTTPException) as refused:
        await generation.generate_hbu_for_plot("P1", user_id="u", organization_id="o")
    assert refused.value.status_code == 429


async def test_generate_study_failure_does_not_leak_internal_errors(monkeypatch, admitted, cache):
    monkeypatch.setattr(
        generation,
        "generate_hbu_study",
        AsyncMock(side_effect=RuntimeError("clickhouse password=hunter2 at 10.0.0.5")),
    )
    with pytest.raises(HTTPException) as failed:
        await generation.generate_seeded_study(
            GenerateStudyRequest(plot_number="P1"), user_id="u", organization_id="o"
        )
    assert failed.value.status_code == 500
    assert "hunter2" not in str(failed.value.detail)


async def test_seed_draft_runs_inside_the_admitted_token_budget(monkeypatch):
    calls = []

    async def run(prompt, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output="draft")

    monkeypatch.setattr(hbu_agent, "hbu_seed_agent_bts_prefetched", SimpleNamespace(run=run))
    usage = object()
    deps = SimpleNamespace(development_model="build_to_sell_residential")
    await hbu_agent.run_seed_draft("p", deps, usage=usage, token_budget=50_000)
    assert calls[0]["usage"] is usage
    assert calls[0]["usage_limits"].total_tokens_limit == 50_000
    assert calls[0]["usage_limits"].request_limit == 15


# --- Feasibility chat ----------------------------------------------------------------


def _plot():
    return PlotDetails(
        plot_number="fixture-plot",
        community_name="Fixture Area",
        project_name="Fixture Project",
        plot_area_sqm=1000,
        max_gfa_sqm=4000,
        max_gfa_sqft=43055,
        max_height="G+20",
        max_coverage="60%",
        gfa_type="Residential",
        inferred_usage="residential",
        is_verified=True,
    )


def _request(history_json=None):
    return SimpleNamespace(
        messages=[{"role": "user", "content": "Raise studio prices"}],
        plot_data=_plot(),
        assumptions={"unitConfigs": []},
        research=None,
        history_json=history_json,
    )


async def test_feasibility_chat_turn_is_admitted_and_capped(monkeypatch, admitted):
    calls = []

    @asynccontextmanager
    async def iterate(message, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("provider said: secret upstream detail")
        yield  # pragma: no cover

    monkeypatch.setattr(chat, "workspace_chat_agent", SimpleNamespace(iter=iterate))
    events = [
        json.loads(item.removeprefix("data: ").strip())
        async for item in chat.stream_chat_events(_request(), user_id="u", organization_id="o")
    ]
    assert admitted[0]["user_id"] == "u"
    assert calls[0]["usage_limits"].total_tokens_limit == admitted[0]["token_limit"]
    assert calls[0]["usage"] is not None
    assert events[-1]["type"] == "error"
    assert "secret upstream detail" not in json.dumps(events)


async def test_feasibility_chat_refusal_is_reported_without_model_work(monkeypatch):
    @asynccontextmanager
    async def refuse(**kwargs):
        raise admission.AdmissionRefused("busy")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_operations, "admitted_run", refuse)
    iterate = AsyncMock(side_effect=AssertionError("no model work"))
    monkeypatch.setattr(chat, "workspace_chat_agent", SimpleNamespace(iter=iterate))
    events = [
        json.loads(item.removeprefix("data: ").strip())
        async for item in chat.stream_chat_events(_request(), user_id="u", organization_id="o")
    ]
    assert events == [{"type": "error", "error": admission.BUSY}]


def test_client_supplied_history_is_bounded_by_tokens_and_starts_at_a_user_turn(monkeypatch):
    monkeypatch.setattr(budget.settings, "ASSISTANT_HISTORY_TOKEN_LIMIT", 1_000)
    messages = []
    for index in range(20):
        messages.append(ModelRequest(parts=[UserPromptPart(f"q{index} " + "x" * 600)]))
        messages.append(ModelResponse(parts=[ToolCallPart("show_analytics", {}, f"c{index}")]))
        messages.append(ModelRequest(parts=[ToolReturnPart("show_analytics", "ok", f"c{index}")]))
        messages.append(ModelResponse(parts=[TextPart(f"a{index}")]))
    history = ModelMessagesTypeAdapter.validate_json(ModelMessagesTypeAdapter.dump_json(messages))
    bounded = budget.bound_history(history)
    assert budget.estimate_messages(bounded) <= 1_000
    assert isinstance(bounded[0].parts[0], UserPromptPart)
    assert bounded[-1].parts[0].content == "a19"
