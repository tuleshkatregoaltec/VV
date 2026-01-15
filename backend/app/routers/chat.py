"""Chat API Router - Endpoints for conversation management and streaming chat."""

import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_db_session
from app.routers.dependencies import require_auth, require_token_quota
from app.schemas.chat import (
    ConversationListResponse,
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
    SendMessageRequest,
    UpdateConversationRequest,
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


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: int,
    request: UpdateConversationRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(require_auth),
):
    """Update a conversation's title"""
    conversation = await chat_service.update_conversation(
        db=db, conversation_id=conversation_id, user_id=current_user["id"], title=request.title
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationResponse.model_validate(conversation)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(require_auth),
):
    """Delete a conversation"""
    success = await chat_service.delete_conversation(
        db=db, conversation_id=conversation_id, user_id=current_user["id"]
    )
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")


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


@router.post("/conversations/{conversation_id}/messages/stream")
async def send_message(
    conversation_id: int,
    request: SendMessageRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(require_auth),
    _: None = Depends(require_token_quota),
):
    """Send a message and stream AI response via SSE"""

    async def event_stream():
        try:
            async for chunk in chat_service.stream_chat_response(
                db=db,
                conversation_id=conversation_id,
                user_message=request.message,
                user_id=current_user["id"],
                organization_id=current_user.get("organization_id"),
                organization_name=current_user.get("organization_name"),
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
