"""Distinguish manually entered owners from import-derived snapshots."""

from alembic import op
import sqlalchemy as sa

revision = "6e2a9c4f8b71"
down_revision = "c4d6f8b0e2a5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("crm_lead_workspaces", sa.Column("owner_source", sa.String(), nullable=True))
    # Old import snapshots have an explicit tag. Do not infer that their contact
    # fields were manually verified. Values remain stored for review/recovery.
    op.execute("""
        UPDATE crm_lead_workspaces
        SET owner_source = CASE
            WHEN tags::jsonb @> '["Imported owner"]'::jsonb THEN 'owner_import'
            ELSE 'manual' END
        WHERE owner_name IS NOT NULL OR owner_email IS NOT NULL OR owner_phone IS NOT NULL
    """)


def downgrade():
    op.drop_column("crm_lead_workspaces", "owner_source")
