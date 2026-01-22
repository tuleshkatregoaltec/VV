from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.postgres import get_db_session
from app.routers.dependencies import require_auth
from app.providers.auth.platform_user import PlatformUser
from app.postgres.models.auth import Organization
from app.schemas.stripe import PaymentSyncResponse

router = APIRouter(prefix="/api/v1/stripe", tags=["stripe"])


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

    if current_user.id not in organization.users:
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
