"""The CRM Operations Assistant's answer stream: the CRM-only coordinator and router."""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat.events import turn_stream_response
from app.chat.models import SendMessageRequest
from app.core.dependencies import (
    AuthContext,
    require_active_subscription,
    require_token_quota,
)
from app.crm.assistant.service import stream_chat_response
from app.postgres import get_db_session

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post(
    "/conversations/{conversation_id}/messages/stream",
    response_class=StreamingResponse,
)
async def send_message(
    conversation_id: int,
    request: SendMessageRequest,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_token_quota),
):
    """Send a message to the CRM Operations Assistant and stream its answer via SSE"""
    return turn_stream_response(
        stream_chat_response(
            db=db,
            conversation_id=conversation_id,
            user_message=request.message,
            user_id=context.user.id,
            organization_id=context.organization.id,
        ),
        context="CRM assistant endpoint",
    )
