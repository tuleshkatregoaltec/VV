"""lead team ownership, shared team pool and timed rotation

Revision ID: e8b4d2f6a1c3
Revises: d2a6e8c4b1f7
Create Date: 2026-11-13 12:00:00.000000

Backfill (conservative, nothing guessed): an existing lead gets a team only when its current
assignee belongs to exactly one team of its organization. Every other existing lead keeps no team,
so only organization administrators and its assignee can see it until someone assigns it again.
No lead is put in a shared pool by this migration.
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "e8b4d2f6a1c3"
down_revision: Union[str, Sequence[str], None] = "d2a6e8c4b1f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STR = sqlmodel.sql.sqltypes.AutoString()
_OLD_REASONS = "'created', 'import_agent', 'import_rule', 'manual', 'approved_from_inbox'"
_NEW_REASONS = _OLD_REASONS + ", 'released', 'claimed', 'rotation'"


def upgrade() -> None:
    op.add_column("crm_inbound_enquiries", sa.Column("team_id", _STR, nullable=True))
    op.add_column(
        "crm_inbound_enquiries",
        sa.Column("pool_released_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_crm_inbound_enquiries_team_id"), "crm_inbound_enquiries", ["team_id"])
    op.create_foreign_key(
        "fk_crm_inbound_enquiry_team",
        "crm_inbound_enquiries",
        "organization_teams",
        ["team_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_crm_inbound_enquiry_pool",
        "crm_inbound_enquiries",
        "pool_released_at IS NULL OR (team_id IS NOT NULL AND assigned_user_id IS NULL)",
    )
    op.execute(
        """
        UPDATE crm_inbound_enquiries AS lead
        SET team_id = only_team.team_id
        FROM (
            SELECT organization_id, user_id, MIN(team_id) AS team_id
            FROM organization_team_members
            GROUP BY organization_id, user_id
            HAVING COUNT(*) = 1
        ) AS only_team
        WHERE lead.team_id IS NULL
          AND lead.assigned_user_id = only_team.user_id
          AND lead.organization_id = only_team.organization_id
        """
    )

    op.add_column("crm_inbound_assignment_events", sa.Column("team_id", _STR, nullable=True))
    op.drop_constraint(
        "ck_crm_inbound_assignment_event_reason", "crm_inbound_assignment_events", type_="check"
    )
    op.create_check_constraint(
        "ck_crm_inbound_assignment_event_reason",
        "crm_inbound_assignment_events",
        f"reason IN ({_NEW_REASONS})",
    )

    op.add_column(
        "crm_routing_rules",
        sa.Column("rotation_user_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column("crm_routing_rules", sa.Column("rotation_minutes", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_crm_routing_rule_rotation_minutes",
        "crm_routing_rules",
        "rotation_minutes IS NULL OR rotation_minutes BETWEEN 1 AND 10080",
    )

    op.create_table(
        "crm_lead_rotations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", _STR, nullable=False),
        sa.Column("enquiry_id", sa.Integer(), nullable=False),
        sa.Column("team_id", _STR, nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("rule_revision", sa.Integer(), nullable=True),
        sa.Column("user_ids", sa.JSON(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("timeout_minutes", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assignment_revision", sa.Integer(), nullable=False),
        sa.Column("status", _STR, nullable=False),
        sa.Column("stop_reason", _STR, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'stopped', 'finished')", name="ck_crm_lead_rotation_status"
        ),
        sa.ForeignKeyConstraint(["enquiry_id"], ["crm_inbound_enquiries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["organization_teams.id", "organization_teams.organization_id"],
            name="fk_crm_lead_rotation_team",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("enquiry_id"),
    )
    op.create_index(
        op.f("ix_crm_lead_rotations_organization_id"), "crm_lead_rotations", ["organization_id"]
    )
    op.create_index(
        "ix_crm_lead_rotations_due",
        "crm_lead_rotations",
        ["due_at"],
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_table("crm_lead_rotations")
    op.drop_constraint("ck_crm_routing_rule_rotation_minutes", "crm_routing_rules", type_="check")
    op.drop_column("crm_routing_rules", "rotation_minutes")
    op.drop_column("crm_routing_rules", "rotation_user_ids")
    # The old schema cannot hold these reasons, and relabelling them would falsify the history, so
    # downgrading deletes that history. Back up crm_inbound_assignment_events first if it matters.
    op.execute(
        "DELETE FROM crm_inbound_assignment_events "
        "WHERE reason IN ('released', 'claimed', 'rotation')"
    )
    op.drop_constraint(
        "ck_crm_inbound_assignment_event_reason", "crm_inbound_assignment_events", type_="check"
    )
    op.create_check_constraint(
        "ck_crm_inbound_assignment_event_reason",
        "crm_inbound_assignment_events",
        f"reason IN ({_OLD_REASONS})",
    )
    op.drop_column("crm_inbound_assignment_events", "team_id")
    op.drop_constraint("ck_crm_inbound_enquiry_pool", "crm_inbound_enquiries", type_="check")
    op.drop_constraint("fk_crm_inbound_enquiry_team", "crm_inbound_enquiries", type_="foreignkey")
    op.drop_index(op.f("ix_crm_inbound_enquiries_team_id"), table_name="crm_inbound_enquiries")
    op.drop_column("crm_inbound_enquiries", "pool_released_at")
    op.drop_column("crm_inbound_enquiries", "team_id")
