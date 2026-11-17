"""Durable customer-channel connections, threads and revisioned review inbox.

Revision ID: 31c7e90b42ad
Revises: 0a9c3d7e1f62
"""

import sqlalchemy as sa
from alembic import op

revision = "31c7e90b42ad"
down_revision = "0a9c3d7e1f62"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.create_table(
        "whatsapp_connections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("phone_number_id", sa.String(), nullable=False, unique=True),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("approved_knowledge", sa.JSON(), nullable=False),
        *timestamps(),
    )
    for name in ("user_id", "organization_id"):
        op.create_index(f"ix_whatsapp_connections_{name}", "whatsapp_connections", [name])
    op.create_table(
        "whatsapp_customer_threads",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(),
            sa.ForeignKey("whatsapp_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sender", sa.String(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("opted_out", sa.Boolean(), nullable=False),
        sa.Column(
            "conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="SET NULL")
        ),
        *timestamps(),
        sa.UniqueConstraint("connection_id", "sender", name="uq_whatsapp_customer_thread_sender"),
    )
    op.create_table(
        "whatsapp_customer_messages",
        sa.Column("id", sa.String(512), primary_key=True),
        sa.Column(
            "thread_id",
            sa.String(),
            sa.ForeignKey("whatsapp_customer_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        *timestamps(),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reply", sa.Text()),
        sa.Column("risk", sa.String()),
        sa.Column("topic", sa.String()),
        sa.Column("reason", sa.String()),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("send_after", sa.DateTime(timezone=True)),
        sa.Column("notification_created_at", sa.DateTime(timezone=True)),
        sa.Column("notification_seen_at", sa.DateTime(timezone=True)),
        sa.Column("outbound_id", sa.String()),
        sa.Column("error_code", sa.String()),
    )
    op.create_index(
        "ix_whatsapp_customer_message_queue", "whatsapp_customer_messages", ["status", "send_after"]
    )
    op.create_index(
        "ix_whatsapp_customer_message_thread",
        "whatsapp_customer_messages",
        ["thread_id", "created_at"],
    )


def downgrade():
    op.drop_table("whatsapp_customer_messages")
    op.drop_table("whatsapp_customer_threads")
    op.drop_table("whatsapp_connections")
