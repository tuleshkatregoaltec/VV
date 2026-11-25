import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncGenerator, List

from fastapi import HTTPException
from pydantic_ai.usage import RunUsage
from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat import admission, repository
from app.chat.budget import turn_limits
from app.chat.conversations import (
    add_message,
    get_conversation,
)
from app.chat.errors import error_event, failure_event
from app.chat.events import encode_sse as _sse
from app.chat.models import Message
from app.chat.security import (
    RESTRICTED_HISTORY,
    fingerprint,
    guarded_answer,
    input_refusal,
    safe_answer,
    safe_data,
)
from app.config import settings
from app.crm.assistant import has_current_access, query_my_records
from app.crm.assistant.agent import _convert_to_pydantic_messages, agent
from app.crm.assistant.connector_tools import CONNECTOR_EVIDENCE, evidence_still_accessible
from app.crm.assistant.dependencies import ChatDependencies
from app.crm.assistant.models import CrmAssistantQuery
from app.crm.assistant.routing import run_routed_turn
from app.token_usage.service import allowance_resets_at

logger = logging.getLogger(__name__)

TURN_DEADLINE_SECONDS = 300
# Name lookups recorded as turn evidence, rechecked (same result) whenever history loads.
LOOKUP_EVIDENCE = {
    "assignee_lookup": "lookup_assignees",
    "colleague_lookup": "lookup_colleagues",
    "team_lookup": "lookup_teams",
    "team_people_lookup": "lookup_team_people",
}


async def _evidence_accessible(db, evidence, user_id, organization_id) -> bool:
    if evidence and not await has_current_access(
        db, user_id=user_id, organization_id=organization_id
    ):
        return False
    for reference in evidence:
        try:
            if reference.get("type") in CONNECTOR_EVIDENCE:
                if not await evidence_still_accessible(
                    db, reference, user_id=user_id, organization_id=organization_id
                ):
                    return False
                continue
            if reference.get("type") == "pending_action":
                result = await _pending_target(db, reference, user_id, organization_id)
                if not result.get("available"):
                    return False
                continue
            if reference.get("type") in LOOKUP_EVIDENCE:
                from app.assistant_actions import service as actions

                lookup = getattr(actions, LOOKUP_EVIDENCE[reference["type"]])
                result = await lookup(
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


async def _pending_target(db, reference, user_id, organization_id):
    from app.assistant_actions.models import ActionKind
    from app.assistant_actions.service import pending_target

    return await pending_target(
        db,
        user_id=user_id,
        organization_id=organization_id,
        kind=ActionKind(reference["kind"]) if reference.get("kind") else None,
        lead_id=int(reference["lead_id"]) if reference.get("lead_id") else None,
    )


def _pending_details(reference) -> dict:
    """The held details, revalidated as typed values; raises when they are not."""
    from app.crm.assistant.workflows import PendingDetails

    details = PendingDetails.model_validate(reference.get("details") or {})
    raw = details.model_dump(mode="json", exclude_defaults=True)
    if not safe_answer(json.dumps(raw)):
        raise ValueError("Pending details are not permitted")
    return raw


# A pending request survives turns that neither replace nor settle it (a further clarifying
# question), but not indefinitely: after this many it lapses and must be asked for again.
PENDING_MAX_CARRIES = 2


def _carry_pending(prior: dict | None, deps: ChatDependencies) -> None:
    """Keep the still-valid pending request of the last turn when this turn did not re-hold
    it, replace it or settle it with a proposal. `prior` was rechecked when history loaded and
    is rechecked again before the answer is saved and on every later turn."""
    if deps.proposals:
        # A proposal settles the request, including one held earlier in this turn.
        deps.evidence[:] = [i for i in deps.evidence if i.get("type") != "pending_action"]
        return
    if not prior or any(item.get("type") == "pending_action" for item in deps.evidence):
        return
    carried = int(prior.get("carried", 0)) + 1
    if carried > PENDING_MAX_CARRIES:
        return
    deps.evidence.append(
        {
            "private": True,
            "type": "pending_action",
            "kind": prior["kind"],
            "lead_id": prior["lead_id"],
            "details": prior.get("details") or {},
            "carried": carried,
        }
    )


async def _current_pending_action(db, messages, user_id, organization_id):
    """The request the latest answer left waiting for the user's reply, if still permitted.

    Only the latest assistant message counts: any later answer settles or replaces it. Kind and
    lead ID only, rechecked against current access; never any private text.
    """
    index = next(
        (i for i in range(len(messages) - 1, -1, -1) if messages[i].role == "assistant"), None
    )
    if index is None:
        return None, None
    pending = [
        item
        for item in (messages[index].meta_data or {}).get("evidence", [])
        if item.get("type") == "pending_action"
    ]
    if not pending:
        return None, None
    try:
        result = await _pending_target(db, pending[-1], user_id, organization_id)
        details = _pending_details(pending[-1])
    except Exception:
        return None, None
    if not result.get("available"):
        return None, None
    lead_id = pending[-1].get("lead_id")
    return index, {
        "kind": pending[-1].get("kind"),
        "lead_id": int(lead_id) if lead_id else None,
        "details": details,
        "carried": int(pending[-1].get("carried", 0)),
    }


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
    from app.assistant_actions import outcome

    visible = []
    for message in messages:
        if message.role != "assistant":
            visible.append(message)
            continue
        metadata = dict(message.meta_data or {})
        action_responses = []
        permitted = metadata.get("guardrail_version") == 1
        stale_prose = False
        if metadata.get("private"):
            permitted = permitted and await has_current_access(
                db, user_id=user_id, organization_id=organization_id
            )
            evidence = metadata.get("evidence", [])
            permitted = permitted and bool(evidence or metadata.get("actions"))
            current = await _evidence_accessible(db, evidence, user_id, organization_id)
            if metadata.get("actions"):
                # Each action is rechecked below and states its own status. Changed evidence,
                # often the confirmed action's own effect, makes only the model's prose stale.
                stale_prose = not current
            else:
                permitted = permitted and current
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
                        action_responses.append(action_response)
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
            update = {"meta_data": public_metadata}
            if action_responses:
                # The stored text was written before confirmation; the action's current status
                # decides what this answer says about it.
                update["content"] = outcome.compose(
                    "" if stale_prose else message.content, action_responses
                )
                if include_retrieval_context:
                    public_metadata["_action_outcomes"] = outcome.model_context(action_responses)
            visible.append(message.model_copy(update=update))
    if include_retrieval_context:
        index, handles = await _current_record_handles(db, messages, user_id, organization_id)
        if index is not None and handles:
            visible[index].meta_data = {
                **(visible[index].meta_data or {}),
                "_retrieval_context": handles,
            }
        index, pending = await _current_pending_action(db, messages, user_id, organization_id)
        if index is not None:
            visible[index].meta_data = {
                **(visible[index].meta_data or {}),
                "_pending_action": pending,
            }
    return visible


@dataclass(frozen=True)
class AssistantRuntime:
    """Which assistant answers a turn: its coordinator, typed router and product tag.

    The CRM Operations Assistant is the default. Market AI (app.market_ai) passes its own; the
    turn's checks (admission, evidence and access rechecks, proposals, outcomes) are the same.
    """

    name: str
    agent: Any
    run_routed_turn: Any


async def stream_chat_response(
    db: AsyncSession,
    conversation_id: int,
    user_message: str,
    user_id: str,
    organization_id: str,
    runtime: AssistantRuntime | None = None,
) -> AsyncGenerator[str, None]:
    """Only validated complete answers cross the SSE/persistence boundary."""
    # Each assistant answers only in its own conversations: a CRM conversation is not found by
    # Market AI's endpoint, and a Market AI conversation not by the CRM assistant's.
    assistant = runtime.name if runtime is not None else "crm"
    conversation = await get_conversation(
        db, conversation_id, user_id, organization_id, assistant=assistant
    )
    if not conversation:
        yield _sse(error_event("conversation_not_found"))
        return
    scope = {"user_id": user_id, "organization_id": organization_id}
    refusal = input_refusal(user_message)
    # Do not persist submitted credentials, dump requests or oversized input.
    if refusal:
        yield _sse({"type": "content", "content": refusal})
        yield _sse({"type": "done"})
        return
    if not settings.ASSISTANT_ENABLED:
        yield _sse(error_event("assistant_disabled"))
        return
    # Request auth and conversation lookup may already hold a read connection.
    await db.commit()
    try:
        async with asyncio.timeout(30):
            lease = await admission.acquire(**scope, conversation_id=conversation_id)
    except admission.AdmissionRefused as exc:
        # Nothing was reserved or saved: the turn never started.
        if exc.code == "busy":
            yield _sse(error_event("turn_in_progress"))
        else:
            yield _sse(error_event("insufficient_allowance", resets_at=allowance_resets_at()))
        return
    except HTTPException:
        yield _sse(error_event("account_unavailable"))
        return
    except TimeoutError:
        # Admission waits on a shared lock; nothing was reserved.
        yield _sse(error_event("service_busy"))
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
            history = _convert_to_pydantic_messages(
                messages[:-1], include_market=runtime is not None
            )
            prior_pending = next(
                (
                    (m.meta_data or {})["_pending_action"]
                    for m in reversed(messages[:-1])
                    if (m.meta_data or {}).get("_pending_action")
                ),
                None,
            )
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
            pending=dict(prior_pending or {}),
        )
        typed = settings.ASSISTANT_TYPED_ROUTING_ENABLED
        if runtime is None:
            run = run_routed_turn if typed else agent.run
        else:
            run = runtime.run_routed_turn if typed else runtime.agent.run

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
            _carry_pending(prior_pending, deps)
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
            answer = guarded_answer(answer)
            # Stored as written; whenever shown, the actions' current status is put first and
            # the model's own claims about them are left out (assistant_actions/outcome.py).
            shown = answer
            if deps.proposals:
                from app.assistant_actions.models import ActionProposalResponse
                from app.assistant_actions.outcome import compose

                shown = compose(
                    answer, [ActionProposalResponse.model_validate(p) for p in deps.proposals]
                )
            metadata = {"guardrail_version": 1, "private": bool(deps.evidence or deps.proposals)}
            if runtime is not None:
                metadata["assistant"] = runtime.name
            if usage.total_tokens:
                metadata["total_tokens"] = usage.total_tokens
            if deps.evidence:
                metadata["evidence"] = deps.evidence
            if deps.proposals:
                metadata["actions"] = [{"id": item["id"]} for item in deps.proposals]
            await add_message(db, conversation_id, "assistant", answer, metadata, **scope)
        yield _sse({"type": "content", "content": shown})
        for proposal in deps.proposals:
            yield _sse({"type": "action_proposed", "action": safe_data(proposal)})
        yield _sse({"type": "done"})
    except Exception as exc:
        yield _sse(
            failure_event(
                exc,
                context="Chat turn",
                requests=usage.requests,
                tokens=usage.total_tokens,
                budget=lease.token_budget,
            )
        )
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
