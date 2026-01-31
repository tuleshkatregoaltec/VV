from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class OrganizationListResponse(BaseModel):
    """Response for listing organizations (system admin)"""

    id: str
    name: str
    owner_email: str
    user_count: int
    subscription_status: str
    seats: int
    created_at: datetime


class OrganizationMemberResponse(BaseModel):
    """Response for organization member details"""

    id: str
    email: str
    first_name: str
    last_name: str
    role: str
    joined_at: datetime


class UserDetailResponse(BaseModel):
    """Response for user details (system admin)"""

    id: str
    email: str
    first_name: str
    last_name: str
    organization_id: Optional[str]
    organization_name: Optional[str]
    role: str
    daily_token_limit: int


class UpdateUserRequest(BaseModel):
    """Request to update user (system admin)"""

    daily_token_limit: Optional[int] = None
