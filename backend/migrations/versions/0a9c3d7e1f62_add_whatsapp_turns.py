"""Durable WhatsApp pilot receipt and reply ledger.

Revision ID: 0a9c3d7e1f62
Revises: e7b9c1d3f5a2
"""

import sqlalchemy as sa
from alembic import op

revision = "0a9c3d7e1f62"
down_revision = "e7b9c1d3f5a2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "whatsapp_turns",
        sa.Column("id", sa.String(512), primary_key=True),
        sa.Column("phone_number_id", sa.String(), nullable=False),
        sa.Column("sender", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="SET NULL")
        ),
        sa.Column("reply", sa.Text()),
        sa.Column("outbound_id", sa.String()),
        sa.Column("error_code", sa.String()),
    )
    for column in ("user_id", "organization_id", "outbound_id"):
        op.create_index(f"ix_whatsapp_turns_{column}", "whatsapp_turns", [column])
    op.create_index("ix_whatsapp_turns_queue", "whatsapp_turns", ["status", "created_at"])


def downgrade():
    op.drop_table("whatsapp_turns")
