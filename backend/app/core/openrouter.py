from typing import Any, Literal, get_args

from openai.types import chat
from pydantic_ai.models.openai import OpenAIStreamedResponse
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

_OPENAI_SERVICE_TIERS = {"auto", "default", "flex", "scale", "priority", None}

AssistantRole = Literal[
    "router",
    "coordinator",
    "market",
    "pricing",
    "crm",
    "followup",
    "action",
    "whatsapp_classifier",
    "whatsapp_drafter",
]


def _drop_unknown_service_tier(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("service_tier") not in _OPENAI_SERVICE_TIERS:
        data.pop("service_tier", None)
    return data


class CompatibleOpenRouterModel(OpenRouterModel):
    """OpenRouter model with response compatibility for OpenAI SDK enums.

    OpenRouter may return provider-specific metadata values that are not yet part
    of OpenAI's response schema. Pydantic AI revalidates non-streamed responses,
    so strip the incompatible field before delegating to its OpenRouter handling.
    """

    def _validate_completion(self, response: chat.ChatCompletion):
        data = _drop_unknown_service_tier(response.model_dump())
        return super()._validate_completion(chat.ChatCompletion.model_construct(**data))

    @property
    def _streamed_response_cls(self):
        # Pydantic AI's OpenAI streamed response path does not revalidate chunks,
        # which keeps OpenRouter's provider-specific response fields forward-compatible.
        return OpenAIStreamedResponse


def create_openrouter_model() -> CompatibleOpenRouterModel:
    from app.config import settings

    return CompatibleOpenRouterModel(
        model_name=settings.DEFAULT_CHAT_MODEL,
        provider=OpenRouterProvider(api_key=settings.OPENROUTER_API_KEY),
    )


class AssistantModelDisabled(RuntimeError):
    pass


class AssistantOpenRouterModel(CompatibleOpenRouterModel):
    """Gate both streamed and ordinary provider requests until qualification."""

    def prepare_request(self, model_settings, model_request_parameters):
        from app.config import settings, validate_assistant_model_id

        if not settings.ASSISTANT_ENABLED:
            raise AssistantModelDisabled("Assistant model rollout is disabled")
        validate_assistant_model_id(self.model_name)
        prepared, parameters = super().prepare_request(model_settings, model_request_parameters)
        prepared = dict(prepared or {})
        body = dict(prepared.get("extra_body") or {})
        if any(key in body for key in ("model", "models", "preset", "route")):
            raise ValueError("Assistant model routing and fallback overrides are not allowed")
        body["provider"] = {
            **body.get("provider", {}),
            "zdr": True,
            "data_collection": "deny",
            "allow_fallbacks": False,
        }
        prepared["extra_body"] = body
        return prepared, parameters


def create_assistant_model(*, role: AssistantRole) -> AssistantOpenRouterModel:
    from app.config import settings, validate_assistant_model_id

    if role not in get_args(AssistantRole):
        raise ValueError("Unknown assistant model role")
    model_name = validate_assistant_model_id(getattr(settings, f"ASSISTANT_{role.upper()}_MODEL"))
    return AssistantOpenRouterModel(
        model_name=model_name,
        provider=OpenRouterProvider(api_key=settings.OPENROUTER_API_KEY),
    )
