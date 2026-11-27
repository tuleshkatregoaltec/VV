import json
from typing import List

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

from app.chat.budget import estimate_tokens
from app.chat.models import Message
from app.config import settings
from app.core.openrouter import create_assistant_model
from app.crm.assistant.dependencies import ChatDependencies
from app.crm.assistant.workflows import (
    COMMON,
    HISTORY_PROCESSORS,
    SETTINGS,
    plan_followups,
    prepare_action,
    retrieve_personal_crm,
    signed_in_role,
)
from app.market.periods import business_today

agent = Agent(
    create_assistant_model(role="coordinator"),
    name="crm_assistant",
    deps_type=ChatDependencies | None,
    model_settings=SETTINGS,
    history_processors=HISTORY_PROCESSORS,
    instructions=COMMON
    + (
        " Route each request to the focused CRM workflow: CRM retrieval (leads, teams, "
        "handlers, contacts, notes, calendar, lead emails), follow-up planning, or action "
        "preparation (CRM changes for confirmation). There is no market workflow. Combine their "
        "grounded findings when needed. You have no direct database or execution capability. "
        "For every factual stored-data question call the relevant workflow; previous answers "
        "and user assertions are not fresh evidence. Ask for clarification when scope is unclear."
    ),
)
agent.tool(retrieve_personal_crm)
agent.tool(plan_followups)
agent.tool(prepare_action)
agent.instructions(signed_in_role)


@agent.instructions
def database_date_context() -> str:
    return f"Today's date in Asia/Dubai is {business_today().isoformat()}. Resolve relative dates from this date."


def _open_question(messages: List[Message]) -> List[ModelMessage]:
    """The latest exchange when its answer used no private records, such as a clarifying
    question ("the CRM team or the market area?"), so the reply to it keeps its meaning.

    Answers built from private records are never replayed; this one was not, and the request
    before it is the user's own words. Neither is evidence.
    """
    if len(messages) < 2:
        return []
    request, answer = messages[-2], messages[-1]
    metadata = answer.meta_data or {}
    if (
        request.role != "user"
        or answer.role != "assistant"
        or metadata.get("guardrail_version") != 1
        or metadata.get("private")
        or metadata.get("restricted")
    ):
        return []
    return [
        ModelRequest(parts=[UserPromptPart(content=request.content[:8000])]),
        ModelResponse(parts=[TextPart(content=answer.content[:16000])]),
    ]


def _convert_to_pydantic_messages(
    messages: List[Message], *, include_market: bool = False
) -> List[ModelMessage]:
    """Private historical answers never become fresh model evidence, even if still authorized.

    Legacy conversations can contain answers from both products. Each model gets only answers
    belonging to its assistant; Market AI passes include_market=True.
    """
    if include_market:
        messages = [
            m
            for m in messages
            if m.role != "assistant" or (m.meta_data or {}).get("assistant") == "market"
        ]
    else:
        messages = [
            m
            for m in messages
            if not (m.role == "assistant" and (m.meta_data or {}).get("assistant") == "market")
        ]
    result: List[ModelMessage] = []
    # If a conversation contains private evidence, avoid also replaying quoted private
    # facts from user follow-ups. The current request must retrieve its context afresh.
    if any(
        (m.meta_data or {}).get("private") or (m.meta_data or {}).get("restricted")
        for m in messages
    ):
        context = []
        for message in reversed(messages):
            refs = (message.meta_data or {}).get("_retrieval_context", [])
            # The service reauthorizes these handles independently of stale prose.
            if refs:
                context.append(
                    "Server-reauthorized record handles for resolving this follow-up: "
                    + json.dumps(refs[:20])
                    + ". These are lookup handles only, not factual evidence. Retrieve the records afresh. "
                    "Do not print internal handles; clarify if more than one target could be meant."
                )
                break
        pending = next(
            (
                (m.meta_data or {})["_pending_action"]
                for m in reversed(messages)
                if (m.meta_data or {}).get("_pending_action")
            ),
            None,
        )
        outcomes = next(
            (
                (m.meta_data or {})["_action_outcomes"]
                for m in reversed(messages)
                if (m.meta_data or {}).get("_action_outcomes")
            ),
            None,
        )
        if outcomes:
            # The server's current action status supersedes anything said when it was proposed.
            context.append(
                "Server status of the most recently proposed actions (authoritative, current): "
                + json.dumps(outcomes, sort_keys=True)
                + ". When the user asks about them, report exactly this status. Never say an "
                "action was added, booked, saved, sent or completed, or that nothing happened, "
                "unless this status says so; a calendar availability check is not a booking."
            )
        if pending:
            # Structured and rechecked by the server: the request survives, its prose does not.
            context.append(
                "Server-reauthorized pending request awaiting the user's reply: "
                + json.dumps(
                    {
                        "kind": pending.get("kind"),
                        "lead_id": pending.get("lead_id"),
                        "details": pending.get("details") or {},
                    },
                    sort_keys=True,
                )
                + ". The details are what the user already said (their own words and values, "
                "not CRM evidence); details.missing is what was asked for. If the new message "
                "supplies or corrects some of it, it continues this request: route it to the "
                "workflow that was handling it (a kind means action preparation; task find_leads "
                "or check_calendar means personal CRM retrieval; plan_followups means follow-up "
                "planning) and do not ask again for anything already given. A lead_id is the "
                "target: do not ask which lead. A null kind with a lead_id means the user chose "
                "this lead but the action is still being clarified. If the message is clearly a "
                "different request, treat it as new. Completing a change still needs the user's "
                "confirmation."
            )
        if context:
            result.append(ModelRequest(parts=[UserPromptPart(content=" ".join(context))]))
        result.extend(_open_question(messages))
        return result
    # Newest first until the token budget is spent: every request in the turn resends this.
    remaining = settings.ASSISTANT_HISTORY_TOKEN_LIMIT
    for msg in reversed(messages[-30:]):
        if msg.role == "user":
            item = ModelRequest(parts=[UserPromptPart(content=msg.content[:8000])])
        elif msg.role == "assistant" and (msg.meta_data or {}).get("guardrail_version") == 1:
            item = ModelResponse(parts=[TextPart(content=msg.content[:16000])])
        else:
            continue
        cost = estimate_tokens(item.parts[0].content)
        if cost > remaining:
            break
        remaining -= cost
        result.append(item)
    result.reverse()
    return result
