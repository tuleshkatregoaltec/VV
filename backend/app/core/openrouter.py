from contextlib import asynccontextmanager
from typing import Any

from openai import AsyncOpenAI
from openai.types import chat
from pydantic_ai.models.openai import OpenAIStreamedResponse
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

_OPENAI_SERVICE_TIERS = {"auto", "default", "flex", "scale", "priority", None}


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

    @staticmethod
    def _validate_text_request(messages, parameters):
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        from app.core.ai_policy import AIPolicyError

        if parameters.builtin_tools:
            raise AIPolicyError("Unpriced built-in provider tools are disabled")
        for message in messages:
            if isinstance(message, ModelRequest):
                for part in message.parts:
                    if isinstance(part, UserPromptPart) and not isinstance(part.content, str):
                        if any(not isinstance(item, str) for item in part.content):
                            raise AIPolicyError("Unpriced multimodal provider input is disabled")

    async def request(self, messages, model_settings, model_request_parameters):
        from app.core.ai_policy import provider_reservation, safe_model_settings

        self._validate_text_request(messages, model_request_parameters)
        policy = safe_model_settings(model_settings)
        async with provider_reservation(
            self.model_name,
            (messages, model_request_parameters),
            output_tokens=policy["max_tokens"],
        ) as reservation:
            result = await super().request(messages, policy, model_request_parameters)
            reservation.reconcile(result.usage.input_tokens, result.usage.output_tokens)
            return result

    @asynccontextmanager
    async def request_stream(
        self, messages, model_settings, model_request_parameters, run_context=None
    ):
        from app.core.ai_policy import provider_reservation, safe_model_settings

        self._validate_text_request(messages, model_request_parameters)
        policy = safe_model_settings(model_settings)
        async with provider_reservation(
            self.model_name,
            (messages, model_request_parameters),
            output_tokens=policy["max_tokens"],
        ) as reservation:
            async with super().request_stream(
                messages, policy, model_request_parameters, run_context
            ) as response:
                yield response
                # Partial streams/cancellation retain the conservative reservation.
                usage = response.usage()
                reservation.reconcile(usage.input_tokens, usage.output_tokens)

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
        provider=OpenRouterProvider(
            openai_client=AsyncOpenAI(
                api_key=settings.OPENROUTER_API_KEY,
                base_url="https://openrouter.ai/api/v1",
                max_retries=0,
            )
        ),
    )
