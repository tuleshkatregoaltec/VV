import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncGenerator, List, Optional

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import (
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.openrouter import OpenRouterModelSettings
from sqlalchemy import delete, text
from sqlalchemy.exc import ProgrammingError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat.agent import agent
from app.chat.models import Conversation, Message
from app.clickhouse import query as ch_query
from app.clickhouse.queries import price_trends
from app.listings.models import ListingMode
from app.listings.service import list_demo_listings
from app.token_usage.service import token_usage_service

logger = logging.getLogger(__name__)


async def create_conversation(
    db: AsyncSession, user_id: str, title: Optional[str] = None
) -> Conversation:
    """Create a new conversation"""
    now = datetime.now(timezone.utc)
    conversation = Conversation(
        user_id=user_id,
        title=title or "New Conversation",
        created_at=now,
        updated_at=now,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_user_conversations(
    db: AsyncSession, user_id: str, limit: int = 50, offset: int = 0
) -> List[Conversation]:
    """Get all conversations for a user"""
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.exec(stmt)
    return list(result.all())


async def get_conversation(
    db: AsyncSession, conversation_id: int, user_id: str
) -> Optional[Conversation]:
    """Get a conversation by ID (with auth check)"""
    stmt = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id
    )
    result = await db.exec(stmt)
    return result.first()


async def update_conversation(
    db: AsyncSession, conversation_id: int, user_id: str, title: str
) -> Optional[Conversation]:
    """Update a conversation's title"""
    conversation = await get_conversation(db, conversation_id, user_id)
    if not conversation:
        return None

    conversation.title = title
    conversation.updated_at = datetime.now(timezone.utc)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def delete_conversation(db: AsyncSession, conversation_id: int, user_id: str) -> bool:
    """Delete a conversation and all its messages"""
    conversation = await get_conversation(db, conversation_id, user_id)
    if not conversation:
        return False

    await db.execute(
        delete(Message)
        .where(Message.conversation_id == conversation_id)
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        delete(Conversation)
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return True


async def get_conversation_messages(
    db: AsyncSession, conversation_id: int, limit: int = 100
) -> List[Message]:
    """Get messages for a conversation"""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
    )
    result = await db.exec(stmt)
    return list(result.all())


async def add_message(
    db: AsyncSession,
    conversation_id: int,
    role: str,
    content: str,
    meta_data: Optional[dict[str, Any]] = None,
) -> Message:
    """Add a message to a conversation"""
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        meta_data=meta_data or {},
        created_at=datetime.now(timezone.utc),
    )
    db.add(message)

    # Update conversation timestamp
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    result = await db.exec(stmt)
    conversation = result.first()
    if conversation:
        conversation.updated_at = datetime.now(timezone.utc)
        # Auto-generate title from first user message
        if not conversation.title or conversation.title == "New Conversation":
            conversation.title = content[:50] + ("..." if len(content) > 50 else "")

    await db.commit()
    await db.refresh(message)
    return message


def _convert_to_pydantic_messages(messages: List[Message]) -> List[ModelMessage]:
    """Convert database messages to Pydantic AI message format"""
    pydantic_messages: List[ModelMessage] = []

    for msg in messages:
        if msg.role == "user":
            pydantic_messages.append(ModelRequest(parts=[UserPromptPart(content=msg.content)]))
        elif msg.role == "assistant":
            pydantic_messages.append(ModelResponse(parts=[TextPart(content=msg.content)]))

    return pydantic_messages


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))


def _positive_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _listing_mode(value: Any) -> ListingMode:
    return "sale" if str(value).lower() == "sale" else "rent"


def _bedroom_values(args: dict[str, Any]) -> list[str] | None:
    exact = _clean_text(args.get("bedrooms"))
    if exact:
        return [exact.lower() if exact.lower() == "studio" else exact]

    min_bedrooms = _positive_int(args.get("bedrooms_min"))
    max_bedrooms = _positive_int(args.get("bedrooms_max"))
    if min_bedrooms is None and max_bedrooms is None:
        return None

    start = min_bedrooms if min_bedrooms is not None else 0
    end = max_bedrooms if max_bedrooms is not None else start
    if end < start:
        start, end = end, start
    return [str(value) for value in range(start, min(end, 10) + 1)]


def _artifact_shell(tool_name: str, tool_call_id: str, args: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    if tool_name == "show_listings":
        mode = _listing_mode(args.get("mode"))
        area = _clean_text(args.get("area"))
        title = "Rental listings" if mode == "rent" else "Sales listings"
        subtitle = area or "Dubai"
        return {
            "id": f"{tool_name}:{tool_call_id}",
            "type": "listing_results",
            "status": "loading",
            "title": title,
            "subtitle": subtitle,
            "created_at": now,
            "query": args,
        }
    if tool_name == "show_market_trend":
        area = _clean_text(args.get("area"))
        return {
            "id": f"{tool_name}:{tool_call_id}",
            "type": "market_trend",
            "status": "loading",
            "title": "Market trend",
            "subtitle": area or "Dubai market",
            "created_at": now,
            "query": args,
        }
    return {
        "id": f"{tool_name}:{tool_call_id}",
        "type": "unknown",
        "status": "loading",
        "title": tool_name.replace("_", " ").title(),
        "created_at": now,
        "query": args,
    }


async def _resolve_transaction_area(area: str | None) -> str | None:
    if not area:
        return None

    aliases = {
        "jvc": "Jumeirah Village Circle",
        "jumeirah village circle": "Jumeirah Village Circle",
        "dubai marina": "Dubai Marina",
        "jlt": "Jumeirah Lakes Towers",
        "jumeirah lake towers": "Jumeirah Lakes Towers",
        "jbr": "Jumeirah Beach Residence",
        "jumeirah beach residence": "Jumeirah Beach Residence",
        "downtown": "Downtown Dubai",
        "downtown dubai": "Downtown Dubai",
    }
    search_text = aliases.get(area.lower().strip(), area)
    sql = """
    SELECT area_name_en
    FROM ch_transactions
    WHERE area_name_en != ''
      AND (
        lower(area_name_en) = lower({area:String})
        OR lower(area_name_en) = lower({search_text:String})
        OR area_name_en ILIKE {pattern:String}
        OR lower(master_project_en) = lower({search_text:String})
        OR master_project_en ILIKE {pattern:String}
        OR project_name_en ILIKE {pattern:String}
      )
      AND trans_group_en = 'Sales'
      AND actual_worth > 0
    GROUP BY area_name_en
    ORDER BY
        (lower(area_name_en) = lower({area:String})) DESC,
        (lower(area_name_en) = lower({search_text:String})) DESC,
        count() DESC
    LIMIT 1
    """
    rows = await ch_query(
        sql, {"area": area, "search_text": search_text, "pattern": f"%{search_text}%"}
    )
    return rows[0]["area_name_en"] if rows else area


async def _latest_transaction_date(
    *,
    property_usage: str | None,
    property_type: str | None,
    area: str | None,
) -> date | None:
    where_clauses = ["trans_group_en = 'Sales'", "actual_worth > 0", "instance_date IS NOT NULL"]
    params: dict[str, Any] = {}

    if property_usage:
        where_clauses.append("property_usage_en = {property_usage:String}")
        params["property_usage"] = property_usage
    if property_type:
        where_clauses.append("property_type_en = {property_type:String}")
        params["property_type"] = property_type
    if area:
        where_clauses.append("area_name_en = {area_name:String}")
        params["area_name"] = area

    rows = await ch_query(
        f"""
        SELECT max(instance_date) AS max_date
        FROM ch_transactions
        WHERE {" AND ".join(where_clauses)}
        """,
        params,
    )
    if not rows:
        return None

    max_date = rows[0].get("max_date")
    if isinstance(max_date, date):
        return max_date
    if isinstance(max_date, str):
        try:
            return date.fromisoformat(max_date)
        except ValueError:
            return None
    return None


def _listing_subtitle(args: dict[str, Any], total: int) -> str:
    parts: list[str] = []
    area = _clean_text(args.get("area"))
    if area:
        parts.append(area)
    bedrooms = _bedroom_values(args)
    if bedrooms:
        parts.append(f"{'-'.join(bedrooms)} bed" if len(bedrooms) > 1 else f"{bedrooms[0]} bed")
    price_min = _positive_int(args.get("price_min"))
    price_max = _positive_int(args.get("price_max"))
    if price_min is not None or price_max is not None:
        low = f"AED {price_min:,}" if price_min is not None else "Any"
        high = f"AED {price_max:,}" if price_max is not None else "Any"
        suffix = "/mo" if args.get("price_basis") == "monthly" else ""
        parts.append(f"{low}-{high}{suffix}")
    parts.append(f"{total:,} matches")
    return " · ".join(parts)


async def _resolve_listing_area(
    db: AsyncSession, mode: ListingMode, area: str | None
) -> str | None:
    if not area:
        return None

    aliases = {
        "jvc": "Jumeirah Village Circle",
        "jbr": "Jumeirah Beach Residence",
        "jlt": "Jumeirah Lake Towers",
        "dubai marina": "Dubai Marina",
    }
    normalized = area.lower().strip()
    if "jvc" in normalized or "jumeirah village circle" in normalized:
        search_text = "Jumeirah Village Circle"
    elif "jbr" in normalized or "jumeirah beach residence" in normalized:
        search_text = "Jumeirah Beach Residence"
    elif "jlt" in normalized or "jumeirah lake towers" in normalized:
        search_text = "Jumeirah Lake Towers"
    else:
        search_text = aliases.get(normalized, area)

    try:
        result = await db.execute(
            text(
                """
                SELECT area_name
                FROM demo_pf_listings
                WHERE listing_mode = :mode
                  AND area_name IS NOT NULL
                  AND area_name <> ''
                  AND (
                    lower(area_name) = lower(:area)
                    OR lower(area_name) = lower(:search_text)
                    OR area_name ILIKE :pattern
                  )
                GROUP BY area_name
                ORDER BY
                    (lower(area_name) = lower(:area)) DESC,
                    (lower(area_name) = lower(:search_text)) DESC,
                    COUNT(*) DESC,
                    area_name ASC
                LIMIT 1
                """
            ),
            {
                "mode": mode,
                "area": area,
                "search_text": search_text,
                "pattern": f"%{search_text}%",
            },
        )
    except ProgrammingError:
        await db.rollback()
        return area

    row = result.first()
    return row[0] if row else area


async def _fetch_listing_artifact(
    db: AsyncSession, artifact: dict[str, Any], args: dict[str, Any]
) -> dict[str, Any]:
    mode = _listing_mode(args.get("mode"))
    limit = _clamp_int(args.get("limit"), default=12, min_value=1, max_value=24)
    price_basis = "monthly" if str(args.get("price_basis")).lower() == "monthly" else "raw"
    price_period = _clean_text(args.get("price_period"))
    area = await _resolve_listing_area(db, mode, _clean_text(args.get("area")))
    listings = await list_demo_listings(
        db=db,
        mode=mode,
        limit=limit,
        offset=0,
        area=area,
        property_type=_clean_text(args.get("property_type")),
        bedrooms_in=_bedroom_values(args),
        price_min=_positive_int(args.get("price_min")),
        price_max=_positive_int(args.get("price_max")),
        price_period=price_period,
        price_basis=price_basis,
    )
    payload = listings.model_dump(mode="json")
    return {
        **artifact,
        "status": "ready",
        "subtitle": _listing_subtitle(args, listings.total),
        "query": {
            "mode": mode,
            "area": area,
            "property_type": _clean_text(args.get("property_type")),
            "bedrooms": _bedroom_values(args),
            "price_min": _positive_int(args.get("price_min")),
            "price_max": _positive_int(args.get("price_max")),
            "price_basis": price_basis,
            "limit": limit,
        },
        "data": payload,
    }


async def _fetch_market_trend_artifact(
    artifact: dict[str, Any], args: dict[str, Any]
) -> dict[str, Any]:
    days = _clamp_int(args.get("days"), default=365, min_value=30, max_value=1095)
    interval = "day" if days <= 30 else "week" if days <= 180 else "month"
    property_usage = _clean_text(args.get("property_usage")) or "Residential"
    property_type = _clean_text(args.get("property_type"))
    area = await _resolve_transaction_area(_clean_text(args.get("area")))
    end_date = (
        await _latest_transaction_date(
            property_usage=property_usage,
            property_type=property_type,
            area=area,
        )
        or date.today()
    )
    start_date = end_date - timedelta(days=days)

    sql = price_trends(
        property_usage=property_usage,
        property_type=property_type,
        area_name=area,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        interval=interval,
    )
    params: dict[str, Any] = {
        "property_usage": property_usage,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    if property_type:
        params["property_type"] = property_type
    if area:
        params["area_name"] = area

    rows = await ch_query(sql, params)
    points = [
        {
            "date": str(row["period"]),
            "transaction_count": int(row["transaction_count"]),
            "avg_price": float(row["avg_price"] or 0),
            "avg_price_sqm": float(row["avg_price_sqm"] or 0),
        }
        for row in rows
    ]
    first = next((point for point in points if point["avg_price_sqm"] > 0), None)
    last = next((point for point in reversed(points) if point["avg_price_sqm"] > 0), None)
    change_pct = (
        round((last["avg_price_sqm"] - first["avg_price_sqm"]) / first["avg_price_sqm"] * 100, 1)
        if first and last and first["avg_price_sqm"]
        else None
    )
    total_transactions = sum(point["transaction_count"] for point in points)
    return {
        **artifact,
        "status": "ready",
        "subtitle": f"{area or 'Dubai market'} · {days} days · {total_transactions:,} transactions",
        "query": {
            "area": area,
            "property_usage": property_usage,
            "property_type": property_type,
            "days": days,
            "interval": interval,
        },
        "data": {
            "data": points,
            "total_transactions": total_transactions,
            "avg_price_sqm_change_pct": change_pct,
        },
    }


async def _fetch_artifact(
    db: AsyncSession, tool_name: str, tool_call_id: str, args: dict[str, Any]
) -> dict[str, Any] | None:
    if tool_name not in {"show_listings", "show_market_trend"}:
        return None

    artifact = _artifact_shell(tool_name, tool_call_id, args)
    try:
        if tool_name == "show_listings":
            return await _fetch_listing_artifact(db, artifact, args)
        if tool_name == "show_market_trend":
            return await _fetch_market_trend_artifact(artifact, args)
    except Exception as exc:
        logger.exception("Failed to build chat artifact for %s", tool_name)
        return {**artifact, "status": "error", "error": str(exc)}
    return None


async def stream_chat_response(
    db: AsyncSession,
    conversation_id: int,
    user_message: str,
    user_id: str,
    organization_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Stream chat response using Pydantic AI agent via SSE"""
    # Verify conversation ownership
    conversation = await get_conversation(db, conversation_id, user_id)
    if not conversation:
        yield f"data: {json.dumps({'type': 'error', 'error': 'Conversation not found'})}\n\n"
        return

    # Save user message
    await add_message(db, conversation_id, "user", user_message)

    # Get conversation history
    messages = await get_conversation_messages(db, conversation_id)
    message_history = _convert_to_pydantic_messages(messages[:-1])  # Exclude the just-added message

    assistant_message = ""
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    artifacts: list[dict[str, Any]] = []
    tool_names_by_call_id: dict[str, str] = {}

    try:
        yield _sse({"type": "thinking"})

        async with agent.iter(
            user_message,
            message_history=message_history,
            model_settings=OpenRouterModelSettings(openrouter_reasoning={"effort": "low"}),
        ) as run:
            async for node in run:
                if PydanticAgent.is_model_request_node(node):
                    async with node.stream(run.ctx) as stream:
                        async for chunk_text in stream.stream_text(delta=True, debounce_by=0.01):
                            assistant_message += chunk_text
                            yield _sse({"type": "content", "content": chunk_text})
                elif PydanticAgent.is_call_tools_node(node):
                    for part in node.model_response.parts:
                        if not isinstance(part, ToolCallPart):
                            continue
                        tool_names_by_call_id[part.tool_call_id] = part.tool_name
                        yield _sse(
                            {
                                "type": "tool_call_start",
                                "tool": part.tool_name,
                                "tool_call_id": part.tool_call_id,
                            }
                        )
                        if part.tool_name in {"show_listings", "show_market_trend"}:
                            yield _sse(
                                {
                                    "type": "artifact_opened",
                                    "artifact": _artifact_shell(
                                        part.tool_name, part.tool_call_id, part.args_as_dict()
                                    ),
                                }
                            )
                        artifact = await _fetch_artifact(
                            db, part.tool_name, part.tool_call_id, part.args_as_dict()
                        )
                        if artifact is not None:
                            artifacts = [item for item in artifacts if item["id"] != artifact["id"]]
                            artifacts.append(artifact)
                            yield _sse({"type": "artifact_updated", "artifact": artifact})

                    async with node.stream(run.ctx) as tool_stream:
                        async for event in tool_stream:
                            if isinstance(event, FunctionToolResultEvent):
                                tool_call_id = getattr(event.result, "tool_call_id", "")
                                tool_name = getattr(event.result, "tool_name", None)
                                yield _sse(
                                    {
                                        "type": "tool_call_result",
                                        "tool_call_id": tool_call_id,
                                        "tool": tool_name
                                        or tool_names_by_call_id.get(tool_call_id, "tool"),
                                    }
                                )

            usage = run.usage()
            total_tokens = getattr(usage, "total_tokens", 0)
            prompt_tokens = getattr(usage, "request_tokens", 0)
            completion_tokens = getattr(usage, "response_tokens", 0)

            if total_tokens:
                logger.info(
                    f"Token usage: prompt={prompt_tokens}, "
                    f"completion={completion_tokens}, "
                    f"total={total_tokens}"
                )

                await token_usage_service.record_usage(
                    db=db,
                    user_id=user_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )

        # Save assistant message with metadata
        if assistant_message or artifacts:
            meta_data = {}
            if total_tokens:
                meta_data["total_tokens"] = total_tokens
            if artifacts:
                meta_data["artifacts"] = artifacts
            if not assistant_message:
                assistant_message = "I added the requested view below."

            await add_message(db, conversation_id, "assistant", assistant_message, meta_data)

        yield _sse({"type": "done"})

    except Exception as e:
        logger.exception("Error during chat streaming")
        yield _sse({"type": "error", "error": str(e)})
