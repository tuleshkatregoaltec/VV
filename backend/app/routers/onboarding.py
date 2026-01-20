from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.db.session import get_db_session
from app.routers.dependencies import require_auth
from app.providers.auth.platform_user import PlatformUser
from app.schemas.onboarding import (
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    CompleteProfileRequest,
    PaymentStatusResponse,
)
from app.services.stripe_service import create_checkout_session
from app.db.models.auth import Organization

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])


@router.post("/checkout", response_model=CheckoutSessionResponse)
async def create_checkout_session_endpoint(
    request: CheckoutSessionRequest,
    current_user: PlatformUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db_session),
):
    """Create Stripe checkout session for organization subscription."""
    try:
        result = await create_checkout_session(
            user_id=current_user.id,
            email=current_user.email,
            organization_name=request.organization_name,
            seats=request.seats,
            db=db,
        )
        return CheckoutSessionResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/complete-profile")
async def complete_profile_setup(
    request: CompleteProfileRequest,
    current_user: PlatformUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db_session),
):
    """Add invited user to organization."""
    stmt = select(Organization).where(Organization.id == request.organization_id)
    result = await db.execute(stmt)
    organization = result.scalar_one_or_none()

    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    if current_user.id not in organization.users:
        organization.users.append(current_user.id)
        await db.commit()

    return {"success": True}


@router.get("/check-payment-status/{session_id}", response_model=PaymentStatusResponse)
async def check_payment_status(
    session_id: str,
    current_user: PlatformUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db_session),
):
    """Check if Stripe payment completed and organization created."""
    stmt = select(Organization).where(
        Organization.stripe_checkout_session_id == session_id
    )
    result = await db.execute(stmt)
    organization = result.scalar_one_or_none()

    if not organization:
        return PaymentStatusResponse(status="failed", organization_id=None)

    if organization.status == "active":
        return PaymentStatusResponse(
            status="completed", organization_id=organization.id
        )
    elif organization.status == "pending_payment":
        return PaymentStatusResponse(status="pending", organization_id=None)
    else:
        return PaymentStatusResponse(status="failed", organization_id=None)
