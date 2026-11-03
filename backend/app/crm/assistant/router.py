import logging

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.dependencies import AuthContext, require_active_subscription, require_token_quota
from app.crm.assistant.actions import cancel_action, confirm_action
from app.crm.assistant.deps import AssistantDeps
from app.crm.assistant.models import (
    ActionEdits,
    AssistantActionResult,
    AssistantConversationListResponse,
    AssistantConversationResponse,
    AssistantMessageRequest,
    AssistantMessageResponse,
    AssistantTranscriptResponse,
    CreateAssistantConversationRequest,
    UpdateAssistantConversationRequest,
    encode_sse,
)
from app.crm.assistant.service import (
    create_conversation,
    delete_conversation,
    get_conversation,
    get_messages_with_action_status,
    list_conversations,
    rename_conversation,
    stream_assistant_response,
)
from app.crm.assistant.voice import MAX_AUDIO_BYTES, InvalidAudio, transcribe
from app.postgres import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/crm/assistant", tags=["crm-assistant"])


def _auth_ids(context: AuthContext) -> tuple[str, str]:
    return str(context.user.id), str(context.organization.id)


@router.post("/conversations", response_model=AssistantConversationResponse)
async def create_assistant_conversation(
    request: CreateAssistantConversationRequest,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    conversation = await create_conversation(db, user_id, organization_id, request.title)
    return AssistantConversationResponse.model_validate(conversation)


@router.get("/conversations", response_model=AssistantConversationListResponse)
async def list_assistant_conversations(
    context: AuthContext = Depends(require_active_subscription),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    conversations = await list_conversations(db, user_id, organization_id, limit, offset)
    return AssistantConversationListResponse(
        conversations=[AssistantConversationResponse.model_validate(c) for c in conversations],
        total=len(conversations),
    )


@router.patch("/conversations/{conversation_id}", response_model=AssistantConversationResponse)
async def rename_assistant_conversation(
    conversation_id: int,
    request: UpdateAssistantConversationRequest,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    conversation = await rename_conversation(
        db, conversation_id, user_id, organization_id, request.title
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return AssistantConversationResponse.model_validate(conversation)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_assistant_conversation(
    conversation_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    if not await delete_conversation(db, conversation_id, user_id, organization_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.get(
    "/conversations/{conversation_id}/messages", response_model=list[AssistantMessageResponse]
)
async def list_assistant_messages(
    conversation_id: int,
    context: AuthContext = Depends(require_active_subscription),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    if not await get_conversation(db, conversation_id, user_id, organization_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await get_messages_with_action_status(
        db, conversation_id, user_id, organization_id, limit
    )


@router.post("/conversations/{conversation_id}/messages/stream", response_class=StreamingResponse)
async def send_assistant_message(
    conversation_id: int,
    request: AssistantMessageRequest,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_token_quota),
):
    """Send a message and stream the assistant's reply via SSE."""
    deps = AssistantDeps.from_auth(context, db)

    async def event_stream():
        try:
            async for chunk in stream_assistant_response(
                db, conversation_id=conversation_id, user_message=request.message, deps=deps
            ):
                yield chunk
        except Exception as error:
            logger.error(
                "assistant endpoint failed conversation=%s error=%s",
                conversation_id,
                type(error).__name__,
            )
            yield encode_sse({"type": "error", "error": "Something went wrong"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/transcribe", response_model=AssistantTranscriptResponse)
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
    return AssistantTranscriptResponse(text=text)


@router.post("/actions/{action_id}/confirm", response_model=AssistantActionResult)
async def confirm_assistant_action(
    action_id: str,
    edits: ActionEdits | None = Body(default=None, embed=True),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Run a change the assistant proposed, after re-checking it belongs to the signed-in user.
    An email card can send the agent's edited subject and message as `edits`."""
    return await confirm_action(
        AssistantDeps.from_auth(context, db), action_id=action_id, edits=edits
    )


@router.post("/actions/{action_id}/cancel", response_model=AssistantActionResult)
async def cancel_assistant_action(
    action_id: str,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await cancel_action(AssistantDeps.from_auth(context, db), action_id=action_id)
