"""add the licensed real-estate broker reference table

Revision ID: a8d3c6f1b9e4
Revises: 7f3b0d5a9c82
Create Date: 2026-10-30 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "a8d3c6f1b9e4"
down_revision: Union[str, Sequence[str], None] = "7f3b0d5a9c82"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_licensed_brokers",
        sa.Column("broker_number", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("phones", sa.JSON(), nullable=False),
        sa.Column("emails", sa.JSON(), nullable=False),
        sa.Column("card_expiry_date", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("broker_number"),
    )
    op.create_index(
        op.f("ix_crm_licensed_brokers_name_key"),
        "crm_licensed_brokers",
        ["name_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_crm_licensed_brokers_name_key"), table_name="crm_licensed_brokers")
    op.drop_table("crm_licensed_brokers")
