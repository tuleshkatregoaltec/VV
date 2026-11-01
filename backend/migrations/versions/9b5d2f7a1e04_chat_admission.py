"""Add durable leases and unique daily totals, preserving the legacy usage table."""

import sqlalchemy as sa
from alembic import op

revision = "9b5d2f7a1e04"
down_revision = "8a4c1e6b0d93"
branch_labels = None
depends_on = None


def upgrade():
    # Pause AI writes during cutover: old binaries write the legacy table. No
    # original rows are changed or removed; duplicates are summed into a new ledger.
    op.create_table(
        "user_token_usage_totals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "date", name="uq_user_token_usage_day"),
    )
    op.create_index("ix_user_token_usage_totals_user_id", "user_token_usage_totals", ["user_id"])
    op.create_index("ix_user_token_usage_totals_date", "user_token_usage_totals", ["date"])
    op.execute("""
        INSERT INTO user_token_usage_totals
            (user_id, date, prompt_tokens, completion_tokens, total_tokens, created_at, updated_at)
        SELECT user_id, date, sum(prompt_tokens), sum(completion_tokens), sum(total_tokens),
               min(created_at), max(updated_at)
        FROM user_token_usage GROUP BY user_id, date
    """)
    op.create_table(
        "chat_turn_leases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("budget_day", sa.Date(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    for column in ("user_id", "organization_id", "conversation_id"):
        op.create_index(f"ix_chat_turn_leases_{column}", "chat_turn_leases", [column])


def downgrade():
    # Returning to the old binary would ignore post-cutover charges. Preserve
    # both ledgers and require an operator-reviewed reconciliation instead.
    raise RuntimeError(
        "Chat admission downgrade requires usage-ledger reconciliation; no data was removed"
    )
