"""Separate the CRM Operations Assistant's and Market AI's conversation histories

Adds conversations.assistant ('crm' or 'market', default 'crm') so each product lists only its
own conversations. Nothing is deleted or moved: every existing conversation keeps its messages.
Existing conversations that hold a Market AI answer (messages tagged meta_data.assistant =
'market') become Market AI conversations; every other existing conversation becomes a CRM
Assistant conversation, so no conversation is lost from view or shown in both.

Idempotent, like the other shared-database migrations: each step only adds what is missing.

Revision ID: c5e9a3b7d1f4
Revises: b8d4f6a2c0e3
Create Date: 2026-11-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5e9a3b7d1f4"
down_revision: Union[str, Sequence[str], None] = "b8d4f6a2c0e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()
    columns = {column["name"] for column in inspector.get_columns("conversations")}
    if "assistant" not in columns:
        # Existing rows take the default: the CRM Operations Assistant.
        op.add_column(
            "conversations",
            sa.Column("assistant", sa.String(), nullable=False, server_default="crm"),
        )
    checks = {check["name"] for check in inspector.get_check_constraints("conversations")}
    if "ck_conversations_assistant" not in checks:
        op.create_check_constraint(
            "ck_conversations_assistant", "conversations", "assistant IN ('crm', 'market')"
        )
    indexes = {index["name"] for index in inspector.get_indexes("conversations")}
    if "ix_conversations_owner_assistant" not in indexes:
        op.create_index(
            "ix_conversations_owner_assistant",
            "conversations",
            ["user_id", "organization_id", "assistant"],
        )
    # Conversations Market AI already answered in belong to Market AI.
    op.execute(
        """
        UPDATE conversations
        SET assistant = 'market'
        WHERE assistant = 'crm'
          AND id IN (
              SELECT conversation_id FROM messages
              WHERE role = 'assistant' AND meta_data ->> 'assistant' = 'market'
          )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_owner_assistant", table_name="conversations")
    op.drop_constraint("ck_conversations_assistant", "conversations", type_="check")
    op.drop_column("conversations", "assistant")
