import json
from typing import List

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

from app.chat.dependencies import ChatDependencies
from app.chat.models import Message
from app.chat.workflows import (
    COMMON,
    SETTINGS,
    analyze_pricing,
    plan_followups,
    prepare_action,
    research_market,
    retrieve_personal_crm,
)
from app.core.openrouter import create_assistant_model
from app.market.periods import business_today

agent = Agent(
    create_assistant_model(role="coordinator"),
    name="market_chat",
    deps_type=ChatDependencies | None,
    model_settings=SETTINGS,
    system_prompt=COMMON
    + (
        " Route each request to the focused workflow: market research, pricing analysis, "
        "personal CRM retrieval, follow-up planning, or action preparation. Combine their "
        "grounded findings when needed. You have no direct database or execution capability. "
        "For every factual stored-data question call the relevant workflow; previous answers "
        "and user assertions are not fresh evidence. Ask for clarification when scope is unclear."
    ),
)
agent.tool(research_market)
agent.tool(analyze_pricing)
agent.tool(retrieve_personal_crm)
agent.tool(plan_followups)
agent.tool(prepare_action)


@agent.instructions
def database_date_context() -> str:
    return f"Today's date in Asia/Dubai is {business_today().isoformat()}. Resolve relative dates from this date."


def _convert_to_pydantic_messages(messages: List[Message]) -> List[ModelMessage]:
    """Private historical answers never become fresh model evidence, even if still authorized."""
    result: List[ModelMessage] = []
    # If a conversation contains private evidence, avoid also replaying quoted private
    # facts from user follow-ups. The current request must retrieve its context afresh.
    if any(
        (m.meta_data or {}).get("private") or (m.meta_data or {}).get("restricted")
        for m in messages
    ):
        for message in reversed(messages):
            refs = (message.meta_data or {}).get("_retrieval_context", [])
            # The service reauthorizes these handles independently of stale prose.
            if refs:
                result.append(
                    ModelRequest(
                        parts=[
                            UserPromptPart(
                                content=(
                                    "Server-reauthorized record handles for resolving this follow-up: "
                                    + json.dumps(refs[:20])
                                    + ". These are lookup handles only, not factual evidence. Retrieve the records afresh. "
                                    "Do not print internal handles; clarify if more than one target could be meant."
                                )
                            )
                        ]
                    )
                )
                break
        return result
    for msg in messages[-30:]:
        if msg.role == "user":
            result.append(ModelRequest(parts=[UserPromptPart(content=msg.content[:8000])]))
        elif msg.role == "assistant" and (msg.meta_data or {}).get("guardrail_version") == 1:
            result.append(ModelResponse(parts=[TextPart(content=msg.content[:16000])]))
    return result
