from pydantic import BaseModel, Field, EmailStr
from typing import Optional


class CheckoutSessionRequest(BaseModel):
    """Request to create a Stripe checkout session"""

    organization_name: str = Field(min_length=1, max_length=100)
    seats: int = Field(ge=1, le=100)


class CheckoutSessionResponse(BaseModel):
    """Response containing Stripe checkout URL"""

    checkout_url: str
    session_id: str


class InviteUserRequest(BaseModel):
    """Request to invite a user to an organization"""

    email: EmailStr
    organization_id: str
    redirect_url: str


class CompleteProfileRequest(BaseModel):
    """Request to complete user profile after invitation"""

    organization_id: str


class PaymentStatusResponse(BaseModel):
    """Response for payment status check"""

    status: str  # "pending", "completed", "failed"
    organization_id: Optional[str] = None


class SyncUserResponse(BaseModel):
    """Response from /auth/sync endpoint"""

    success: bool
    organization_id: str
    is_active: bool
    role: str
