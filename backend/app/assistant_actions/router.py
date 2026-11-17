from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from app.assistant_actions import service
from app.assistant_actions.models import (
    ActionProposalRequest,
    ActionProposalResponse,
    ListingDraftResponse,
    ReminderResponse,
    ViewingResponse,
)
from app.core.dependencies import AuthContext, require_active_subscription
from app.postgres import get_db_session

router = APIRouter(prefix="/api/v1/assistant/actions", tags=["Assistant actions"])


def _identity(context):
    return {"user_id": str(context.user.id), "organization_id": str(context.organization.id)}


@router.post("/proposals", response_model=ActionProposalResponse)
async def propose_action(
    request: ActionProposalRequest,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.propose_action(db, **_identity(context), request=request)


@router.get("/proposals", response_model=list[ActionProposalResponse])
async def list_actions(
    conversation_id: int = Query(gt=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.list_actions(db, **_identity(context), conversation_id=conversation_id)


@router.get("/reminders", response_model=list[ReminderResponse])
async def list_reminders(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.list_reminders(db, **_identity(context))


@router.get("/viewings", response_model=list[ViewingResponse])
async def list_viewings(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.list_viewings(db, **_identity(context))


@router.get("/listing-drafts", response_model=list[ListingDraftResponse])
async def list_listing_drafts(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.list_listing_drafts(db, **_identity(context))


@router.get("/{action_id}", response_model=ActionProposalResponse)
async def get_action(
    action_id: str,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.get_action(db, **_identity(context), action_id=action_id)


@router.post("/{action_id}/confirm", response_model=ActionProposalResponse)
async def confirm_action(
    action_id: str,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.confirm_action(db, **_identity(context), action_id=action_id)


@router.post("/{action_id}/cancel", response_model=ActionProposalResponse)
async def cancel_action(
    action_id: str,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.cancel_action(db, **_identity(context), action_id=action_id)
