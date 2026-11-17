"""Instrumentation must not turn SDK preparation into an unapproved body override."""

import copy
import json

import httpx
import pytest
from openai import AsyncOpenAI
from opentelemetry.sdk.trace import TracerProvider
from pydantic_ai import Agent
from pydantic_ai.models.instrumented import InstrumentationSettings
from pydantic_ai.providers.openrouter import OpenRouterProvider

from app.chat.workflows import SETTINGS
from app.core.openrouter import CompatibleOpenRouterModel
from scripts.evaluation.http_trial import CURRENT_CASE, HTTPBudgetedModel
from scripts.evaluation.trial_budget import BudgetedModel, TrialLedger

MODEL = "openai/gpt-6-luna"
ENTRY = {
    "id": MODEL,
    "context_length": 100000,
    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
}


def wrap_model(kind, raw, ledger, directory):
    if kind == "http":
        return HTTPBudgetedModel(
            raw,
            plan={"catalog_entry": ENTRY, "run_id": "instrumented-test"},
            directory=directory,
            ledger=ledger,
        )
    return BudgetedModel(
        raw,
        ledger=ledger,
        entry=ENTRY,
        stage="flows",
        run_id="instrumented-test",
        case_id="q01",
    )


@pytest.mark.parametrize("kind", ["http", "direct"])
@pytest.mark.parametrize("settings_location", ["caller", "wrapped_defaults"])
async def test_instrumented_sdk_preserves_settings_and_settles_one_guarded_request(
    tmp_path, kind, settings_location
):
    ledger = TrialLedger(tmp_path / "ledger.sqlite3")
    wire = []

    def respond(request):
        # The provider cannot receive a request before its durable reserve exists.
        assert ledger.snapshot()["requests"][-1]["state"] == "pending"
        wire.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "offline-completion",
                "object": "chat.completion",
                "created": 0,
                "model": MODEL,
                "provider": "MockTransport",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Grounded response"},
                        "finish_reason": "stop",
                        "native_finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "cost": 0.001,
                },
            },
        )

    caller = copy.deepcopy(SETTINGS) if settings_location == "caller" else None
    defaults = copy.deepcopy(SETTINGS) if settings_location == "wrapped_defaults" else None
    original_caller, original_defaults = copy.deepcopy(caller), copy.deepcopy(defaults)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        async with AsyncOpenAI(
            api_key="offline",
            base_url="https://mock.invalid/v1",
            http_client=http,
            max_retries=0,
        ) as sdk:
            raw = CompatibleOpenRouterModel(
                MODEL,
                provider=OpenRouterProvider(openai_client=sdk),
                settings=defaults,
            )
            model = wrap_model(kind, raw, ledger, tmp_path)
            token = CURRENT_CASE.set("q01")
            try:
                result = await Agent(
                    model,
                    model_settings=caller,
                    instrument=InstrumentationSettings(
                        tracer_provider=TracerProvider(), include_content=False
                    ),
                ).run("Synthetic property question")
            finally:
                CURRENT_CASE.reset(token)

    assert result.output == "Grounded response"
    assert caller == original_caller
    assert defaults == original_defaults
    assert len(wire) == 1
    assert wire[0]["model"] == MODEL
    assert wire[0].get("max_tokens", wire[0].get("max_completion_tokens")) == 3000
    assert "models" not in wire[0] and "preset" not in wire[0]
    assert wire[0]["provider"] == {
        "zdr": True,
        "data_collection": "deny",
        "allow_fallbacks": False,
        "require_parameters": True,
        "max_price": {"prompt": 1.0, "completion": 2.0, "request": 0.0},
    }
    snapshot = ledger.snapshot()
    assert len(snapshot["requests"]) == 1
    assert snapshot["requests"][0]["state"] == "settled"
    assert snapshot["accounted_usd"] == 0.001


@pytest.mark.parametrize("kind", ["http", "direct"])
@pytest.mark.parametrize("settings_location", ["caller", "wrapped_defaults"])
@pytest.mark.parametrize(
    "override",
    [
        {"openrouter_models": ["google/gemini-unapproved"]},
        {"openrouter_preset": "unapproved"},
        {"extra_body": {"models": ["qwen/qwen3.8-max"]}},
    ],
)
async def test_instrumented_sdk_still_rejects_routing_before_reserve_or_transport(
    tmp_path, kind, settings_location, override
):
    ledger = TrialLedger(tmp_path / "ledger.sqlite3")
    wire = []

    def forbidden(request):
        wire.append(request)
        raise AssertionError("An unapproved route must never reach the provider transport")

    supplied = {**copy.deepcopy(SETTINGS), **copy.deepcopy(override)}
    caller = supplied if settings_location == "caller" else None
    defaults = supplied if settings_location == "wrapped_defaults" else None
    original = copy.deepcopy(supplied)
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        async with AsyncOpenAI(
            api_key="offline",
            base_url="https://mock.invalid/v1",
            http_client=http,
            max_retries=0,
        ) as sdk:
            raw = CompatibleOpenRouterModel(
                MODEL,
                provider=OpenRouterProvider(openai_client=sdk),
                settings=defaults,
            )
            model = wrap_model(kind, raw, ledger, tmp_path)
            token = CURRENT_CASE.set("q01")
            try:
                with pytest.raises(ValueError, match="overrides"):
                    await Agent(
                        model,
                        model_settings=caller,
                        instrument=InstrumentationSettings(
                            tracer_provider=TracerProvider(), include_content=False
                        ),
                    ).run("Synthetic property question")
            finally:
                CURRENT_CASE.reset(token)

    assert supplied == original
    assert wire == []
    assert ledger.snapshot()["requests"] == []
