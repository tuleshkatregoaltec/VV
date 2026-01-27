from typing import LiteralString, Optional
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime


class Subscription(SQLModel, table=True):
    """Stripe subscription model for per-seat billing"""

    __tablename__: LiteralString = "subscriptions"

    # Primary key
    id: str = Field(primary_key=True)  # UUID

    # Foreign keys
    organization_id: str = Field(foreign_key="organizations.id", index=True)

    # Stripe identifiers
    stripe_subscription_id: str = Field(unique=True, index=True)
    stripe_customer_id: str
    stripe_price_id: str  # Tier 1 or Tier 2 price ID

    # Subscription details
    status: str  # "active", "canceled", "past_due", "incomplete"
    seats: int
    current_period_start: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    current_period_end: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    cancel_at_period_end: bool = Field(default=False)

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )


from pydantic import BaseModel, Field


class CheckoutSessionRequest(BaseModel):
    """Request to create a Stripe checkout session"""

    organization_name: str = Field(min_length=1, max_length=100)
    seats: int = Field(ge=1, le=100)


class CheckoutSessionResponse(BaseModel):
    """Response containing Stripe checkout URL"""

    checkout_url: str
    session_id: str


class PaymentStatusResponse(BaseModel):
    """Response for payment status check"""

    status: str  # "pending", "completed", "failed"
    organization_id: str | None = None


class PaymentSyncResponse(BaseModel):
    """Payment sync response"""

    payment_completed: bool
    organization_id: str | None
    organization_status: str | None
    message: str


class SubscriptionResponse(BaseModel):
    """Response containing subscription details"""

    id: str
    organization_id: str
    status: str
    seats: int
    current_period_end: datetime
    cancel_at_period_end: bool
    current_members: int
    available_seats: int
    excess_users: int
    within_paid_period: bool


class CustomerPortalResponse(BaseModel):
    """Response containing Stripe Customer Portal URL"""

    url: str
