"""Token budgets for one assistant turn: limits, history bound and in-turn compaction.

Each provider request resends the system prompt, tool schemas, replayed history and every
tool output so far, so a turn's cost grows with every request. History is bounded by
estimated tokens and, once a request would exceed the context budget, the oldest tool
outputs are replaced by a short marker (the newest outputs are always kept whole).
"""

import json
from dataclasses import replace
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart, UserPromptPart
from pydantic_ai.usage import UsageLimits

from app.config import settings

# Conservative for JSON-heavy tool output (English prose is closer to 4 chars/token),
# so the bounds trim slightly early rather than late.
CHARS_PER_TOKEN = 3
COMPACTED_TOOL_OUTPUT = (
    "[Earlier tool output omitted to keep this turn within its context budget. "
    "Call the tool again if this evidence is still needed.]"
)


def turn_limits(token_budget: int) -> UsageLimits:
    """Cumulative limits for every request in one turn, including nested workflows."""
    return UsageLimits(
        request_limit=settings.ASSISTANT_TURN_REQUEST_LIMIT,
        tool_calls_limit=settings.ASSISTANT_TURN_TOOL_CALLS_LIMIT,
        total_tokens_limit=token_budget,
    )


def estimate_tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return -(-len(text) // CHARS_PER_TOKEN)


def _part_tokens(part: Any) -> int:
    for attribute in ("content", "args"):
        value = getattr(part, attribute, None)
        if value is not None:
            return estimate_tokens(value)
    return 0


def estimate_messages(messages: list[ModelMessage]) -> int:
    return sum(_part_tokens(part) for message in messages for part in message.parts)


def compact_tool_outputs(messages: list[ModelMessage]) -> list[ModelMessage]:
    """History processor: trim the oldest tool outputs once the context is over budget.

    Tool call/return pairs stay intact (only content is replaced) and the latest
    request's outputs are never trimmed, so the model always sees its newest evidence.
    """
    limit = settings.ASSISTANT_REQUEST_CONTEXT_TOKEN_LIMIT
    total = estimate_messages(messages)
    if total <= limit:
        return messages
    result = list(messages)
    for index, message in enumerate(result[:-1]):
        if total <= limit:
            break
        if not isinstance(message, ModelRequest):
            continue
        parts = list(message.parts)
        for position, part in enumerate(parts):
            if total <= limit:
                break
            if not isinstance(part, ToolReturnPart) or part.content == COMPACTED_TOOL_OUTPUT:
                continue
            saved = _part_tokens(part) - estimate_tokens(COMPACTED_TOOL_OUTPUT)
            if saved <= 0:
                continue
            parts[position] = replace(part, content=COMPACTED_TOOL_OUTPUT)
            total -= saved
        result[index] = replace(message, parts=parts)
    return result


def bound_history(messages: list[ModelMessage], limit: int | None = None) -> list[ModelMessage]:
    """Keep the newest messages within the token budget, starting at a user turn.

    Starting at a user prompt keeps every tool return paired with its tool call.
    """
    limit = settings.ASSISTANT_HISTORY_TOKEN_LIMIT if limit is None else limit
    kept: list[ModelMessage] = []
    remaining = limit
    for message in reversed(messages):
        cost = estimate_messages([message])
        if cost > remaining:
            break
        remaining -= cost
        kept.append(message)
    kept.reverse()
    while kept and not (
        isinstance(kept[0], ModelRequest)
        and any(isinstance(part, UserPromptPart) for part in kept[0].parts)
        and not any(isinstance(part, ToolReturnPart) for part in kept[0].parts)
    ):
        kept.pop(0)
    return kept
