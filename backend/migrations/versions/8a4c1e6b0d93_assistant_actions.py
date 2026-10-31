"""Persist confirmation proposals, private tasks, drafts and disconnected outbox."""

from alembic import op
import sqlalchemy as sa

revision = "8a4c1e6b0d93"
down_revision = "7f3b0d5a9c82"
branch_labels = None
depends_on = None


def _owners():
    return [
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
    ]


def _timestamp(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _indexes(table, *fields):
    for field in ("user_id", "organization_id", *fields):
        op.create_index(f"ix_{table}_{field}", table, [field])


def upgrade():
    op.create_table(
        "assistant_actions",
        sa.Column("id", sa.String(), primary_key=True),
        *_owners(),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("preview", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        _timestamp("created_at"),
        _timestamp("expires_at"),
        _timestamp("completed_at", True),
        sa.UniqueConstraint(
            "user_id", "organization_id", "idempotency_key", name="uq_assistant_action_idempotency"
        ),
    )
    _indexes("assistant_actions", "conversation_id", "status")
    op.create_table(
        "assistant_reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_owners(),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        _timestamp("due_at"),
        _timestamp("updated_at"),
    )
    _indexes("assistant_reminders")
    op.create_table(
        "assistant_viewings",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_owners(),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        _timestamp("starts_at"),
        _timestamp("ends_at"),
        _timestamp("updated_at"),
    )
    _indexes("assistant_viewings")
    op.create_table(
        "assistant_listing_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_owners(),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("price_aed", sa.BigInteger(), nullable=False),
        sa.Column("location", sa.String(), nullable=False),
        _timestamp("updated_at"),
    )
    _indexes("assistant_listing_drafts")
    op.create_table(
        "assistant_outbox",
        sa.Column("id", sa.String(), primary_key=True),
        *_owners(),
        sa.Column("action_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _timestamp("created_at"),
        _timestamp("claimed_at", True),
    )
    _indexes("assistant_outbox")
    op.create_index("ix_assistant_outbox_action_id", "assistant_outbox", ["action_id"], unique=True)


def downgrade():
    for table in (
        "assistant_outbox",
        "assistant_listing_drafts",
        "assistant_viewings",
        "assistant_reminders",
        "assistant_actions",
    ):
        op.drop_table(table)
