"""CRM calendar: remember the slots an event was rescheduled from

Revision ID: d8a3f1c5e7b9
Revises: c3e5a7b9d1f2
Create Date: 2026-10-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8a3f1c5e7b9"
down_revision: Union[str, Sequence[str], None] = "c3e5a7b9d1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "crm_calendar_events",
        sa.Column("rescheduled_from", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("crm_calendar_events", "rescheduled_from")
