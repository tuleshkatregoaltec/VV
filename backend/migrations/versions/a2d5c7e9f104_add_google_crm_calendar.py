"""add per-agent Google Calendar connections and CRM events

Revision ID: a2d5c7e9f104
Revises: e7b9c1d3f5a2
Create Date: 2026-10-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2d5c7e9f104"
down_revision: Union[str, Sequence[str], None] = "e7b9c1d3f5a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_calendar_connections",
        sa.Column("organization_id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("google_email", sa.String(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("sync_token", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "crm_calendar_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.String()),
        sa.Column("kind", sa.String(), nullable=False, server_default="follow_up"),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("lead_id", sa.Integer()),
        sa.Column("listing_id", sa.String()),
        sa.Column("google_event_id", sa.String()),
        sa.Column("etag", sa.String()),
        sa.Column("google_sync_status", sa.String(), nullable=False, server_default="local"),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", "google_event_id"),
        sa.ForeignKeyConstraint(["lead_id"], ["crm_inbound_enquiries.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_crm_calendar_events_owner_date",
        "crm_calendar_events",
        ["organization_id", "user_id", "event_date"],
    )


def downgrade() -> None:
    op.drop_table("crm_calendar_events")
    op.drop_table("crm_calendar_connections")
