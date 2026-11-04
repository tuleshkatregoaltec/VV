"""CRM WhatsApp: campaigns and their recipients

Revision ID: c4e1a8b7d2f9
Revises: b7d2e9f4a1c3
Create Date: 2026-11-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "c4e1a8b7d2f9"
down_revision: Union[str, Sequence[str], None] = "b7d2e9f4a1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    string = sqlmodel.sql.sqltypes.AutoString
    op.create_table(
        "crm_whatsapp_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", string(), nullable=False),
        sa.Column(
            "number_id",
            sa.Integer(),
            sa.ForeignKey("crm_whatsapp_numbers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", string(), nullable=False),
        sa.Column("template_name", string(), nullable=False),
        sa.Column("template_language", string(), nullable=False),
        sa.Column("template_body", sa.Text(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("status", string(), nullable=False),
        sa.Column("created_by_user_id", string(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_crm_whatsapp_campaigns_organization_id"),
        "crm_whatsapp_campaigns",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_crm_whatsapp_campaigns_number_id"), "crm_whatsapp_campaigns", ["number_id"]
    )

    op.create_table(
        "crm_whatsapp_campaign_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.Integer(),
            sa.ForeignKey("crm_whatsapp_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("organization_id", string(), nullable=False),
        sa.Column(
            "enquiry_id",
            sa.Integer(),
            sa.ForeignKey("crm_inbound_enquiries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("wa_id", string(), nullable=False),
        sa.Column("name", string(), nullable=False),
        sa.Column("status", string(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("crm_whatsapp_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "wa_id", name="uq_crm_whatsapp_campaign_recipient"),
    )
    op.create_index(
        op.f("ix_crm_whatsapp_campaign_recipients_organization_id"),
        "crm_whatsapp_campaign_recipients",
        ["organization_id"],
    )
    op.create_index(
        "ix_crm_whatsapp_campaign_recipients_queue",
        "crm_whatsapp_campaign_recipients",
        ["campaign_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("crm_whatsapp_campaign_recipients")
    op.drop_table("crm_whatsapp_campaigns")
