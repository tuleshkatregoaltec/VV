"""Audit private CRM mutations atomically without retaining customer field values.

Revision ID: d8e4a1c6b093
Revises: c7d3f0b5a982
"""

import sqlalchemy as sa
from alembic import op

revision = "d8e4a1c6b093"
down_revision = "c7d3f0b5a982"
branch_labels = None
depends_on = None

# Explicit private stores, including cascades and durable-worker writes. Shared
# regulator reference data and replaceable assessment revisions are not private stores.
_TABLES = (
    "crm_contact_imports",
    "crm_contact_lists",
    "crm_property_contact_claims",
    "crm_owner_workspaces",
    "crm_owner_notes",
    "crm_saved_leads",
    "crm_lead_workspaces",
    "crm_lead_notes",
    "crm_agent_area_preferences",
    "crm_inbound_imports",
    "crm_inbound_contacts",
    "crm_inbound_enquiries",
    "crm_inbound_notes",
    "crm_inbound_activities",
    "crm_inbound_matches",
    "crm_import_jobs",
)


def upgrade() -> None:
    op.create_table(
        "crm_mutation_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("actor_kind", sa.String(), nullable=False),
        sa.Column("database_actor", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False, server_default="success"),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint("row_count > 0", name="ck_crm_mutation_audit_rows"),
        sa.CheckConstraint(
            "action IN ('INSERT', 'UPDATE', 'DELETE')", name="ck_crm_mutation_audit_action"
        ),
        sa.CheckConstraint(
            "actor_kind IN ('user', 'database')", name="ck_crm_mutation_audit_actor"
        ),
        sa.CheckConstraint("outcome = 'success'", name="ck_crm_mutation_audit_outcome"),
    )
    op.create_index(
        "ix_crm_mutation_audit_org_time", "crm_mutation_audit", ["organization_id", "occurred_at"]
    )
    op.execute("""
        CREATE FUNCTION crm_reject_audit_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'CRM audit is append-only; private stores cannot be truncated'
                USING ERRCODE = '42501';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER crm_audit_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
        ON crm_mutation_audit FOR EACH STATEMENT EXECUTE FUNCTION crm_reject_audit_change()
    """)
    op.execute("""
        CREATE FUNCTION crm_guard_audit_insert() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF pg_trigger_depth() < 2 THEN
                RAISE EXCEPTION 'CRM audit can only be appended by mutation triggers'
                    USING ERRCODE = '42501';
            END IF;
            RETURN NULL;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER crm_audit_insert_guard BEFORE INSERT ON crm_mutation_audit
        FOR EACH STATEMENT EXECUTE FUNCTION crm_guard_audit_insert()
    """)
    # Transition tables aggregate only org IDs/counts. They avoid a separate audit
    # record (and copied before/after contact payload) per imported customer row.
    op.execute("""
        CREATE FUNCTION crm_audit_private_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            actor text := NULLIF(current_setting('app.actor_id', true), '');
            actor_org text := NULLIF(current_setting('app.organization_id', true), '');
            request text := NULLIF(current_setting('app.request_id', true), '');
            affected record;
            affected_query text;
        BEGIN
            IF (actor IS NULL) <> (actor_org IS NULL) THEN
                RAISE EXCEPTION 'Incomplete CRM transaction actor' USING ERRCODE = '42501';
            END IF;
            IF TG_OP = 'INSERT' THEN
                affected_query := 'SELECT organization_id, count(*) AS row_count '
                    'FROM new_rows GROUP BY organization_id';
            ELSIF TG_OP = 'DELETE' THEN
                affected_query := 'SELECT organization_id, count(*) AS row_count '
                    'FROM old_rows GROUP BY organization_id';
            ELSE
                affected_query := 'SELECT organization_id, max(row_count) AS row_count FROM ('
                    'SELECT organization_id, count(*) AS row_count FROM old_rows GROUP BY organization_id '
                    'UNION ALL SELECT organization_id, count(*) AS row_count '
                    'FROM new_rows GROUP BY organization_id) changes GROUP BY organization_id';
            END IF;
            FOR affected IN EXECUTE affected_query LOOP
                IF actor_org IS NOT NULL AND affected.organization_id IS DISTINCT FROM actor_org THEN
                    RAISE EXCEPTION 'CRM mutation organization does not match transaction actor'
                        USING ERRCODE = '42501';
                END IF;
                INSERT INTO public.crm_mutation_audit (
                    organization_id, actor_id, actor_kind, database_actor, request_id,
                    action, resource, outcome, row_count
                ) VALUES (
                    affected.organization_id, COALESCE(actor, current_user::text),
                    CASE WHEN actor IS NULL THEN 'database' ELSE 'user' END,
                    current_user::text, request, TG_OP, TG_TABLE_NAME, 'success', affected.row_count
                );
            END LOOP;
            RETURN NULL;
        END $$
    """)
    for table in _TABLES:
        for action, references in (
            ("INSERT", "NEW TABLE AS new_rows"),
            ("UPDATE", "OLD TABLE AS old_rows NEW TABLE AS new_rows"),
            ("DELETE", "OLD TABLE AS old_rows"),
        ):
            op.execute(f"""
                CREATE TRIGGER crm_audit_{action.lower()} AFTER {action} ON {table}
                REFERENCING {references} FOR EACH STATEMENT
                EXECUTE FUNCTION crm_audit_private_mutation()
            """)
        op.execute(f"""
            CREATE TRIGGER crm_no_truncate BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION crm_reject_audit_change()
        """)


def downgrade() -> None:
    for table in reversed(_TABLES):
        for action in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER crm_audit_{action} ON {table}")
        op.execute(f"DROP TRIGGER crm_no_truncate ON {table}")
    op.execute("DROP FUNCTION crm_audit_private_mutation()")
    op.drop_table("crm_mutation_audit")
    op.execute("DROP FUNCTION crm_guard_audit_insert()")
    op.execute("DROP FUNCTION crm_reject_audit_change()")
