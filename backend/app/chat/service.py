import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, List, Optional

from fastapi import HTTPException
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import RunUsage
from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat import admission, repository
from app.chat.agent import _convert_to_pydantic_messages, agent
from app.chat.budget import turn_limits
from app.chat.dependencies import ChatDependencies
from app.chat.events import encode_sse as _sse
from app.chat.models import Conversation, Message
from app.chat.routing import run_routed_turn
from app.chat.security import (
    REFUSAL,
    RESTRICTED_HISTORY,
    fingerprint,
    input_refusal,
    safe_answer,
    safe_data,
)
from app.config import settings
from app.crm.assistant import has_current_access, query_my_records
from app.crm.assistant_models import CrmAssistantQuery

logger = logging.getLogger(__name__)

TURN_DEADLINE_SECONDS = 300
TURN_ERROR = "Unable to complete this answer. Please try again."
TURN_LIMIT_ERROR = (
    "This question needed more research steps than one answer allows. "
    "Please ask about one area, project or record at a time."
)


async def create_conversation(
    db: AsyncSession, user_id: str, organization_id: str, title: Optional[str] = None
) -> Conversation:
    """Create a new conversation"""
    now = datetime.now(timezone.utc)
    conversation = Conversation(
        user_id=user_id,
        organization_id=organization_id,
        title=title or "New Conversation",
        created_at=now,
        updated_at=now,
    )
    repository.save_conversation(db, conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_user_conversations(
    db: AsyncSession, user_id: str, organization_id: str, limit: int = 50, offset: int = 0
) -> List[Conversation]:
    return await repository.get_user_conversations(db, user_id, organization_id, limit, offset)


async def get_conversation(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str
) -> Optional[Conversation]:
    return await repository.get_conversation(db, conversation_id, user_id, organization_id)


async def update_conversation(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str, title: str
) -> Optional[Conversation]:
    """Update a conversation's title"""
    conversation = await get_conversation(db, conversation_id, user_id, organization_id)
    if not conversation:
        return None

    conversation.title = title
    conversation.updated_at = datetime.now(timezone.utc)
    repository.save_conversation(db, conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def delete_conversation(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str
) -> bool:
    """Delete a conversation and all its messages"""
    conversation = await get_conversation(db, conversation_id, user_id, organization_id)
    if not conversation:
        return False

    await repository.delete_conversation_records(db, conversation_id, user_id, organization_id)
    await db.commit()
    return True


async def _evidence_accessible(db, evidence, user_id, organization_id) -> bool:
    if evidence and not await has_current_access(
        db, user_id=user_id, organization_id=organization_id
    ):
        return False
    for reference in evidence:
        try:
            if reference.get("type") == "assignee_lookup":
                from app.assistant_actions.service import lookup_assignees

                result = await lookup_assignees(
                    db,
                    user_id=user_id,
                    organization_id=organization_id,
                    search=reference["search"],
                )
                if fingerprint(result) != reference["fingerprint"]:
                    return False
                continue
            result = await query_my_records(
                db,
                CrmAssistantQuery.model_validate(reference["query"]),
                user_id=user_id,
                organization_id=organization_id,
            )
            payload = safe_data(result.model_dump(mode="json"))
            payload["source"] = "Your CRM records"
            if fingerprint(payload) != reference["fingerprint"]:
                return False
        except Exception:
            return False
    return True


async def _current_record_handles(db, messages, user_id, organization_id):
    """Reauthorize at most twenty handles from the latest relevant private answer.

    Fact changes invalidate historical prose without invalidating a still-owned
    resource's identity. Never carry names, values or search strings in this context.
    """
    if not await has_current_access(db, user_id=user_id, organization_id=organization_id):
        return None, []
    for index in range(len(messages) - 1, -1, -1):
        metadata = messages[index].meta_data or {}
        references = [
            ref
            for evidence in metadata.get("evidence", [])
            for ref in evidence.get("resource_refs", [])
        ][:20]
        if not references:
            continue
        current = []
        seen = set()
        for ref in references:
            try:
                request = CrmAssistantQuery(
                    resource=ref["resource"], record_id=ref["record_id"], limit=1
                )
                key = (request.resource, request.record_id)
                if key in seen:
                    continue
                seen.add(key)
                result = await query_my_records(
                    db, request, user_id=user_id, organization_id=organization_id
                )
                if result.available and any(
                    row.get("id") == request.record_id for row in result.records
                ):
                    current.append({"resource": request.resource, "record_id": request.record_id})
            except Exception:
                continue
        return index, current
    return None, []


async def get_conversation_messages(
    db: AsyncSession,
    conversation_id: int,
    user_id: str,
    organization_id: str,
    limit: int = 100,
    before_id: int | None = None,
    include_retrieval_context: bool = False,
) -> List[Message]:
    messages = await repository.get_conversation_messages(
        db, conversation_id, user_id, organization_id, limit, before_id
    )
    visible = []
    for message in messages:
        if message.role != "assistant":
            visible.append(message)
            continue
        metadata = dict(message.meta_data or {})
        permitted = metadata.get("guardrail_version") == 1
        if metadata.get("private"):
            permitted = permitted and await has_current_access(
                db, user_id=user_id, organization_id=organization_id
            )
            evidence = metadata.get("evidence", [])
            permitted = permitted and bool(evidence or metadata.get("actions"))
            permitted = permitted and await _evidence_accessible(
                db, evidence, user_id, organization_id
            )
            if metadata.get("actions"):
                from app.assistant_actions.service import get_action

                for action in metadata["actions"]:
                    try:
                        action_response = await get_action(
                            db,
                            user_id=user_id,
                            organization_id=organization_id,
                            action_id=action["id"],
                        )
                        permitted = (
                            permitted and action_response.preview.get("available") is not False
                        )
                    except Exception:
                        permitted = False
        # A copied model avoids dirtying ORM state while preparing an authorized response.
        public_metadata = {
            key: value
            for key, value in metadata.items()
            if key not in {"evidence", "_retrieval_context"}
        }
        if not permitted or not safe_answer(message.content):
            visible.append(
                message.model_copy(
                    update={
                        "content": RESTRICTED_HISTORY,
                        "meta_data": {"restricted": True, "private": True},
                    }
                )
            )
        else:
            visible.append(message.model_copy(update={"meta_data": public_metadata}))
    if include_retrieval_context:
        index, handles = await _current_record_handles(db, messages, user_id, organization_id)
        if index is not None and handles:
            visible[index].meta_data = {
                **(visible[index].meta_data or {}),
                "_retrieval_context": handles,
            }
    return visible


async def add_message(
    db: AsyncSession,
    conversation_id: int,
    role: str,
    content: str,
    meta_data: Optional[dict[str, Any]] = None,
    *,
    user_id: str,
    organization_id: str,
) -> Message:
    """Add a message to a conversation the caller owns; nothing is written otherwise."""
    conversation = await get_conversation(db, conversation_id, user_id, organization_id)
    if conversation is None:
        raise LookupError("Conversation not found")

    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        meta_data=meta_data or {},
        created_at=datetime.now(timezone.utc),
    )
    repository.save_message(db, message)

    # Update conversation timestamp
    conversation.updated_at = datetime.now(timezone.utc)
    # Auto-generate title from first user message
    if not conversation.title or conversation.title == "New Conversation":
        conversation.title = content[:50] + ("..." if len(content) > 50 else "")

    await db.commit()
    await db.refresh(message)
    return message


async def stream_chat_response(
    db: AsyncSession,
    conversation_id: int,
    user_message: str,
    user_id: str,
    organization_id: str,
) -> AsyncGenerator[str, None]:
    """Only validated complete answers cross the SSE/persistence boundary."""
    conversation = await get_conversation(db, conversation_id, user_id, organization_id)
    if not conversation:
        yield _sse({"type": "error", "error": "Conversation not found"})
        return
    scope = {"user_id": user_id, "organization_id": organization_id}
    refusal = input_refusal(user_message)
    # Do not persist submitted credentials, dump requests or oversized input.
    if refusal:
        yield _sse({"type": "content", "content": refusal})
        yield _sse({"type": "done"})
        return
    if not settings.ASSISTANT_ENABLED:
        yield _sse({"type": "error", "error": "The assistant is not enabled yet."})
        return
    # Request auth and conversation lookup may already hold a read connection.
    await db.commit()
    try:
        async with asyncio.timeout(30):
            lease = await admission.acquire(**scope, conversation_id=conversation_id)
    except HTTPException as exc:
        yield _sse({"type": "error", "error": exc.detail})
        return
    usage = RunUsage()
    provider_completed = False
    run_task: asyncio.Task | None = None
    next_event: asyncio.Future | None = None
    deadline = asyncio.get_running_loop().time() + TURN_DEADLINE_SECONDS
    try:
        yield _sse({"type": "thinking"})
        # Deadlines wrap only non-yielding sections: the SSE heartbeat resumes this
        # generator from a different task each time.
        async with asyncio.timeout_at(deadline):
            await add_message(db, conversation_id, "user", user_message, **scope)
            messages = await get_conversation_messages(
                db, conversation_id, **scope, include_retrieval_context=True
            )
            history = _convert_to_pydantic_messages(messages[:-1])
            # Release the read transaction and pool connection before nested tools
            # open their own sessions during provider latency.
            await db.commit()
        progress: asyncio.Queue = asyncio.Queue()
        limits = turn_limits(lease.token_budget)
        deps = ChatDependencies(
            **scope,
            conversation_id=conversation_id,
            usage_limits=limits,
            progress=progress.put_nowait,
        )
        run = run_routed_turn if settings.ASSISTANT_TYPED_ROUTING_ENABLED else agent.run

        async def run_turn():
            async with asyncio.timeout_at(deadline):
                return await run(
                    user_message,
                    deps=deps,
                    message_history=history,
                    usage_limits=limits,
                    usage=usage,
                )

        run_task = asyncio.create_task(run_turn())
        # Tool names stream while the provider works; answer text only after validation.
        while True:
            next_event = asyncio.ensure_future(progress.get())
            await asyncio.wait({run_task, next_event}, return_when=asyncio.FIRST_COMPLETED)
            if next_event.done():
                yield _sse(next_event.result())
                continue
            next_event.cancel()
            break
        while not progress.empty():
            yield _sse(progress.get_nowait())
        result = run_task.result()
        async with asyncio.timeout_at(deadline):
            provider_completed = True
            answer = result.output
            # A target can be reassigned while the provider is composing its answer.
            if (deps.evidence or deps.proposals) and (
                not await has_current_access(db, user_id=user_id, organization_id=organization_id)
                or not await _evidence_accessible(db, deps.evidence, user_id, organization_id)
            ):
                answer = RESTRICTED_HISTORY
                deps.proposals.clear()
            if deps.proposals:
                from app.assistant_actions.service import get_action

                current_proposals = []
                try:
                    for proposal in deps.proposals:
                        current = await get_action(
                            db,
                            user_id=user_id,
                            organization_id=organization_id,
                            action_id=proposal["id"],
                        )
                        if (
                            current.preview.get("available") is False
                            or current.status != "awaiting_confirmation"
                        ):
                            raise PermissionError("Action target is no longer accessible")
                        current_proposals.append(current.model_dump(mode="json"))
                except Exception:
                    answer = RESTRICTED_HISTORY
                    deps.proposals.clear()
                else:
                    deps.proposals[:] = current_proposals
            if not safe_answer(answer):
                answer = REFUSAL
            metadata = {"guardrail_version": 1, "private": bool(deps.evidence or deps.proposals)}
            if usage.total_tokens:
                metadata["total_tokens"] = usage.total_tokens
            if deps.evidence:
                metadata["evidence"] = deps.evidence
            if deps.proposals:
                metadata["actions"] = [{"id": item["id"]} for item in deps.proposals]
            await add_message(db, conversation_id, "assistant", answer, metadata, **scope)
        yield _sse({"type": "content", "content": answer})
        for proposal in deps.proposals:
            yield _sse({"type": "action_proposed", "action": safe_data(proposal)})
        yield _sse({"type": "done"})
    except Exception as exc:
        logger.error(
            "Chat execution failed (%s; requests=%s tokens=%s budget=%s)",
            type(exc).__name__,
            usage.requests,
            usage.total_tokens,
            lease.token_budget,
        )
        error = TURN_LIMIT_ERROR if isinstance(exc, UsageLimitExceeded) else TURN_ERROR
        yield _sse({"type": "error", "error": error})
    finally:
        if next_event is not None:
            next_event.cancel()
        if run_task is not None and not run_task.done():
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
        try:
            await asyncio.shield(admission.finish(lease.id, usage, successful=provider_completed))
        except Exception as exc:
            # The committed reservation remains charged and its capacity lease
            # expires; a database outage must not turn failed cleanup into credit.
            logger.error("Chat admission settlement failed (%s)", type(exc).__name__)
