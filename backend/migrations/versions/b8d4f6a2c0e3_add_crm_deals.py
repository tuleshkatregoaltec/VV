"""CRM deals and their stage history

Additive only: two new tables. Each step creates only what is missing, so running it against
a database that already has them (the shared development database) changes nothing.

Revision ID: b8d4f6a2c0e3
Revises: f2b4d6e8a0c1
Create Date: 2026-11-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4f6a2c0e3"
down_revision: Union[str, Sequence[str], None] = "f2b4d6e8a0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()
    if "crm_deals" not in tables:
        op.create_table(
            "crm_deals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column(
                "lead_id",
                sa.Integer(),
                sa.ForeignKey("crm_inbound_enquiries.id", ondelete="SET NULL"),
            ),
            sa.Column("assigned_user_id", sa.String()),
            sa.Column("team_id", sa.String()),
            sa.Column("created_by_user_id", sa.String(), nullable=False),
            sa.Column("deal_type", sa.String(), nullable=False),
            sa.Column("unit", sa.String(), nullable=False),
            sa.Column("client", sa.String(), nullable=False),
            sa.Column("counterparty", sa.String(), nullable=False),
            sa.Column("value_aed", sa.BigInteger()),
            sa.Column("due_date", sa.Date()),
            sa.Column("listing_id", sa.String()),
            sa.Column("origin", sa.String(), nullable=False),
            sa.Column("origin_source", sa.String(), nullable=False),
            sa.Column("stage_index", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("dld_transaction_id", sa.String()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("closed_at", sa.DateTime(timezone=True)),
        )
    if "crm_deal_events" not in tables:
        op.create_table(
            "crm_deal_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column(
                "deal_id",
                sa.Integer(),
                sa.ForeignKey("crm_deals.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("actor_user_id", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("from_stage", sa.Integer()),
            sa.Column("to_stage", sa.Integer()),
            sa.Column("detail", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    for table, name, columns in (
        ("crm_deals", "ix_crm_deals_lead_id", ["lead_id"]),
        (
            "crm_deals",
            "ix_crm_deals_org_agent_status",
            ["organization_id", "assigned_user_id", "status"],
        ),
        ("crm_deals", "ix_crm_deals_org_team", ["organization_id", "team_id"]),
        ("crm_deal_events", "ix_crm_deal_events_deal_id", ["deal_id"]),
        (
            "crm_deal_events",
            "ix_crm_deal_events_org_actor_at",
            ["organization_id", "actor_user_id", "created_at"],
        ),
    ):
        if name not in _indexes(table):
            op.create_index(name, table, columns)


def downgrade() -> None:
    op.drop_table("crm_deal_events")
    op.drop_table("crm_deals")
