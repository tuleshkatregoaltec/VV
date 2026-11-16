"""owner import requests get a processing lease; rotations remember whom they tried

Revision ID: b2d4f6a8c0e2
Revises: a7c9e1b3d5f2
Create Date: 2026-11-13 18:00:00.000000

A request whose import began more than the lease ago without finishing is treated as failed and
can be approved again, so a crash mid-import never leaves it "processing" for ever. A rotation
keeps the list of people who already held the lead, so after a manager's reassignment it carries
on with the rule's untried people only. Existing active rotations: the people up to the current
position are backfilled as tried.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2d4f6a8c0e2"
down_revision: Union[str, Sequence[str], None] = "a7c9e1b3d5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing ambiguous/teamless requests stay administrator-only; never guess an owning team.
    op.add_column("crm_owner_import_requests", sa.Column("team_id", sa.String(), nullable=True))
    op.create_index(
        "ix_crm_owner_import_requests_team_id", "crm_owner_import_requests", ["team_id"]
    )
    op.execute("""
        UPDATE crm_owner_import_requests r
        SET team_id = teams.team_id
        FROM (
            SELECT organization_id, user_id, min(team_id) AS team_id
            FROM organization_team_members
            GROUP BY organization_id, user_id HAVING count(*) = 1
        ) teams
        WHERE r.organization_id = teams.organization_id AND r.requested_by_user_id = teams.user_id
    """)
    op.add_column(
        "crm_owner_import_requests",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "crm_owner_import_requests",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    op.add_column(
        "crm_lead_rotations",
        sa.Column("tried_user_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    # Running rotations: everyone up to and including the current position has held the lead.
    op.execute(
        """
        UPDATE crm_lead_rotations
        SET tried_user_ids = (
            SELECT COALESCE(json_agg(value ORDER BY ordinality), '[]'::json)
            FROM json_array_elements_text(user_ids::json) WITH ORDINALITY AS t(value, ordinality)
            WHERE ordinality <= position + 1
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_crm_owner_import_requests_team_id", table_name="crm_owner_import_requests")
    op.drop_column("crm_owner_import_requests", "team_id")
    op.drop_column("crm_lead_rotations", "tried_user_ids")
    op.drop_column("crm_owner_import_requests", "attempts")
    op.drop_column("crm_owner_import_requests", "processing_started_at")
