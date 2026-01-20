from pydantic import BaseModel
from datetime import datetime


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
