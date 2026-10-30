"""CRM assistant: proposed-action store; message metadata on the existing assistant tables

The conversation and message tables already exist (c51b90aa7f42). Messages keep their rows; the
JSON column is renamed from sources to meta_data, which now holds the proposed-action cards.

Revision ID: c3e5a7b9d1f2
Revises: b6d8f0a2c4e1
Create Date: 2026-10-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "c3e5a7b9d1f2"
down_revision: Union[str, Sequence[str], None] = "b6d8f0a2c4e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("crm_assistant_messages", "sources", new_column_name="meta_data")

    op.create_table(
        "crm_assistant_actions",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("organization_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("enquiry_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["crm_assistant_conversations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "user_id", "conversation_id", "enquiry_id", "status"):
        op.create_index(
            op.f(f"ix_crm_assistant_actions_{column}"), "crm_assistant_actions", [column]
        )


def downgrade() -> None:
    op.drop_table("crm_assistant_actions")
    op.alter_column("crm_assistant_messages", "meta_data", new_column_name="sources")
