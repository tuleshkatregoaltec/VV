"""languages agents speak, and routing rules that route to speakers only

Revision ID: a7c9e1b3d5f2
Revises: f3d5b7c9e1a4
Create Date: 2026-11-13 15:00:00.000000

An agent's languages are recorded by a manager or administrator; nothing is backfilled or
inferred. Existing rules keep routing as before (speakers_only defaults to false).
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "a7c9e1b3d5f2"
down_revision: Union[str, Sequence[str], None] = "f3d5b7c9e1a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STR = sqlmodel.sql.sqltypes.AutoString()


def upgrade() -> None:
    op.create_table(
        "crm_agent_languages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", _STR, nullable=False),
        sa.Column("user_id", _STR, nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("updated_by_user_id", _STR, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            name="fk_crm_agent_languages_membership",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_crm_agent_languages_member"),
    )
    op.create_index(
        op.f("ix_crm_agent_languages_organization_id"), "crm_agent_languages", ["organization_id"]
    )
    op.add_column(
        "crm_routing_rules",
        sa.Column("speakers_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("crm_lead_rotations", sa.Column("required_language", _STR, nullable=True))


def downgrade() -> None:
    op.drop_column("crm_lead_rotations", "required_language")
    op.drop_column("crm_routing_rules", "speakers_only")
    op.drop_index(op.f("ix_crm_agent_languages_organization_id"), table_name="crm_agent_languages")
    op.drop_table("crm_agent_languages")
