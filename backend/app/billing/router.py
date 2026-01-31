from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel

from app.postgres import get_db_session
from app.core.dependencies import require_auth
from app.providers.auth.platform_user import PlatformUser
from app.auth.service import update_user_profile_metadata
from app.billing.models import (
    CheckoutSessionRequest,
    CheckoutSessionResponse,
)
from app.billing.service import create_checkout_session, sync_after_checkout

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.post("/create-checkout", response_model=CheckoutSessionResponse)
async def create_checkout_session_endpoint(
    request: CheckoutSessionRequest,
    current_user: PlatformUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db_session),
):
    """Create Stripe checkout session for organization subscription."""
    try:
        await update_user_profile_metadata(
            current_user.id,
            request.first_name,
            request.last_name,
        )

        result = await create_checkout_session(
            user_id=current_user.id,
            email=current_user.email,
            organization_name=request.organization_name,
            seats=request.seats,
            first_name=request.first_name,
            last_name=request.last_name,
            price_tier=request.price_tier,
            db=db,
        )
        return CheckoutSessionResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class SyncAfterCheckoutRequest(BaseModel):
    """Request to sync after checkout"""

    session_id: str


@router.post("/sync-after-checkout")
async def sync_after_checkout_endpoint(
    request: SyncAfterCheckoutRequest,
    current_user: PlatformUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db_session),
):
    """Eager sync after checkout success."""
    result = await sync_after_checkout(
        session_id=request.session_id,
        user_id=current_user.id,
        db=db,
    )
    return result
