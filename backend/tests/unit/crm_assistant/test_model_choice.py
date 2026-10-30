"""The assistant can run on OpenAI directly with its own key; without one it stays on OpenRouter,
so market chat's configuration is never involved."""

from types import SimpleNamespace

from pydantic_ai.models.openai import OpenAIChatModel

from app.core.openrouter import CompatibleOpenRouterModel
from app.crm.assistant.agent import assistant_model_settings, create_assistant_model


def _settings(**overrides):
    values = dict(
        OPENROUTER_API_KEY="or-key",
        DEFAULT_CHAT_MODEL="google/gemini-3.1-flash-lite",
        ASSISTANT_OPENAI_API_KEY=None,
        ASSISTANT_MODEL=None,
    )
    return SimpleNamespace(**{**values, **overrides})


def test_openai_key_runs_the_assistant_on_openai():
    model = create_assistant_model(_settings(ASSISTANT_OPENAI_API_KEY="sk-test"))
    assert isinstance(model, OpenAIChatModel)
    assert not isinstance(model, CompatibleOpenRouterModel)
    assert model.model_name == "gpt-4o-mini"


def test_assistant_model_name_can_be_chosen():
    model = create_assistant_model(
        _settings(ASSISTANT_OPENAI_API_KEY="sk-test", ASSISTANT_MODEL="gpt-4.1-mini")
    )
    assert model.model_name == "gpt-4.1-mini"


def test_without_an_openai_key_the_assistant_stays_on_openrouter():
    model = create_assistant_model(_settings())
    assert isinstance(model, CompatibleOpenRouterModel)
    assert model.model_name == "google/gemini-3.1-flash-lite"


def test_openrouter_only_settings_are_not_sent_to_openai():
    assert assistant_model_settings(_settings(ASSISTANT_OPENAI_API_KEY="sk-test")) is None
    assert assistant_model_settings(_settings()) == {"openrouter_reasoning": {"effort": "low"}}
