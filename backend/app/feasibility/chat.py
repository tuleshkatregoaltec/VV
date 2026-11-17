import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import replace
from typing import Any

from fastapi import HTTPException
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    SystemPromptPart,
    ToolCallPart,
)
from pydantic_ai.usage import RunUsage, UsageLimits

from app.chat import operations as chat_operations
from app.config import settings
from app.feasibility.chat_agent import (
    FeasibilityChatDeps,
    WorkspaceUnitMixReplacement,
    WorkspaceUnitMixUpdate,
    workspace_chat_agent,
)
from app.feasibility.chat_units import price_per_sqm, to_workbook_units
from app.feasibility.models import (
    FeasibilityChatRequest,
    FeasibilityPaymentPlan,
)
from app.feasibility.research import fetch_chat_research
from app.plots.models import PlotDetails

logger = logging.getLogger(__name__)


ERROR_EVENT = f"data: {json.dumps({'type': 'error', 'error': 'Internal server error'})}\n\n"


async def stream_chat_events(
    request: FeasibilityChatRequest, *, user_id: str, organization_id: str
) -> AsyncGenerator[str, None]:
    """One admitted turn: shares the assistant's per-user concurrency and daily allowance."""
    try:
        async with chat_operations.admitted_run(
            user_id=user_id,
            organization_id=organization_id,
            token_limit=settings.ASSISTANT_TURN_TOKEN_LIMIT,
        ) as (usage, token_budget):
            async for chunk in stream_feasibility_response(
                request.messages,
                request.plot_data,
                request.assumptions,
                request.research,
                request.history_json,
                usage=usage,
                token_budget=token_budget,
            ):
                yield chunk
    except HTTPException as exc:
        yield f"data: {json.dumps({'type': 'error', 'error': exc.detail})}\n\n"
    except Exception:
        logger.exception("Error in feasibility chat stream service")
        yield ERROR_EVENT


_RESEARCH_TOOLS = {"show_transactions": "transactions", "show_analytics": "analytics"}

_MUTATION_TOOLS = {
    "update_prices": "set_price_per_sqm",
    "update_unit_mix": "update_unit_mix",
    "replace_unit_mix": "replace_unit_mix",
    "update_assumptions": "set_assumptions",
    "update_payment_plan": "set_payment_plan",
}


def _without_system_parts(message: ModelMessage) -> ModelMessage:
    if not isinstance(message, ModelRequest):
        return message
    return replace(
        message, parts=[part for part in message.parts if not isinstance(part, SystemPromptPart)]
    )


def _unit_mix_row(row: WorkspaceUnitMixUpdate | WorkspaceUnitMixReplacement) -> dict[str, Any]:
    """The chat proposes sq ft and AED per sq ft; the workbook takes m² and AED per m²."""
    return to_workbook_units(row.model_dump(exclude_none=True))


def _extract_payload(part: ToolCallPart) -> Any:
    args = part.args_as_dict()
    if part.tool_name == "update_prices":
        prices = args.get("prices", args)
        return {unit: price_per_sqm(value) for unit, value in prices.items()}
    if part.tool_name == "update_unit_mix":
        raw = args.get("unit_mix", args)
        return [_unit_mix_row(WorkspaceUnitMixUpdate(**row)) for row in raw]
    if part.tool_name == "replace_unit_mix":
        raw = args.get("unit_mix", args)
        return [_unit_mix_row(WorkspaceUnitMixReplacement(**row)) for row in raw]
    if part.tool_name == "update_assumptions":
        return to_workbook_units(args.get("assumptions", args))
    if part.tool_name == "update_payment_plan":
        raw = args.get("payment_plan", args)
        return FeasibilityPaymentPlan(**raw).model_dump()
    return None


def _unit_type_keys_from_assumptions(assumptions: dict[str, Any]) -> list[str]:
    unit_configs = assumptions.get("unitConfigs")
    if not isinstance(unit_configs, list):
        return []

    keys: list[str] = []
    for row in unit_configs:
        if not isinstance(row, dict):
            continue
        unit_id = row.get("id")
        if isinstance(unit_id, str):
            keys.append(unit_id)
    return keys


async def stream_feasibility_response(
    messages: list[dict],
    plot_data: PlotDetails,
    assumptions: dict[str, Any],
    research: dict | None = None,
    history_json: str | None = None,
    *,
    usage: RunUsage | None = None,
    token_budget: int | None = None,
) -> AsyncGenerator[str, None]:
    deps = FeasibilityChatDeps(
        plot_number=plot_data.plot_number,
        area_name=plot_data.community_name,
        plot=plot_data.model_dump(mode="json"),
        study=research,
        assumptions=assumptions,
        unit_type_keys=_unit_type_keys_from_assumptions(assumptions),
    )

    history: list[Any] = []
    if history_json:
        try:
            # Client-supplied: drop any system parts (instructions are rebuilt from the
            # live workbook each turn) and keep only the newest turns within budget.
            history = chat_operations.bound_history(
                [
                    _without_system_parts(message)
                    for message in ModelMessagesTypeAdapter.validate_json(history_json)
                ]
            )
        except Exception:
            logger.exception("Failed to deserialize feasibility history_json")
            yield f"data: {json.dumps({'type': 'warning', 'content': 'Session context reset — conversation history could not be restored.'})}\n\n"

    user_turns = [message for message in messages if message.get("role") == "user"]
    user_message = user_turns[-1].get("content", "") if user_turns else ""

    try:
        async with workspace_chat_agent.iter(
            user_message,
            message_history=history,
            deps=deps,
            usage=usage,
            usage_limits=UsageLimits(request_limit=10, total_tokens_limit=token_budget),
        ) as run:
            async for node in run:
                if Agent.is_model_request_node(node):
                    async with node.stream(run.ctx) as stream:
                        async for chunk in stream.stream_text(delta=True, debounce_by=0.01):
                            yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
                elif Agent.is_call_tools_node(node):
                    for part in node.model_response.parts:
                        if not isinstance(part, ToolCallPart):
                            continue
                        if part.tool_name in _MUTATION_TOOLS:
                            payload = _extract_payload(part)
                            if payload is not None:
                                yield f"data: {json.dumps({'type': 'pending_action', 'action': _MUTATION_TOOLS[part.tool_name], 'payload': payload}, default=str)}\n\n"
                        elif part.tool_name in _RESEARCH_TOOLS:
                            payload = await fetch_chat_research(part.tool_name, part.args_as_dict())
                            if payload is not None:
                                yield f"data: {json.dumps({'type': 'show_research', 'tab': _RESEARCH_TOOLS[part.tool_name], 'data': payload}, default=str)}\n\n"
            new_messages_json = run.new_messages_json().decode()
            yield f"data: {json.dumps({'type': 'done', 'new_messages_json': new_messages_json})}\n\n"
    except Exception as exc:
        logger.error("Feasibility chat failed (%s)", type(exc).__name__)
        yield ERROR_EVENT
