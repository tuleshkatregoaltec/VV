from typing import Optional, List, LiteralString
from datetime import datetime, timezone
from uuid import uuid4
from enum import Enum
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime, UniqueConstraint, CheckConstraint


class Organization(SQLModel, table=True):
    """Organization model for multi-tenancy"""

    __tablename__: LiteralString = "organizations"

    # Primary key
    id: str = Field(primary_key=True)

    # Organization details
    name: str
    max_users: int = Field(default=5)
    is_active: bool = Field(default=True)
    owner_user_id: str  # User ID of organization owner

    # Payment and subscription tracking
    subscription_status: str = Field(
        default="pending"
    )  # "pending", "active", "past_due", "canceled", "failed", "none"

    # Stripe integration (one customer per org)
    stripe_customer_id: Optional[str] = Field(
        default=None, unique=True, index=True, nullable=True
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )


class OrganizationMembership(SQLModel, table=True):
    """Organization membership model with single-org constraint"""

    __tablename__: LiteralString = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_membership_user_id"),
        UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
        CheckConstraint("role IN ('owner', 'member')", name="ck_membership_role"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    organization_id: str = Field(foreign_key="organizations.id", index=True)
    user_id: str = Field(index=True)
    role: str = Field(default="member")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )


class MembershipRole(str, Enum):
    """Membership role enumeration"""

    OWNER = "owner"
    MEMBER = "member"


class OrganizationInvitation(SQLModel, table=True):
    """Organization invitations - source of truth for invites"""

    __tablename__: LiteralString = "organization_invitations"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    organization_id: str = Field(foreign_key="organizations.id", index=True)
    email: str = Field(index=True)
    role: str = Field(default="member")  # "owner" or "member"
    token: str = Field(unique=True, index=True)
    status: str = Field(
        default="pending"
    )  # "pending", "accepted", "declined", "expired"
    invited_by_user_id: str
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    accepted_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class OrganizationCreateRequest(BaseModel):
    name: str
    max_users: int = 5


class OrganizationUpdateRequest(BaseModel):
    max_users: int
    is_active: bool


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    max_users: int
    is_active: bool
    active_user_count: Optional[int] = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class OrganizationDetailResponse(BaseModel):
    organization: OrganizationResponse
    users: List[dict]


class InviteUserRequest(BaseModel):
    """Request to invite a user to an organization"""

    email: EmailStr
    organization_id: str
    redirect_url: str


class CompleteProfileRequest(BaseModel):
    """Request to complete user profile after invitation"""

    organization_id: str


class MembershipResponse(BaseModel):
    """Organization membership response"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    user_id: str
    role: str
    created_at: datetime


class UserUpdateRequest(BaseModel):
    """Request to update user settings (admin only)"""

    daily_token_limit: Optional[int] = None


class ValidateInviteTokenResponse(BaseModel):
    """Response for validating invitation token"""

    organization_name: str
    organization_id: str
    role: str
    email: str
    expires_at: datetime
    status: str


class AcceptInviteRequest(BaseModel):
    """Request to accept invitation"""

    token: str


class AcceptInviteResponse(BaseModel):
    """Response for accepting invitation"""

    success: bool
    organization_id: str
    organization_name: str
    role: str


class InviteConflictResponse(BaseModel):
    """Response when user already has membership"""

    conflict: bool
    current_org_id: str
    current_org_name: str
    current_role: str
    member_count: int
    is_single_seat: bool
