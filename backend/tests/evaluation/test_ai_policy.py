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
    assert settlement[-7:-4] == (40, 30, "settled")
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
    assert settlement[-7:-4] == (reservation.reserved_cost, reservation.reserved_tokens, "unknown")
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


def test_unpriced_multimodal_or_builtin_calls_cannot_evade_text_budget():
    from pydantic_ai import ImageUrl
    from pydantic_ai.builtin_tools import WebSearchTool
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.models import ModelRequestParameters

    with pytest.raises(policy.AIPolicyError, match="multimodal"):
        CompatibleOpenRouterModel._validate_text_request(
            [ModelRequest(parts=[UserPromptPart([ImageUrl("https://example.test/large.png")])])],
            ModelRequestParameters(),
        )
    with pytest.raises(policy.AIPolicyError, match="built-in"):
        CompatibleOpenRouterModel._validate_text_request(
            [], ModelRequestParameters(builtin_tools=[WebSearchTool()])
        )


async def test_real_sdk_prepared_reasoning_settings_reach_http_with_privacy(configured):
    """Agent preparation used to turn valid reasoning into a rejected extra_body."""
    import json

    from openai import AsyncOpenAI
    from opentelemetry.sdk.trace import TracerProvider
    from pydantic_ai import Agent
    from pydantic_ai.models.instrumented import InstrumentationSettings
    from pydantic_ai.models.openrouter import OpenRouterModelSettings
    from pydantic_ai.providers.openrouter import OpenRouterProvider

    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("stream"):
            chunks = [
                {
                    "id": "test",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": policy.settings.DEFAULT_CHAT_MODEL,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": "Grounded answer"},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "test",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": policy.settings.DEFAULT_CHAT_MODEL,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                },
            ]
            content = (
                "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
                + "data: [DONE]\n\n"
            )
            return httpx.Response(200, text=content, headers={"content-type": "text/event-stream"})
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "provider": "Google",
                "created": 1,
                "model": policy.settings.DEFAULT_CHAT_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Grounded answer"},
                        "finish_reason": "stop",
                        "native_finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    configured.eval.side_effect = ["ok", 1, "ok", 1]
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        model = CompatibleOpenRouterModel(
            policy.settings.DEFAULT_CHAT_MODEL,
            provider=OpenRouterProvider(
                openai_client=AsyncOpenAI(
                    api_key="mock-only",
                    base_url="https://openrouter.ai/api/v1",
                    max_retries=0,
                    http_client=http,
                )
            ),
        )
        agent = Agent(
            model,
            instrument=InstrumentationSettings(
                tracer_provider=TracerProvider(), include_content=False
            ),
            model_settings=OpenRouterModelSettings(
                openrouter_reasoning={"effort": "low"}, max_tokens=4096
            ),
        )
        async with scope():
            assert (await agent.run("Use supplied evidence")).output == "Grounded answer"
            async with agent.run_stream("Use supplied evidence") as result:
                assert await result.get_output() == "Grounded answer"
    assert len(requests) == 2
    for body in requests:
        assert body["reasoning"] == {"effort": "low"}
        assert body["provider"] == policy.provider_privacy()
        assert body["max_completion_tokens"] == 4096
    assert configured.eval.await_count == 4


def test_sdk_normalization_still_rejects_unapproved_or_conflicting_extra_body():
    for extra in ({"model": "other"}, {"plugins": [{"id": "web"}]}, {"provider": {"zdr": False}}):
        with pytest.raises(policy.AIPolicyError, match="override"):
            policy.safe_model_settings({"extra_body": extra})
    with pytest.raises(policy.AIPolicyError, match="Conflicting"):
        policy.safe_model_settings(
            {
                "extra_body": {"reasoning": {"effort": "high"}},
                "openrouter_reasoning": {"effort": "low"},
            }
        )
