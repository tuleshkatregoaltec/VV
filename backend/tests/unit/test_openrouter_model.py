from typing import get_args
from unittest.mock import AsyncMock

import pytest
from openai.types.chat import ChatCompletion
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.providers.openrouter import OpenRouterProvider

from app.config import Settings, settings
from app.core.openrouter import (
    AssistantModelDisabled,
    AssistantRole,
    CompatibleOpenRouterModel,
    create_assistant_model,
    create_openrouter_model,
)


def test_openrouter_model_accepts_standard_response_service_tier() -> None:
    model = CompatibleOpenRouterModel(
        "google/gemini-3-flash-preview",
        provider=OpenRouterProvider(api_key="test-key"),
    )
    response = ChatCompletion.model_construct(
        id="chatcmpl-test",
        choices=[
            {
                "finish_reason": "stop",
                "index": 0,
                "message": {"content": "ok", "role": "assistant"},
                "native_finish_reason": "stop",
            }
        ],
        created=1,
        model="google/gemini-3-flash-preview",
        object="chat.completion",
        provider="google-ai-studio",
        service_tier="standard",
    )

    validated = model._validate_completion(response)

    assert validated.choices[0].message.content == "ok"
    assert validated.provider == "google-ai-studio"
    assert validated.service_tier is None


@pytest.mark.parametrize("role", get_args(AssistantRole))
@pytest.mark.parametrize(
    "prohibited", ["google/gemini-3-flash-preview", "qwen/qwen3.8-max", "qwen/Qwen-3_8-Max:free"]
)
def test_all_assistant_role_settings_reject_prohibited_models(role, prohibited):
    values = settings.model_dump()
    values[f"ASSISTANT_{role.upper()}_MODEL"] = prohibited
    with pytest.raises(ValidationError, match="non-Gemini"):
        Settings.model_validate(values)


@pytest.mark.parametrize("role", get_args(AssistantRole))
def test_assistant_factory_is_role_specific_and_keeps_excluded_features_unchanged(
    monkeypatch, role
):
    monkeypatch.setattr(settings, "DEFAULT_CHAT_MODEL", "google/gemini-3-flash-preview")
    monkeypatch.setattr(settings, f"ASSISTANT_{role.upper()}_MODEL", "openai/gpt-6-luna")
    assert create_assistant_model(role=role).model_name == "openai/gpt-6-luna"
    assert create_openrouter_model().model_name == "google/gemini-3-flash-preview"


@pytest.mark.parametrize("stream", [False, True])
async def test_disabled_assistant_blocks_provider_io_for_all_request_modes(monkeypatch, stream):
    monkeypatch.setattr(settings, "ASSISTANT_ENABLED", False)
    model = create_assistant_model(role="market")
    call = AsyncMock(side_effect=AssertionError("Provider must never be contacted"))
    monkeypatch.setattr(model, "_completions_create", call)
    agent = Agent(model)
    with pytest.raises(AssistantModelDisabled):
        if stream:
            async with agent.run_stream("hello"):
                pass
        else:
            await agent.run("hello")
    call.assert_not_awaited()


def test_assistant_provider_policy_cannot_enable_retention_or_fallback(monkeypatch):
    monkeypatch.setattr(settings, "ASSISTANT_ENABLED", True)
    model = create_assistant_model(role="market")
    configured, _ = model.prepare_request(
        {
            "openrouter_provider": {
                "zdr": False,
                "data_collection": "allow",
                "allow_fallbacks": True,
            }
        },
        ModelRequestParameters(),
    )
    assert configured["extra_body"]["provider"] == {
        "zdr": True,
        "data_collection": "deny",
        "allow_fallbacks": False,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"openrouter_models": ["google/gemini-3-flash-preview"]},
        {"openrouter_preset": "hidden-model"},
        {"extra_body": {"model": "qwen/qwen3.8-max"}},
    ],
)
def test_assistant_cannot_hide_a_prohibited_model_in_fallback_or_preset(monkeypatch, overrides):
    monkeypatch.setattr(settings, "ASSISTANT_ENABLED", True)
    with pytest.raises(ValueError, match="overrides"):
        create_assistant_model(role="market").prepare_request(overrides, ModelRequestParameters())
