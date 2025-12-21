"""Add chat tool calling and compression support

Revision ID: 10912d69c757
Revises: 1dafd6990f49
Create Date: 2025-12-19 15:41:31.006790

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "10912d69c757"
down_revision: Union[str, Sequence[str], None] = "1dafd6990f49"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create conversations table
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversations_user_id"), "conversations", ["user_id"], unique=False
    )

    # Create messages table
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("compressed_content", sa.Text(), nullable=True),
        sa.Column("compression_ratio", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tool_call_ids", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_messages_conversation_id"),
        "messages",
        ["conversation_id"],
        unique=False,
    )

    # Create tool_call_results table
    op.create_table(
        "tool_call_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("tool_args", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("cached", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tool_call_results_conversation_id"),
        "tool_call_results",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_call_results_message_id"),
        "tool_call_results",
        ["message_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_tool_call_results_message_id"), table_name="tool_call_results"
    )
    op.drop_index(
        op.f("ix_tool_call_results_conversation_id"), table_name="tool_call_results"
    )
    op.drop_table("tool_call_results")
    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_conversations_user_id"), table_name="conversations")
    op.drop_table("conversations")
