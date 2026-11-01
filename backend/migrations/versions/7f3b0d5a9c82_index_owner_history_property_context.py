"""Index tenant property history across contact identities and imports."""

from alembic import op

revision = "7f3b0d5a9c82"
down_revision = "6e2a9c4f8b71"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_crm_claim_org_property",
        "crm_property_contact_claims",
        ["organization_id", "property_key"],
    )


def downgrade():
    op.drop_index("ix_crm_claim_org_property", table_name="crm_property_contact_claims")
