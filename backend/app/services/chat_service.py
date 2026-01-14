"""Chat Service - Core business logic for conversations, messages, and AI interactions."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from openai import AsyncOpenAI
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.core.cache import RedisCache
from app.db.models.chat import Conversation, Message, ToolCallResult
from app.services.mcp_service import mcp_registry

logger = logging.getLogger(__name__)
cache = RedisCache(settings.REDIS_URL)


class ChatService:
    """Service for managing conversations and AI chat interactions"""

    # Conversation Management

    async def create_conversation(
        self, db: AsyncSession, user_id: str, title: Optional[str] = None
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
        self, db: AsyncSession, user_id: str, limit: int = 50, offset: int = 0
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
        self, db: AsyncSession, conversation_id: int, user_id: str
    ) -> Optional[Conversation]:
        """Get a conversation by ID (with auth check)"""
        stmt = select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
        result = await db.exec(stmt)
        return result.first()

    async def update_conversation(
        self, db: AsyncSession, conversation_id: int, user_id: str, title: str
    ) -> Optional[Conversation]:
        """Update a conversation's title"""
        conversation = await self.get_conversation(db, conversation_id, user_id)
        if not conversation:
            return None

        conversation.title = title
        conversation.updated_at = datetime.now(timezone.utc)
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        return conversation

    async def delete_conversation(
        self, db: AsyncSession, conversation_id: int, user_id: str
    ) -> bool:
        """Delete a conversation and all its messages"""
        conversation = await self.get_conversation(db, conversation_id, user_id)
        if not conversation:
            return False

        await db.delete(conversation)
        await db.commit()
        return True

    async def get_conversation_messages(
        self, db: AsyncSession, conversation_id: int, limit: int = 100
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

    # Message & Chat Logic

    async def add_message(
        self, db: AsyncSession, conversation_id: int, role: str, content: str
    ) -> Message:
        """Add a message to a conversation"""
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
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

    async def _build_context(
        self, db: AsyncSession, conversation_id: int, new_user_message: str
    ) -> List[Dict[str, str]]:
        """Build conversation context"""

        # Get conversation history
        messages = await self.get_conversation_messages(db, conversation_id)

        # Convert to OpenAI format
        context = []

        # System prompt
        context.append(
            {
                "role": "system",
                "content": (
                    "You are a helpful AI assistant for Vitevue, a real estate analytics platform. "
                    "You have access to comprehensive Dubai real estate data including sales transactions, "
                    "rental contracts, developer information, and project details. "
                    "Use the available tools to answer user questions with accurate, data-driven insights. "
                    "Always cite specific numbers and trends when using tool results.\n\n"
                    "IMPORTANT DATA STRUCTURE NOTES:\n"
                    "- Sales transactions: Bedroom data in 'rooms' field (Studio, 1 B/R, 2 B/R, 3 B/R, etc.)\n"
                    '- Rental contracts: Bedroom data in \'property_sub_type\' field ("2 bed rooms+hall", "3 bed rooms+hall", "Studio", etc.)\n'
                    "- get_sales_analytics: Supports bedroom filtering via 'rooms' parameter\n"
                    "- get_rental_analytics: Does NOT support bedroom filtering (use search_rental_contracts instead)\n"
                    "- search_rental_contracts: Use 'property_sub_type' parameter for bedroom-specific rentals (e.g., \"2 bed rooms+hall\")\n"
                    "- Both sales and rentals support: property_type, master_project, area ranges, and price/rent buckets\n\n"
                    "SUPPLY/PROJECT TOOLS:\n"
                    "- search_active_projects: Search active projects with flexible filters\n"
                    "  * Use 'timeframe' parameter for date-based queries (upcoming, overdue, 3m, 6m, 12m, all)\n"
                    "  * Use 'developer_name' or 'area_name' for location/developer filtering (partial case-insensitive match)\n"
                    "  * Use 'min_progress' and 'max_progress' for completion percentage filtering (0-100)\n"
                    "  * Combine multiple filters for complex queries (e.g., developer_name='Emaar', timeframe='6m', min_progress=50)\n"
                    "  * Returns project details including name, developer, area, progress, dates, buildings, and units"
                ),
            }
        )

        # Historical messages
        for msg in messages:
            context.append({"role": msg.role, "content": msg.content})

        # Add new user message
        context.append({"role": "user", "content": new_user_message})

        return context

    async def _get_tool_call_cache_key(
        self, conversation_id: int, tool_name: str, arguments: Dict[str, Any]
    ) -> str:
        """Generate cache key for tool call result"""
        # Sort arguments for consistent cache keys
        sorted_args = json.dumps(arguments, sort_keys=True)
        return f"tool_call:{conversation_id}:{tool_name}:{sorted_args}"

    async def _execute_tool_with_cache(
        self, conversation_id: int, tool_name: str, arguments: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], bool]:
        """Execute tool with per-conversation caching"""
        cache_key = await self._get_tool_call_cache_key(
            conversation_id, tool_name, arguments
        )

        # Check cache
        cached_result = await cache.get(cache_key)
        if cached_result:
            logger.info(f"Tool call cache hit: {tool_name}")
            return cached_result, True

        # Execute tool
        logger.info(f"Executing tool: {tool_name} with args: {arguments}")
        result = await mcp_registry.execute_tool(tool_name, arguments)

        # Cache for 10 minutes (per conversation)
        await cache.set(cache_key, result, expire=600)

        return result, False

    async def stream_chat_response(
        self, db: AsyncSession, conversation_id: int, user_message: str, user_id: str
    ) -> AsyncGenerator[str, None]:
        """Stream chat response with tool calling support via SSE"""

        # Verify conversation ownership
        conversation = await self.get_conversation(db, conversation_id, user_id)
        if not conversation:
            yield f"data: {json.dumps({'type': 'error', 'error': 'Conversation not found'})}\n\n"
            return

        # Save user message
        await self.add_message(db, conversation_id, "user", user_message)

        # Build context
        context = await self._build_context(db, conversation_id, user_message)

        # Start streaming from OpenRouter
        async with AsyncOpenAI(
            base_url=settings.OPENROUTER_BASE_URL, api_key=settings.OPENROUTER_API_KEY
        ) as client:
            # Track assistant response and tool calls
            assistant_message = ""
            tool_calls_made = []

            try:
                # Get available tools
                tools = await mcp_registry.get_tools_for_llm()

                # Loop to handle tool calls and continuations
                while True:
                    # Make LLM call
                    stream = await client.chat.completions.create(
                        model=settings.CHAT_MODEL,
                        messages=context,
                        tools=tools if tools else None,
                        stream=True,
                    )

                    tool_call_id = None
                    tool_name = None
                    tool_args = ""
                    current_tool_call_index = None
                    made_tool_call = False

                    async for chunk in stream:
                        if not chunk.choices:
                            continue

                        delta = chunk.choices[0].delta
                        finish_reason = chunk.choices[0].finish_reason

                        # Handle content streaming
                        if delta.content:
                            assistant_message += delta.content
                            yield f"data: {json.dumps({'type': 'content', 'content': delta.content})}\n\n"

                        # Handle tool calls
                        if delta.tool_calls:
                            for tool_call in delta.tool_calls:
                                if tool_call.index != current_tool_call_index:
                                    current_tool_call_index = tool_call.index

                                if tool_call.function and tool_call.function.name:
                                    tool_name = tool_call.function.name
                                    tool_call_id = tool_call.id
                                    tool_args = ""
                                    yield f"data: {json.dumps({'type': 'tool_call_start', 'tool': tool_name})}\n\n"

                                if tool_call.function and tool_call.function.arguments:
                                    tool_args += tool_call.function.arguments

                        # When tool call complete
                        if finish_reason == "tool_calls" and tool_name and tool_args:
                            # Parse arguments
                            try:
                                args = json.loads(tool_args)
                            except json.JSONDecodeError:
                                logger.error(
                                    f"Failed to parse tool arguments: {tool_args}"
                                )
                                yield f"data: {json.dumps({'type': 'error', 'error': 'Failed to parse tool arguments'})}\n\n"
                                continue

                            # Execute tool with caching
                            start_time = datetime.now(timezone.utc)
                            result, cached = await self._execute_tool_with_cache(
                                conversation_id, tool_name, args
                            )
                            execution_time = int(
                                (
                                    datetime.now(timezone.utc) - start_time
                                ).total_seconds()
                                * 1000
                            )

                            # Save tool call result
                            tool_call_result = ToolCallResult(
                                conversation_id=conversation_id,
                                message_id=None,  # Will update after message save
                                tool_name=tool_name,
                                tool_args=args,
                                result=result,
                                execution_time_ms=execution_time,
                                cached=cached,
                                created_at=datetime.now(timezone.utc),
                            )
                            db.add(tool_call_result)
                            await db.commit()
                            await db.refresh(tool_call_result)

                            tool_calls_made.append(tool_call_result.id)

                            # Send tool result to user
                            yield f"data: {json.dumps({'type': 'tool_call_result', 'tool': tool_name, 'cached': cached})}\n\n"

                            # Continue conversation with tool result
                            context.append(
                                {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": tool_call_id or "call_0",
                                            "type": "function",
                                            "function": {
                                                "name": tool_name,
                                                "arguments": json.dumps(args),
                                            },
                                        }
                                    ],
                                }
                            )
                            context.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call_id or "call_0",
                                    "content": json.dumps(result),
                                }
                            )

                            made_tool_call = True

                    # If no tool call was made, we're done
                    if not made_tool_call:
                        break

                # Save assistant message
                if assistant_message:
                    assistant_msg = await self.add_message(
                        db, conversation_id, "assistant", assistant_message
                    )

                    # Update tool call message IDs
                    if tool_calls_made:
                        assistant_msg.tool_call_ids = tool_calls_made
                        await db.commit()

                yield f"data: {json.dumps({'type': 'done'})}\n\n"

            except Exception as e:
                logger.exception("Error during chat streaming")
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"


# Global service instance
chat_service = ChatService()
