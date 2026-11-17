from datetime import datetime, timezone
from enum import Enum
from typing import List, Literal, LiteralString, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, SQLModel


class Organization(SQLModel, table=True):
    """Organization model for multi-tenancy"""

    __tablename__: LiteralString = "organizations"

    # Primary key
    id: str = Field(primary_key=True)

    # Organization details
    name: str
    max_users: int = Field(default=5)

    # Payment and subscription tracking
    subscription_status: str = Field(
        default="pending"
    )  # "pending", "active", "past_due", "canceled", "failed", "none"

    # Stripe integration (one customer per org)
    stripe_customer_id: Optional[str] = Field(default=None, unique=True, index=True, nullable=True)
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
    # Granted by an owner: organization administration (teams, routing, assignment) without
    # billing ownership. Owners are always organization administrators.
    organization_admin: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )


class OrganizationTeam(SQLModel, table=True):
    """A group of organization members supervised by one or more managers."""

    __tablename__: LiteralString = "organization_teams"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_organization_team_name"),
        # Target of the composite keys that keep team rows inside one organization.
        UniqueConstraint("id", "organization_id", name="uq_organization_team_id_org"),
        ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_organization_team_organization",
            ondelete="CASCADE",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    organization_id: str = Field(index=True)
    name: str = Field(sa_column=Column(String(120), nullable=False))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )


class OrganizationTeamMember(SQLModel, table=True):
    """A member's place in a team: an agent or a supervising manager.

    Both keys are composite with the organization, so a team can only hold members of its own
    organization, and removing someone from the organization removes them from every team.
    """

    __tablename__: LiteralString = "organization_team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_organization_team_member"),
        CheckConstraint("role IN ('agent', 'supervisor')", name="ck_organization_team_member_role"),
        ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["organization_teams.id", "organization_teams.organization_id"],
            name="fk_organization_team_member_team",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            name="fk_organization_team_member_membership",
            ondelete="CASCADE",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    team_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    user_id: str = Field(index=True)
    role: str = Field(default="agent")
    created_at: datetime = Field(
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
    status: str = Field(default="pending")  # "pending", "accepted", "declined", "expired"
    invited_by_user_id: str
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
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
    owner_id: str


class OwnerOrganizationCreateRequest(BaseModel):
    """Request for owner to create organization during self-signup"""

    name: str = Field(min_length=1, max_length=100)
    max_users: int = Field(ge=1, le=1000)


class OwnerOrganizationCreateResponse(BaseModel):
    """Response after creating organization"""

    organization_id: str
    name: str
    max_users: int
    is_new: bool  # True if newly created, False if updated existing


class OrganizationUpdateRequest(BaseModel):
    max_users: int


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    max_users: int
    active_user_count: Optional[int] = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class OrganizationDetailResponse(BaseModel):
    organization: OrganizationResponse
    users: List["OrganizationUserDetailResponse"]


class InviteUserRequest(BaseModel):
    """Request to invite a user to an organization"""

    email: EmailStr


class InviteUserResponse(BaseModel):
    """Response after creating an organization invitation"""

    success: bool
    invitation_token: str


class OrganizationInvitationResponse(BaseModel):
    """Pending invitation response for organization settings."""

    id: str
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime


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


class OperationSuccessResponse(BaseModel):
    success: bool


class OrganizationUserDetailResponse(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    created_at: datetime | None
    last_login: datetime | None
    daily_token_limit: int
    tokens_used_today: int
    usage_percentage: float


class UserTokenLimitUpdateResponse(BaseModel):
    id: str
    email: str
    daily_token_limit: int
    updated_at: datetime | None


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


class OrganizationAdminUpdateRequest(BaseModel):
    """Grant or remove organization administration for a non-owner member (owner only)."""

    organization_admin: bool


class TeamWriteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TeamMemberInput(BaseModel):
    user_id: str = Field(min_length=1, max_length=200)
    role: Literal["agent", "supervisor"]


class TeamMembersUpdateRequest(BaseModel):
    """The complete membership of a team; members left out are removed."""

    members: List[TeamMemberInput] = Field(max_length=500)


class TeamMemberResponse(BaseModel):
    user_id: str
    name: str
    email: str
    role: Literal["agent", "supervisor"]


class TeamResponse(BaseModel):
    id: str
    name: str
    members: List[TeamMemberResponse]
    created_at: datetime
    updated_at: datetime


class TeamPersonResponse(BaseModel):
    """An organization member who can be placed in a team."""

    user_id: str
    name: str
    email: str
    role: str
    organization_admin: bool


class TeamsResponse(BaseModel):
    teams: List[TeamResponse]
    people: List[TeamPersonResponse]
