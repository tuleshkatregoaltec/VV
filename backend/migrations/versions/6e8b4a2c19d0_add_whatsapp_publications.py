"""Broker-approved expiring publications and customer evidence snapshots.

Revision ID: 6e8b4a2c19d0
Revises: 31c7e90b42ad
"""

import sqlalchemy as sa
from alembic import op

revision = "6e8b4a2c19d0"
down_revision = "31c7e90b42ad"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "whatsapp_connections",
        sa.Column("market_data_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "whatsapp_customer_messages",
        sa.Column("evidence_snapshots", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "whatsapp_published_listings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(),
            sa.ForeignKey("whatsapp_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=False),
        sa.Column("property_type", sa.String(), nullable=False),
        sa.Column("transaction", sa.String(), nullable=False),
        sa.Column("bedrooms", sa.Integer()),
        sa.Column("price_aed", sa.Float(), nullable=False),
        sa.Column("area_sqft", sa.Float()),
        sa.Column("availability", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_whatsapp_listing_connection",
        "whatsapp_published_listings",
        ["connection_id", "expires_at"],
    )


def downgrade():
    op.drop_table("whatsapp_published_listings")
    op.drop_column("whatsapp_customer_messages", "evidence_snapshots")
    op.drop_column("whatsapp_connections", "market_data_enabled")
