import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import FunctionToolResultEvent, ToolCallPart
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.assistant import repository
from app.crm.assistant.actions import proposed_payload
from app.crm.assistant.agent import (
    assistant_agent,
    assistant_model_settings,
    history_to_model_messages,
)
from app.crm.assistant.deps import AssistantDeps
from app.crm.assistant.models import (
    AssistantMessageResponse,
    CrmAssistantConversation,
    CrmAssistantMessage,
    encode_sse,
    message_meta,
)
from app.token_usage.service import token_usage_service

logger = logging.getLogger(__name__)

NEW_TITLE = "New conversation"
TOOL_LABELS = {
    "search_leads": "Searching leads…",
    "get_lead": "Reading the lead…",
    "lead_pipeline_summary": "Counting your pipeline…",
    "list_org_members": "Looking up your team…",
    "propose_status_change": "Preparing a change…",
    "propose_add_note": "Preparing a change…",
    "propose_follow_up": "Preparing a change…",
    "propose_assign": "Preparing a change…",
    "propose_share": "Preparing to share…",
    "list_calendar_events": "Checking your calendar…",
    "propose_calendar_event": "Preparing a booking…",
    "email_overview": "Checking your email…",
    "lead_email_thread": "Reading the lead's emails…",
    "list_email_templates": "Looking up your templates…",
    "propose_send_email": "Preparing an email…",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_conversation(
    db: AsyncSession, user_id: str, organization_id: str, title: str | None = None
) -> CrmAssistantConversation:
    now = _now()
    conversation = CrmAssistantConversation(
        user_id=user_id,
        organization_id=organization_id,
        title=title or NEW_TITLE,
        created_at=now,
        updated_at=now,
    )
    repository.save(db, conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def list_conversations(
    db: AsyncSession, user_id: str, organization_id: str, limit: int = 50, offset: int = 0
) -> list[CrmAssistantConversation]:
    return await repository.list_conversations(db, user_id, organization_id, limit, offset)


async def get_conversation(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str
) -> CrmAssistantConversation | None:
    return await repository.get_conversation(db, conversation_id, user_id, organization_id)


async def rename_conversation(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str, title: str
) -> CrmAssistantConversation | None:
    conversation = await get_conversation(db, conversation_id, user_id, organization_id)
    if not conversation:
        return None
    conversation.title = title
    conversation.updated_at = _now()
    repository.save(db, conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def delete_conversation(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str
) -> bool:
    if not await get_conversation(db, conversation_id, user_id, organization_id):
        return False
    await repository.delete_conversation_records(db, conversation_id, user_id, organization_id)
    await db.commit()
    return True


async def list_messages(
    db: AsyncSession,
    conversation_id: int,
    user_id: str,
    organization_id: str,
    limit: int = 100,
    offset: int = 0,
) -> list[CrmAssistantMessage]:
    return await repository.list_messages(
        db, conversation_id, user_id, organization_id, limit, offset
    )


async def add_message(
    db: AsyncSession,
    conversation_id: int,
    role: str,
    content: str,
    meta_data: dict[str, Any] | None = None,
    *,
    user_id: str,
    organization_id: str,
) -> CrmAssistantMessage:
    """Add a turn to a conversation the caller owns; nothing is written otherwise."""
    conversation = await get_conversation(db, conversation_id, user_id, organization_id)
    if conversation is None:
        raise LookupError("Conversation not found")
    message = CrmAssistantMessage(
        conversation_id=conversation_id,
        role=role,
        content=content,
        meta_data=meta_data or {},
        created_at=_now(),
    )
    repository.save(db, message)
    conversation.updated_at = _now()
    if role == "user" and (not conversation.title or conversation.title == NEW_TITLE):
        conversation.title = content[:50] + ("..." if len(content) > 50 else "")
    await db.commit()
    await db.refresh(message)
    return message


async def get_messages_with_action_status(
    db: AsyncSession,
    conversation_id: int,
    user_id: str,
    organization_id: str,
    limit: int = 100,
    offset: int = 0,
) -> list[AssistantMessageResponse]:
    """Stored turns, with each proposed action's status as it is now (confirmed, expired…)."""
    messages = await list_messages(db, conversation_id, user_id, organization_id, limit, offset)
    action_ids = [
        item["action_id"]
        for message in messages
        for item in message_meta(message).get("actions", [])
        if item.get("action_id")
    ]
    rows = await repository.get_actions_by_ids(db, action_ids, user_id, organization_id)
    now = _now()
    current = {}
    for row in rows:
        expires_at = (
            row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        )
        current[row.id] = {
            **proposed_payload(row),
            "status": "expired" if row.status == "pending" and expires_at <= now else row.status,
        }

    responses = []
    for message in messages:
        meta_data = dict(message_meta(message))
        if meta_data.get("actions"):
            meta_data["actions"] = [
                {**item, **current.get(item.get("action_id"), {})} for item in meta_data["actions"]
            ]
        response = AssistantMessageResponse(
            id=message.id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            meta_data=meta_data,
            created_at=message.created_at,
        )
        responses.append(response)
    return responses


def _card(tool_result: Any) -> dict[str, Any] | None:
    """The action card a tool result asks the chat to show, if any."""
    if not isinstance(tool_result, dict):
        return None
    if tool_result.get("action_id"):
        return tool_result
    if share := tool_result.get("share"):
        return {
            "action_id": None,
            "action_type": "share",
            "lead_id": share["lead_id"],
            "summary": share["summary"],
            "channel": share["channel"],
            "text": share["text"],
            "status": "confirmed",
        }
    return None


async def stream_assistant_response(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_message: str,
    deps: AssistantDeps,
) -> AsyncGenerator[str, None]:
    """Run one assistant turn and stream it as SSE (text-delta, tool-status, action-proposed)."""
    scope = {"user_id": deps.user_id, "organization_id": deps.organization_id}
    if not await get_conversation(db, conversation_id, **scope):
        yield encode_sse({"type": "error", "error": "Conversation not found"})
        return

    await add_message(db, conversation_id, "user", user_message, **scope)
    stored = await get_messages_with_action_status(db, conversation_id, **scope)
    history = history_to_model_messages(stored[:-1])  # the turn just saved is the prompt
    deps.conversation_id = conversation_id

    reply = ""
    cards: list[dict[str, Any]] = []
    total_tokens = 0
    try:
        async with assistant_agent.iter(
            user_message,
            deps=deps,
            message_history=history,
            model_settings=assistant_model_settings(),
        ) as run:
            async for node in run:
                if PydanticAgent.is_model_request_node(node):
                    async with node.stream(run.ctx) as stream:
                        async for chunk in stream.stream_text(delta=True, debounce_by=0.01):
                            reply += chunk
                            yield encode_sse({"type": "text-delta", "content": chunk})
                elif PydanticAgent.is_call_tools_node(node):
                    for part in node.model_response.parts:
                        if isinstance(part, ToolCallPart):
                            yield encode_sse(
                                {
                                    "type": "tool-status",
                                    "tool": part.tool_name,
                                    "label": TOOL_LABELS.get(part.tool_name, "Working…"),
                                }
                            )
                    async with node.stream(run.ctx) as tool_stream:
                        async for event in tool_stream:
                            if not isinstance(event, FunctionToolResultEvent):
                                continue
                            card = _card(getattr(event.result, "content", None))
                            if card is not None:
                                cards.append(card)
                                yield encode_sse({"type": "action-proposed", "action": card})

            usage = run.usage()
            total_tokens = getattr(usage, "total_tokens", 0) or 0
            if total_tokens:
                await token_usage_service.record_usage(
                    db=db,
                    user_id=deps.user_id,
                    prompt_tokens=getattr(usage, "input_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "output_tokens", 0) or 0,
                    total_tokens=total_tokens,
                )

        if reply or cards:
            meta_data: dict[str, Any] = {}
            if total_tokens:
                meta_data["total_tokens"] = total_tokens
            if cards:
                meta_data["actions"] = cards
            await add_message(
                db,
                conversation_id,
                "assistant",
                reply or "Please review the card below.",
                meta_data,
                **scope,
            )
        yield encode_sse({"type": "done"})
    except Exception as error:
        # Only ids and the error type: messages from providers or the database can carry
        # prompt text or lead details.
        logger.error(
            "assistant stream failed conversation=%s org=%s error=%s",
            conversation_id,
            deps.organization_id,
            type(error).__name__,
        )
        yield encode_sse({"type": "error", "error": "Something went wrong"})
