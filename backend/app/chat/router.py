"""The conversation API every chat product shares (CRM Operations Assistant and Market AI):
list, create, rename, delete, read messages and transcribe a voice message. Each product
streams its own answers from its own endpoint."""

import logging
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat.conversations import (
    create_conversation,
    delete_conversation,
    get_conversation,
    get_user_conversations,
    update_conversation,
)
from app.chat.models import (
    ChatAssistant,
    ConversationListResponse,
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
    TranscriptResponse,
    UpdateConversationRequest,
)
from app.chat.voice import MAX_AUDIO_BYTES, InvalidAudio, transcribe
from app.core.dependencies import (
    AuthContext,
    require_active_subscription,
    require_token_quota,
)
from app.crm.assistant.service import get_conversation_messages
from app.postgres import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/chat",
    tags=["chat"],
)


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation_endpoint(
    request: CreateConversationRequest,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new conversation"""
    conversation = await create_conversation(
        db=db,
        user_id=context.user.id,
        organization_id=context.organization.id,
        title=request.title,
        assistant=request.assistant,
    )
    return ConversationResponse.model_validate(conversation)


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    context: AuthContext = Depends(require_active_subscription),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    assistant: ChatAssistant = Query(default="crm"),
    db: AsyncSession = Depends(get_db_session),
):
    """Get the current user's conversations with one assistant (the CRM assistant by default)"""
    conversations = await get_user_conversations(
        db=db,
        user_id=context.user.id,
        organization_id=context.organization.id,
        limit=limit,
        offset=offset,
        assistant=assistant,
    )
    return ConversationListResponse(
        conversations=[ConversationResponse.model_validate(c) for c in conversations],
        total=len(conversations),
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation_endpoint(
    conversation_id: int,
    request: UpdateConversationRequest,
    assistant: ChatAssistant = Query(default="crm"),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Update a conversation's title"""
    conversation = await update_conversation(
        db=db,
        conversation_id=conversation_id,
        user_id=context.user.id,
        organization_id=context.organization.id,
        title=request.title,
        assistant=assistant,
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationResponse.model_validate(conversation)


@router.post("/transcribe", response_model=TranscriptResponse)
async def transcribe_voice_message(
    audio: UploadFile = File(...),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_token_quota),
):
    """Turn the agent's recording (16 kHz mono WAV) into text for them to check before sending.
    Nothing is stored and nothing is sent to the assistant."""
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    try:
        text = await transcribe(db, user_id=str(context.user.id), audio=data)
    except InvalidAudio as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except Exception as error:
        # Only the error type: provider messages can carry what was said.
        logger.error(
            "assistant transcribe failed org=%s error=%s",
            context.organization.id,
            type(error).__name__,
        )
        raise HTTPException(
            status_code=502, detail="Could not turn your voice into text."
        ) from None
    return TranscriptResponse(text=text)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation_endpoint(
    conversation_id: int,
    assistant: ChatAssistant = Query(default="crm"),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Delete a conversation"""
    success = await delete_conversation(
        db=db,
        conversation_id=conversation_id,
        user_id=context.user.id,
        organization_id=context.organization.id,
        assistant=assistant,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_conversation_messages_endpoint(
    conversation_id: int,
    context: AuthContext = Depends(require_active_subscription),
    limit: int = Query(default=100, ge=1, le=100),
    before_id: int | None = Query(default=None, ge=1),
    assistant: ChatAssistant = Query(default="crm"),
    db: AsyncSession = Depends(get_db_session),
):
    """Get messages for a conversation (only that assistant's, when `assistant` is given)"""
    # Verify ownership
    conversation = await get_conversation(
        db, conversation_id, context.user.id, context.organization.id, assistant=assistant
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await get_conversation_messages(
        db=db,
        conversation_id=conversation_id,
        user_id=context.user.id,
        organization_id=context.organization.id,
        limit=limit,
        before_id=before_id,
    )
    return [MessageResponse.model_validate(m) for m in messages]
