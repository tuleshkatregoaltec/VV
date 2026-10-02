import logging
from typing import List

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

from app.chat.artifacts import _artifact_history_context
from app.chat.models import Message
from app.chat.prompts import CHAT_SYSTEM_PROMPT
from app.config import settings
from app.core.openrouter import create_openrouter_model

logger = logging.getLogger(__name__)

model = create_openrouter_model()

# Toolsets are bound per authenticated turn by the service, never shared across tenants.
agent = Agent(
    model,
    name="market_chat",
    system_prompt=CHAT_SYSTEM_PROMPT
    + (
        "\nConfigured product policy:\n" + settings.AI_TOPIC_POLICY
        if settings.AI_TOPIC_POLICY
        else ""
    ),
)


def _convert_to_pydantic_messages(messages: List[Message]) -> List[ModelMessage]:
    """Convert database messages to Pydantic AI message format"""
    pydantic_messages: List[ModelMessage] = []

    for msg in messages:
        if msg.role == "user":
            pydantic_messages.append(ModelRequest(parts=[UserPromptPart(content=msg.content)]))
        elif msg.role == "assistant":
            artifact_context = _artifact_history_context(msg.meta_data)
            content = msg.content
            if artifact_context:
                content = (
                    f"{content}\n\n"
                    "[Rendered card context for follow-up references]\n"
                    f"{artifact_context}"
                )
            pydantic_messages.append(ModelResponse(parts=[TextPart(content=content)]))

    return pydantic_messages
