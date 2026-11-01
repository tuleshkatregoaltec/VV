"""one recently-sold Inbox item per owner per agency

Revision ID: e7b9c1d3f5a2
Revises: f4b2d8a6c0e1
Create Date: 2026-10-27 20:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7b9c1d3f5a2"
down_revision: Union[str, Sequence[str], None] = "f4b2d8a6c0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_crm_inbound_sold_owner",
        "crm_inbound_enquiries",
        ["organization_id", "source_lead_id"],
        unique=True,
        postgresql_where=sa.text("source = 'Owner file · recently sold'"),
    )


def downgrade() -> None:
    op.drop_index("uq_crm_inbound_sold_owner", table_name="crm_inbound_enquiries")
