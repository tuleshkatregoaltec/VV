"""Per-agent WhatsApp connections: encrypted tokens, Meta asset state and contacts.

Existing rows were created for the env-configured pilot number. They become
`onboarding_type = 'env'`; the application copies the env token into the encrypted
column on start-up (see customer_connections.bootstrap_env_connection).

Unclassified inbound content may no longer rest in PostgreSQL, so any legacy
queued/classifying rows are cancelled and their content erased.

Revision ID: 7a1d3c5e9b20
Revises: 6e8b4a2c19d0
"""

import sqlalchemy as sa
from alembic import op

revision = "7a1d3c5e9b20"
down_revision = "6e8b4a2c19d0"
branch_labels = None
depends_on = None


def upgrade():
    columns = [
        sa.Column("status", sa.String(), nullable=False, server_default="connected"),
        sa.Column("onboarding_type", sa.String()),
        sa.Column("business_id", sa.String()),
        sa.Column("display_phone_number", sa.String()),
        sa.Column("access_token_encrypted", sa.Text()),
        sa.Column("quality_rating", sa.String()),
        sa.Column("health", sa.JSON()),
        sa.Column("last_account_event", sa.String()),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
        sa.Column("disconnected_at", sa.DateTime(timezone=True)),
        sa.Column("contacts_sync_requested_at", sa.DateTime(timezone=True)),
        sa.Column("contacts_synced_at", sa.DateTime(timezone=True)),
    ]
    for column in columns:
        op.add_column("whatsapp_connections", column)
    op.execute("UPDATE whatsapp_connections SET onboarding_type = 'env', connected_at = created_at")
    op.create_index("ix_whatsapp_connections_account_id", "whatsapp_connections", ["account_id"])
    op.create_table(
        "whatsapp_contacts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(),
            sa.ForeignKey("whatsapp_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("wa_id", sa.String()),
        sa.Column("bsuid", sa.String()),
        sa.Column("name", sa.String()),
        sa.Column("in_address_book", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("blocked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "wa_id", name="uq_whatsapp_contact_wa_id"),
        sa.UniqueConstraint("connection_id", "bsuid", name="uq_whatsapp_contact_bsuid"),
    )
    op.create_index(
        "ix_whatsapp_contact_blocked", "whatsapp_contacts", ["connection_id", "blocked"]
    )
    op.execute(
        "UPDATE whatsapp_customer_messages SET status = 'cancelled', content = NULL, "
        "reply = NULL, reason = 'privacy_migration', send_after = NULL, "
        "revision = revision + 1 WHERE status IN ('queued', 'classifying')"
    )


def downgrade():
    op.drop_table("whatsapp_contacts")
    op.drop_index("ix_whatsapp_connections_account_id", table_name="whatsapp_connections")
    for name in (
        "contacts_synced_at",
        "contacts_sync_requested_at",
        "disconnected_at",
        "connected_at",
        "last_account_event",
        "health",
        "quality_rating",
        "access_token_encrypted",
        "display_phone_number",
        "business_id",
        "onboarding_type",
        "status",
    ):
        op.drop_column("whatsapp_connections", name)
