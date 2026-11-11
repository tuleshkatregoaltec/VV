"""Per-agent reply voice, handoff summaries and human-paced sending state.

Adds the agent's writing voice (JSON), a short handoff summary for the agent, the
qualification question a reply asked (so a bare answer can be recognised even when the
question is worded naturally), and the time the typing indicator went out.

Revision ID: 8b2e4f6a1c93
Revises: 7a1d3c5e9b20
"""

import sqlalchemy as sa
from alembic import op

revision = "8b2e4f6a1c93"
down_revision = "7a1d3c5e9b20"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("whatsapp_connections", sa.Column("reply_voice", sa.JSON()))
    op.add_column("whatsapp_customer_messages", sa.Column("handoff_summary", sa.Text()))
    op.add_column("whatsapp_customer_messages", sa.Column("asked_detail", sa.String()))
    op.add_column(
        "whatsapp_customer_messages",
        sa.Column("typing_started_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_column("whatsapp_customer_messages", "typing_started_at")
    op.drop_column("whatsapp_customer_messages", "asked_detail")
    op.drop_column("whatsapp_customer_messages", "handoff_summary")
    op.drop_column("whatsapp_connections", "reply_voice")
