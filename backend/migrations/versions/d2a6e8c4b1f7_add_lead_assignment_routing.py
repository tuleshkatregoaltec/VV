"""teams, organization administrators, lead assignment history and routing rules

Revision ID: d2a6e8c4b1f7
Revises: c3e7a1f9d2b6
Create Date: 2026-11-12 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "d2a6e8c4b1f7"
down_revision: Union[str, Sequence[str], None] = "c3e7a1f9d2b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STR = sqlmodel.sql.sqltypes.AutoString()


def upgrade() -> None:
    op.add_column(
        "organization_memberships",
        sa.Column("organization_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "organization_teams",
        sa.Column("id", _STR, nullable=False),
        sa.Column("organization_id", _STR, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_organization_team_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_organization_team_id_org"),
        sa.UniqueConstraint("organization_id", "name", name="uq_organization_team_name"),
    )
    op.create_index(
        op.f("ix_organization_teams_organization_id"), "organization_teams", ["organization_id"]
    )

    op.create_table(
        "organization_team_members",
        sa.Column("id", _STR, nullable=False),
        sa.Column("team_id", _STR, nullable=False),
        sa.Column("organization_id", _STR, nullable=False),
        sa.Column("user_id", _STR, nullable=False),
        sa.Column("role", _STR, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('agent', 'supervisor')", name="ck_organization_team_member_role"
        ),
        sa.ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["organization_teams.id", "organization_teams.organization_id"],
            name="fk_organization_team_member_team",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            name="fk_organization_team_member_membership",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_organization_team_member"),
    )
    for column in ("team_id", "organization_id", "user_id"):
        op.create_index(
            op.f(f"ix_organization_team_members_{column}"), "organization_team_members", [column]
        )

    op.add_column(
        "crm_inbound_enquiries",
        sa.Column("assignment_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "crm_inbound_enquiries",
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "crm_inbound_assignment_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", _STR, nullable=False),
        sa.Column("enquiry_id", sa.Integer(), nullable=False),
        sa.Column("previous_user_id", _STR, nullable=True),
        sa.Column("assigned_user_id", _STR, nullable=True),
        sa.Column("actor_user_id", _STR, nullable=False),
        sa.Column("reason", _STR, nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("rule_revision", sa.Integer(), nullable=True),
        sa.Column("import_id", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reason IN ('created', 'import_agent', 'import_rule', 'manual', 'approved_from_inbox')",
            name="ck_crm_inbound_assignment_event_reason",
        ),
        sa.ForeignKeyConstraint(["enquiry_id"], ["crm_inbound_enquiries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "enquiry_id"):
        op.create_index(
            op.f(f"ix_crm_inbound_assignment_events_{column}"),
            "crm_inbound_assignment_events",
            [column],
        )

    op.create_table(
        "crm_routing_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", _STR, nullable=False),
        sa.Column("team_id", _STR, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("match_mode", _STR, nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("destination_user_id", _STR, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", _STR, nullable=False),
        sa.Column("updated_by_user_id", _STR, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("match_mode IN ('all', 'any')", name="ck_crm_routing_rule_match_mode"),
        sa.ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["organization_teams.id", "organization_teams.organization_id"],
            name="fk_crm_routing_rule_team",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "team_id"):
        op.create_index(op.f(f"ix_crm_routing_rules_{column}"), "crm_routing_rules", [column])


def downgrade() -> None:
    op.drop_table("crm_routing_rules")
    op.drop_table("crm_inbound_assignment_events")
    op.drop_column("crm_inbound_enquiries", "assigned_at")
    op.drop_column("crm_inbound_enquiries", "assignment_revision")
    op.drop_table("organization_team_members")
    op.drop_table("organization_teams")
    op.drop_column("organization_memberships", "organization_admin")
