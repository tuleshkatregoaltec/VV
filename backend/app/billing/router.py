from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.postgres import get_db_session
from app.core.dependencies import require_auth
from app.providers.auth.platform_user import PlatformUser
from app.postgres.models import Organization
from app.organization.models import OrganizationMembership
from app.schemas.stripe import PaymentSyncResponse
from app.billing.models import (
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    PaymentStatusResponse,
)
from app.billing.service import create_checkout_session

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.get("/sync", response_model=PaymentSyncResponse)
async def sync_payment_status(
    session_id: str,
    current_user: PlatformUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db_session),
):
    """Check if payment processed and organization is ready."""
    stmt = select(Organization).where(
        Organization.stripe_checkout_session_id == session_id
    )
    result = await db.execute(stmt)
    organization = result.scalar_one_or_none()

    if not organization:
        raise HTTPException(
            status_code=404,
            detail="Organization not found for this checkout session. Please contact support.",
        )

    # Check if user is a member of this organization
    membership_result = await db.exec(
        select(OrganizationMembership)
        .where(OrganizationMembership.organization_id == organization.id)
        .where(OrganizationMembership.user_id == current_user.id)
    )
    membership = membership_result.first()

    if not membership:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to access this organization.",
        )

    if organization.status == "active":
        return PaymentSyncResponse(
            payment_completed=True,
            organization_id=organization.id,
            organization_status="active",
            message="Payment processed successfully. Organization is active.",
        )
    elif organization.status == "pending_payment":
        return PaymentSyncResponse(
            payment_completed=True,
            organization_id=None,
            organization_status="pending_payment",
            message="Payment confirmed. Processing your organization... Please wait.",
        )
    else:
        return PaymentSyncResponse(
            payment_completed=False,
            organization_id=None,
            organization_status=organization.status,
            message=f"Organization status: {organization.status}. Please contact support if this persists.",
        )


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


@router.get("/payment-status/{session_id}", response_model=PaymentStatusResponse)
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
