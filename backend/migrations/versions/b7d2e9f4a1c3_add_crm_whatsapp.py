"""CRM WhatsApp: sender numbers, messages and opt-outs

Revision ID: b7d2e9f4a1c3
Revises: d8a3f1c5e7b9
Create Date: 2026-11-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "b7d2e9f4a1c3"
down_revision: Union[str, Sequence[str], None] = "d8a3f1c5e7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column], unique=False)


def upgrade() -> None:
    string = sqlmodel.sql.sqltypes.AutoString
    op.create_table(
        "crm_whatsapp_numbers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", string(), nullable=False),
        sa.Column("phone_number_id", string(), nullable=False),
        sa.Column("display_number", string(), nullable=False),
        sa.Column("label", string(), nullable=False),
        sa.Column("purpose", string(), nullable=False),
        sa.Column("user_id", string(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("phone_number_id", name="uq_crm_whatsapp_number_phone_number_id"),
    )
    _indexes("crm_whatsapp_numbers", ("organization_id", "user_id"))
    op.create_index(
        "uq_crm_whatsapp_number_agent",
        "crm_whatsapp_numbers",
        ["organization_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("active AND purpose = 'agent'"),
    )

    op.create_table(
        "crm_whatsapp_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", string(), nullable=False),
        sa.Column(
            "number_id",
            sa.Integer(),
            sa.ForeignKey("crm_whatsapp_numbers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("wa_id", string(), nullable=False),
        sa.Column("direction", string(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("wamid", string(), nullable=True),
        sa.Column("template_name", string(), nullable=True),
        sa.Column("template_language", string(), nullable=True),
        sa.Column("status", string(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("contact_name", string(), nullable=True),
        sa.Column("sent_by_user_id", string(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("wamid", name="uq_crm_whatsapp_message_wamid"),
    )
    _indexes("crm_whatsapp_messages", ("organization_id", "number_id", "wa_id"))
    op.create_index(
        "ix_crm_whatsapp_messages_conversation",
        "crm_whatsapp_messages",
        ["number_id", "wa_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "crm_whatsapp_opt_outs",
        sa.Column("organization_id", string(), primary_key=True),
        sa.Column("wa_id", string(), primary_key=True),
        sa.Column("reason", string(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("crm_whatsapp_opt_outs")
    op.drop_table("crm_whatsapp_messages")
    op.drop_table("crm_whatsapp_numbers")
