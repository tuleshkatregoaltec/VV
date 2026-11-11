"""Persist the per-claim CRM ownership assessment.

Additive only: one sequence and four tables, nothing altered and nothing removed.

- ``crm_owner_assessed_claims``: the assessed row of every claim of a tenant for one
  ``generation`` (the whole-tenant snapshot, one row per claim, with the columns the Owners
  reads filter and order by).
- ``crm_owner_assessment_state``: which generation is current for a tenant, the source and
  registry-evidence revisions it was built from, and the tenant-wide counts.
- ``crm_owner_registry_owners`` / ``crm_owner_registry_properties``: each owner's profile
  (for the tenant and for each contact list) and the per-property columns the registry
  filters, counts and sorts by.

Nothing reads these tables in an older release; dropping them restores the previous
behaviour. They are filled by the first Owners read of a tenant (or an explicit rebuild).

Revision ID: 9c3f5a7d1e24
Revises: 8b2e4f6a1c93
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "9c3f5a7d1e24"
down_revision = "8b2e4f6a1c93"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SEQUENCE crm_owner_assessment_generation_seq AS bigint")
    op.create_table(
        "crm_owner_assessment_state",
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.String(), nullable=False),
        sa.Column("warehouse_revision", sa.String(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("warehouse_status", sa.String(), nullable=False),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        # What the assessment says about the tenant as a whole, computed once per generation.
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("import_summaries", postgresql.JSONB(), nullable=False),
        sa.Column("list_counts", postgresql.JSONB(), nullable=False),
        sa.Column("source_audit", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("organization_id"),
    )
    op.create_table(
        "crm_owner_assessed_claims",
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("claim_id", sa.Integer(), nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("import_id", sa.Integer(), nullable=False),
        sa.Column("owner_key", sa.String(), nullable=False),
        sa.Column("canonical_owner_key", sa.String(), nullable=False),
        sa.Column("property_key", sa.String(), nullable=False),
        sa.Column("identity_area", sa.String()),
        sa.Column("identity_key", sa.String()),
        sa.Column("group_ident", sa.String(), nullable=False),
        sa.Column("is_source", sa.Boolean(), nullable=False),
        sa.Column("ord", sa.BigInteger(), nullable=False),
        sa.Column("assessed_status", sa.String(), nullable=False),
        sa.Column("party_role", sa.String(), nullable=False),
        sa.Column("transaction_date", sa.Date()),
        sa.Column("event_conf", sa.Integer(), nullable=False),
        sa.Column("pref_support", sa.Boolean(), nullable=False),
        sa.Column("pref_buyer", sa.Boolean(), nullable=False),
        sa.Column("ready_row", sa.Boolean(), nullable=False),
        sa.Column("lead_id", sa.String()),
        sa.Column("building_name", sa.String()),
        sa.Column("project_name", sa.String()),
        sa.Column("unit_number", sa.String()),
        sa.Column("area_name", sa.String()),
        sa.Column("match_colour", sa.String()),
        sa.Column("match_outcome", sa.String()),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("props_search_text", sa.Text(), nullable=False),
        sa.Column("row", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "generation", "claim_id"),
    )
    for name, columns in (
        ("canonical", ["canonical_owner_key"]),
        ("owner", ["owner_key"]),
        ("list", ["list_id", "ord"]),
        ("import", ["import_id", "ord"]),
        ("identity", ["identity_key", "identity_area"]),
        ("property", ["property_key"]),
    ):
        op.create_index(
            f"ix_crm_assessed_claim_{name}",
            "crm_owner_assessed_claims",
            ["organization_id", "generation", *columns],
        )
    op.create_table(
        "crm_owner_registry_owners",
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        # 0 for the whole organization, otherwise the contact list the profile is limited to.
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("canonical_owner_key", sa.String(), nullable=False),
        sa.Column("owner_key", sa.String(), nullable=False),
        sa.Column("profile", postgresql.JSONB(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("property_count", sa.Integer(), nullable=False),
        sa.Column("contact_ready_count", sa.Integer(), nullable=False),
        sa.Column("highest_confidence_score", sa.Integer(), nullable=False),
        sa.Column("next_lease_end", sa.Date()),
        sa.Column("developer_side_seller", sa.Boolean(), nullable=False),
        sa.Column("invalid_identity_sources", sa.Boolean(), nullable=False),
        sa.Column("no_properties", sa.Boolean(), nullable=False),
        sa.Column("in_rental", sa.Boolean(), nullable=False),
        sa.Column("in_registry", sa.Boolean(), nullable=False),
        sa.Column("in_prior", sa.Boolean(), nullable=False),
        sa.Column("in_review", sa.Boolean(), nullable=False),
        sa.Column("in_multi", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "generation", "list_id", "canonical_owner_key"),
    )
    op.create_index(
        "ix_crm_registry_owner_key",
        "crm_owner_registry_owners",
        ["organization_id", "generation", "list_id", "owner_key"],
    )
    op.create_table(
        "crm_owner_registry_properties",
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("canonical_owner_key", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("ready", sa.Boolean(), nullable=False),
        sa.Column("rental_linked", sa.Boolean(), nullable=False),
        sa.Column("lease_end", sa.Date()),
        sa.Column("annual_rent_aed", sa.BigInteger()),
        sa.Column("sale_price_aed", sa.BigInteger()),
        sa.Column("match_status", sa.String()),
        sa.Column("location_text", sa.Text(), nullable=False),
        sa.Column("headline_rank", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "organization_id", "generation", "list_id", "canonical_owner_key", "ordinal"
        ),
    )
    op.create_index(
        "ix_crm_assessed_claim_lead",
        "crm_owner_assessed_claims",
        ["organization_id", "generation", "lead_id"],
        postgresql_where=sa.text("lead_id IS NOT NULL"),
    )


def downgrade():
    op.drop_table("crm_owner_registry_properties")
    op.drop_table("crm_owner_registry_owners")
    op.drop_table("crm_owner_assessed_claims")
    op.drop_table("crm_owner_assessment_state")
    op.execute("DROP SEQUENCE crm_owner_assessment_generation_seq")
