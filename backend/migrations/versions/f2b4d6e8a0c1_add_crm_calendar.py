"""CRM calendar: Google connections and CRM events (restored from PR 50, repair be40cc4a)

The shared development database already holds both tables from the original PR 50 chain
(a2d5c7e9f104, b6d8f0a2c4e1, d8a3f1c5e7b9), so every step only creates what is missing and
never changes existing rows. A fresh database gets the final schema of those three revisions.

Revision ID: f2b4d6e8a0c1
Revises: e1f3a5c7b9d2
Create Date: 2026-11-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2b4d6e8a0c1"
down_revision: Union[str, Sequence[str], None] = "e1f3a5c7b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()
    if "crm_calendar_connections" not in tables:
        op.create_table(
            "crm_calendar_connections",
            sa.Column("organization_id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), primary_key=True),
            sa.Column("google_email", sa.String(), nullable=False),
            sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
            sa.Column("sync_token", sa.Text()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "crm_calendar_events" not in tables:
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
            sa.Column(
                "lead_id",
                sa.Integer(),
                sa.ForeignKey("crm_inbound_enquiries.id", ondelete="SET NULL"),
            ),
            sa.Column("listing_id", sa.String()),
            sa.Column("google_event_id", sa.String()),
            sa.Column("etag", sa.String()),
            sa.Column("google_sync_status", sa.String(), nullable=False, server_default="local"),
            sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("event_end_date", sa.Date()),
            sa.Column("event_end_time", sa.String()),
            sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("repeat", sa.String(), nullable=False, server_default="none"),
            sa.Column("meet", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("meet_link", sa.String()),
            sa.Column("meet_request_id", sa.String()),
            sa.Column("location", sa.String(), nullable=False, server_default=""),
            sa.Column("reminders", sa.JSON(), nullable=False, server_default="[30]"),
            sa.Column(
                "reminders_use_default", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("guests", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("guests_can_modify", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "guests_can_invite_others", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "guests_can_see_other_guests",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column("show_as", sa.String(), nullable=False, server_default="busy"),
            sa.Column("visibility", sa.String(), nullable=False, server_default="default"),
            sa.Column("rescheduled_from", sa.JSON(), nullable=False, server_default="[]"),
            sa.UniqueConstraint("organization_id", "user_id", "google_event_id"),
        )
    indexes = _indexes("crm_calendar_events")
    if "ix_crm_calendar_events_owner_date" not in indexes:
        op.create_index(
            "ix_crm_calendar_events_owner_date",
            "crm_calendar_events",
            ["organization_id", "user_id", "event_date"],
        )
    if "ix_crm_calendar_events_google_id" not in indexes:
        op.create_index(
            "ix_crm_calendar_events_google_id",
            "crm_calendar_events",
            ["organization_id", "user_id", "google_event_id"],
        )
    if "ix_crm_calendar_events_lead_id" not in indexes:
        # Deleting a lead nulls its events' lead_id; without this that scans every event.
        op.create_index("ix_crm_calendar_events_lead_id", "crm_calendar_events", ["lead_id"])


def downgrade() -> None:
    op.drop_table("crm_calendar_events")
    op.drop_table("crm_calendar_connections")
