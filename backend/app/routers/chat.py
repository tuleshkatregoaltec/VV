"""Chat API Router - Endpoints for conversation management and streaming chat."""

import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_db_session
from app.routers.dependencies import require_auth
from app.schemas.chat import (
    ConversationListResponse,
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
)
from app.services.chat_service import chat_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/chat",
    tags=["chat"],
    dependencies=[Depends(require_auth)],
)


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    request: CreateConversationRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(require_auth),
):
    """Create a new conversation"""
    conversation = await chat_service.create_conversation(
        db=db, user_id=current_user["id"], title=request.title
    )
    return ConversationResponse.model_validate(conversation)


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(require_auth),
):
    """Get all conversations for current user"""
    conversations = await chat_service.get_user_conversations(
        db=db, user_id=current_user["id"], limit=limit, offset=offset
    )
    return ConversationListResponse(
        conversations=[ConversationResponse.model_validate(c) for c in conversations],
        total=len(conversations),
    )


@router.get(
    "/conversations/{conversation_id}/messages", response_model=List[MessageResponse]
)
async def get_conversation_messages(
    conversation_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(require_auth),
):
    """Get messages for a conversation"""
    # Verify ownership
    conversation = await chat_service.get_conversation(
        db, conversation_id, current_user["id"]
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await chat_service.get_conversation_messages(
        db=db, conversation_id=conversation_id, limit=limit
    )
    return [MessageResponse.model_validate(m) for m in messages]


@router.get("/conversations/{conversation_id}/messages/stream")
async def send_message(
    conversation_id: int,
    message: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(require_auth),
):
    """Send a message and stream AI response via SSE"""

    async def event_stream():
        try:
            async for chunk in chat_service.stream_chat_response(
                db=db,
                conversation_id=conversation_id,
                user_message=message,
                user_id=current_user["id"],
            ):
                yield chunk
        except Exception:
            logger.exception("Error in send_message endpoint")
            yield f"data: {json.dumps({'type': 'error', 'error': 'Internal server error'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
