"""Fail-closed provider admission, cancellation and privacy contract."""

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core import ai_policy as policy
from app.core.openrouter import CompatibleOpenRouterModel, create_openrouter_model


@pytest.fixture
def configured(monkeypatch):
    for name in (
        "AI_USER_DAILY_USD",
        "AI_USER_MONTHLY_USD",
        "AI_ORG_DAILY_USD",
        "AI_ORG_MONTHLY_USD",
    ):
        monkeypatch.setattr(policy.settings, name, Decimal("5"))
    monkeypatch.setattr(policy.settings, "AI_PRICING_MODEL", policy.settings.DEFAULT_CHAT_MODEL)
    monkeypatch.setattr(policy.settings, "AI_INPUT_USD_PER_MILLION", Decimal("0.5"))
    monkeypatch.setattr(policy.settings, "AI_OUTPUT_USD_PER_MILLION", Decimal("3"))
    connection = SimpleNamespace(eval=AsyncMock(side_effect=["ok", 1]), aclose=AsyncMock())
    monkeypatch.setattr(policy, "client", lambda: connection)
    return connection


def scope(identifier="execution-one"):
    return policy.ai_execution(
        user_id="user", organization_id="org", execution_id=identifier, daily_token_limit=500000
    )


async def test_unscoped_direct_crm_request_cannot_reach_provider(configured):
    transport = AsyncMock()
    with pytest.raises(policy.AIPolicyError, match="context"):
        await policy.direct_provider_request(
            transport,
            "https://openrouter.ai/api/v1/chat/completions",
            json={"model": policy.settings.DEFAULT_CHAT_MODEL, "max_tokens": 100},
        )
    transport.post.assert_not_called()
    configured.eval.assert_not_called()


async def test_actual_usage_reconciles_once_and_context_is_reset(configured):
    async with scope():
        async with policy.provider_reservation(
            policy.settings.DEFAULT_CHAT_MODEL, "hello", output_tokens=100
        ) as reservation:
            reservation.reconcile(20, 10)
    settlement = configured.eval.call_args.args
    assert settlement[13:16] == (40, 30, "settled")
    assert policy._scope.get() is None
    assert configured.eval.await_count == 2
    configured.aclose.assert_awaited_once()


async def test_cancellation_keeps_unknown_charge_and_cleans_up(configured):
    with pytest.raises(asyncio.CancelledError):
        async with scope():
            async with policy.provider_reservation(
                policy.settings.DEFAULT_CHAT_MODEL, "hello", output_tokens=100
            ) as reservation:
                raise asyncio.CancelledError
    settlement = configured.eval.call_args.args
    assert settlement[13:16] == (reservation.reserved_cost, reservation.reserved_tokens, "unknown")
    assert policy._scope.get() is None
    configured.aclose.assert_awaited_once()


async def test_missing_prices_and_unavailable_ledger_fail_before_provider(configured, monkeypatch):
    monkeypatch.setattr(policy.settings, "AI_INPUT_USD_PER_MILLION", None)
    async with scope():
        with pytest.raises(policy.AIPolicyError, match="pricing"):
            async with policy.provider_reservation(
                policy.settings.DEFAULT_CHAT_MODEL, "hello", output_tokens=100
            ):
                pytest.fail("Provider must not be reached")
    configured.eval.assert_not_called()
    monkeypatch.setattr(policy.settings, "AI_INPUT_USD_PER_MILLION", Decimal("0.5"))
    configured.eval.side_effect = ConnectionError("SECRET")
    async with scope():
        with pytest.raises(policy.AIPolicyError, match="accounting is unavailable"):
            async with policy.provider_reservation(
                policy.settings.DEFAULT_CHAT_MODEL, "hello", output_tokens=100
            ):
                pytest.fail("Provider must not be reached")


async def test_concurrent_scopes_do_not_share_tenant_identity():
    async def observe(identifier):
        async with scope(identifier):
            await asyncio.sleep(0)
            return policy._scope.get().execution_id

    assert await asyncio.gather(observe("one"), observe("two")) == ["one", "two"]
    assert policy._scope.get() is None


async def test_crm_applies_privacy_even_when_caller_supplies_weaker_flags(configured):
    seen = []

    def handler(request):
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"usage": {"prompt_tokens": 20, "completion_tokens": 10}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        async with scope():
            await policy.direct_provider_request(
                client,
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model": policy.settings.DEFAULT_CHAT_MODEL,
                    "max_tokens": 100,
                    "provider": {"zdr": False, "data_collection": "allow"},
                },
            )
    assert seen[0]["provider"] == policy.provider_privacy()
    assert seen[0]["provider"]["allow_fallbacks"] is False


def test_provider_settings_cannot_override_privacy_or_make_implicit_retries():
    assert policy.safe_model_settings({"openrouter_provider": {"zdr": False}})[
        "openrouter_provider"
    ]["zdr"]
    with pytest.raises(policy.AIPolicyError, match="override"):
        policy.safe_model_settings({"extra_body": {"provider": {"zdr": False}}})
    model = create_openrouter_model()
    assert model.client.max_retries == 0


async def test_model_factory_stream_and_nonstream_use_shared_reservations(configured, monkeypatch):
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.models.openrouter import OpenRouterModel
    from pydantic_ai.usage import RequestUsage

    seen = []

    async def request(self, messages, settings, parameters):
        seen.append(settings)
        return SimpleNamespace(usage=RequestUsage(input_tokens=20, output_tokens=10))

    @asynccontextmanager
    async def stream(self, messages, settings, parameters, run_context):
        seen.append(settings)
        yield SimpleNamespace(usage=lambda: RequestUsage(input_tokens=20, output_tokens=10))

    monkeypatch.setattr(OpenRouterModel, "request", request)
    monkeypatch.setattr(OpenRouterModel, "request_stream", stream)
    configured.eval.side_effect = ["ok", 1, "ok", 1]
    model = create_openrouter_model()
    assert isinstance(model, CompatibleOpenRouterModel)
    messages = [ModelRequest(parts=[UserPromptPart("hello")])]
    async with scope():
        await model.request(messages, {}, ModelRequestParameters())
        async with model.request_stream(messages, {}, ModelRequestParameters()):
            pass
    assert len(seen) == 2
    assert all(item["openrouter_provider"]["zdr"] for item in seen)
