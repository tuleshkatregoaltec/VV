"""expand CRM calendar event fields

Revision ID: b6d8f0a2c4e1
Revises: a2d5c7e9f104
Create Date: 2026-10-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6d8f0a2c4e1"
down_revision: Union[str, Sequence[str], None] = "a2d5c7e9f104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE crm_calendar_connections SET sync_token = NULL")
    op.add_column("crm_calendar_events", sa.Column("event_end_date", sa.Date(), nullable=True))
    op.add_column("crm_calendar_events", sa.Column("event_end_time", sa.String(), nullable=True))
    op.add_column(
        "crm_calendar_events",
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "crm_calendar_events",
        sa.Column("repeat", sa.String(), nullable=False, server_default="none"),
    )
    op.add_column(
        "crm_calendar_events",
        sa.Column("meet", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("crm_calendar_events", sa.Column("meet_link", sa.String(), nullable=True))
    op.add_column("crm_calendar_events", sa.Column("meet_request_id", sa.String(), nullable=True))
    op.add_column(
        "crm_calendar_events",
        sa.Column("location", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "crm_calendar_events",
        sa.Column("reminders", sa.JSON(), nullable=False, server_default="[30]"),
    )
    op.add_column(
        "crm_calendar_events",
        sa.Column("reminders_use_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "crm_calendar_events",
        sa.Column("guests", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "crm_calendar_events",
        sa.Column("guests_can_modify", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "crm_calendar_events",
        sa.Column("guests_can_invite_others", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "crm_calendar_events",
        sa.Column("guests_can_see_other_guests", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "crm_calendar_events",
        sa.Column("show_as", sa.String(), nullable=False, server_default="busy"),
    )
    op.add_column(
        "crm_calendar_events",
        sa.Column("visibility", sa.String(), nullable=False, server_default="default"),
    )
    op.execute(
        "UPDATE crm_calendar_events SET event_end_date = event_date WHERE event_end_date IS NULL"
    )


def downgrade() -> None:
    for column in (
        "visibility",
        "show_as",
        "guests_can_see_other_guests",
        "guests_can_invite_others",
        "guests_can_modify",
        "guests",
        "reminders_use_default",
        "reminders",
        "location",
        "meet_request_id",
        "meet_link",
        "meet",
        "repeat",
        "all_day",
        "event_end_time",
        "event_end_date",
    ):
        op.drop_column("crm_calendar_events", column)
