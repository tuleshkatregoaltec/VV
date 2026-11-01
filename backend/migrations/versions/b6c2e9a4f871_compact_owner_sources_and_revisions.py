"""Persist compact owner sources and transactional tenant revision tokens.

Revision ID: b6c2e9a4f871
Revises: a8d3c6f1b9e4
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b6c2e9a4f871"
down_revision = "a8d3c6f1b9e4"
branch_labels = None
depends_on = None

# Match the existing history read projection. Original evidence/mapping JSON stays
# untouched: these are replaceable read inputs, never a new audit authority.
_HISTORY_KEYS = """
    resolver_version event_family cadastral_identity scoped_identity_collision
    source_size_unit original_identifiers original_property_fields inferred_size_unit
    amount_first_match property_identity_match owner_match_policy source_file_sha256
    source_identifiers source_area_field source_filename address_recovery
    inferred_file_context source_registry_location_resolution property_identity_resolution
    file_context registry_unit_fallback unit_hierarchy_resolution source_unit_number
    duplicate_count source_audit owner_match broker_contact
""".split()
_SOURCE_KEYS = """
    size_sqft size_sqm size_unknown property_type unit_number area_name master_project
    project_name building_name building_number property_number plot_number
    plot_pre_reg_number transaction_price_aed
""".split()
_TABLES = ("crm_contact_imports", "crm_contact_lists", "crm_property_contact_claims")


def upgrade() -> None:
    history_keys = ", ".join(f"'{key}'" for key in _HISTORY_KEYS)
    source_keys = ", ".join(f"'{key}'" for key in _SOURCE_KEYS)
    # json_to_record previously coerced these legacy scalar values to text.
    text_keys = (
        "resolver_version",
        "event_family",
        "source_size_unit",
        "source_unit_number",
        "owner_match_policy",
        "source_file_sha256",
        "source_area_field",
        "source_filename",
    )
    text_values = ", ".join(f"'{key}', document.value->>'{key}'" for key in text_keys)
    op.execute(
        f"""
        CREATE FUNCTION crm_owner_history_projection(source json) RETURNS jsonb
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
            WITH document AS MATERIALIZED (SELECT source::jsonb AS value)
            SELECT jsonb_strip_nulls(
                COALESCE((SELECT jsonb_object_agg(key, value)
                          FROM jsonb_each(document.value)
                          WHERE key IN ({history_keys})), '{{}}'::jsonb)
                || jsonb_build_object({text_values})
                || jsonb_build_object('source_fields',
                    COALESCE((SELECT jsonb_object_agg(key, value)
                              FROM jsonb_each(CASE
                                  WHEN jsonb_typeof(document.value->'source_fields') = 'object'
                                  THEN document.value->'source_fields' ELSE '{{}}'::jsonb END)
                              WHERE key IN ({source_keys})), '{{}}'::jsonb))
            ) FROM document
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION crm_owner_import_projection(source json) RETURNS jsonb
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
            WITH document AS MATERIALIZED (SELECT source::jsonb AS value)
            SELECT jsonb_build_object(
                'resolver_version', value->'resolver_version',
                'mode', value->'mode',
                'sheets', COALESCE((
                    SELECT jsonb_agg(jsonb_build_object(
                        'sheet_name', sheet->'sheet_name',
                        'field_map', sheet->'field_map'
                    ) ORDER BY ordinal)
                    FROM jsonb_array_elements(CASE
                        WHEN jsonb_typeof(value->'sheets') = 'array' THEN value->'sheets'
                        ELSE '[]'::jsonb END) WITH ORDINALITY AS sheets(sheet, ordinal)
                    WHERE jsonb_typeof(sheet) = 'object'
                ), '[]'::jsonb)
            ) FROM document
        $$
        """
    )
    for table, target in (
        ("crm_contact_imports", "owner_source_metadata"),
        ("crm_property_contact_claims", "owner_history_evidence"),
    ):
        op.add_column(
            table,
            sa.Column(
                target, postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
            ),
        )
    op.create_table(
        "crm_owner_assessment_revisions",
        sa.Column("organization_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("organization_id"),
    )
    # Sequence allocation is deliberately nontransactional. Rollback must not
    # reuse a revision token that a reader in that transaction already cached.
    op.execute("CREATE SEQUENCE crm_owner_assessment_revision_seq AS bigint")
    op.execute(
        "ALTER SEQUENCE crm_owner_assessment_revision_seq "
        "OWNED BY crm_owner_assessment_revisions.revision"
    )
    for table, source, target, function in (
        ("crm_contact_imports", "mapping", "owner_source_metadata", "crm_owner_import_projection"),
        (
            "crm_property_contact_claims",
            "evidence",
            "owner_history_evidence",
            "crm_owner_history_projection",
        ),
    ):
        op.execute(
            f"""
            CREATE FUNCTION {function}_write() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                NEW.{target} := {function}(NEW.{source});
                RETURN NEW;
            END $$
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER owner_source_projection BEFORE INSERT OR UPDATE OF {source}, {target}
            ON {table} FOR EACH ROW EXECUTE FUNCTION {function}_write()
            """
        )
        op.execute(f"UPDATE {table} SET {target} = {target}")
    op.execute(
        """
        CREATE FUNCTION crm_owner_revision_write() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                INSERT INTO crm_owner_assessment_revisions (organization_id, revision)
                SELECT organization_id, nextval('crm_owner_assessment_revision_seq')
                FROM (SELECT DISTINCT organization_id FROM owner_new_rows ORDER BY 1) organizations
                ON CONFLICT (organization_id) DO UPDATE SET revision = EXCLUDED.revision;
            ELSIF TG_OP = 'DELETE' THEN
                INSERT INTO crm_owner_assessment_revisions (organization_id, revision)
                SELECT organization_id, nextval('crm_owner_assessment_revision_seq')
                FROM (SELECT DISTINCT organization_id FROM owner_old_rows ORDER BY 1) organizations
                ON CONFLICT (organization_id) DO UPDATE SET revision = EXCLUDED.revision;
            ELSIF TG_OP = 'UPDATE' THEN
                INSERT INTO crm_owner_assessment_revisions (organization_id, revision)
                SELECT organization_id, nextval('crm_owner_assessment_revision_seq')
                FROM (SELECT organization_id FROM owner_old_rows
                      UNION SELECT organization_id FROM owner_new_rows ORDER BY 1) organizations
                ON CONFLICT (organization_id) DO UPDATE SET revision = EXCLUDED.revision;
            ELSE
                INSERT INTO crm_owner_assessment_revisions (organization_id, revision)
                SELECT organization_id, nextval('crm_owner_assessment_revision_seq')
                FROM crm_owner_assessment_revisions ORDER BY organization_id
                ON CONFLICT (organization_id) DO UPDATE SET revision = EXCLUDED.revision;
            END IF;
            RETURN NULL;
        END $$
        """
    )
    for table in _TABLES:
        for event, references in (
            ("INSERT", "NEW TABLE AS owner_new_rows"),
            ("DELETE", "OLD TABLE AS owner_old_rows"),
            ("UPDATE", "OLD TABLE AS owner_old_rows NEW TABLE AS owner_new_rows"),
        ):
            op.execute(
                f"CREATE TRIGGER owner_revision_{event.lower()} AFTER {event} ON {table} "
                f"REFERENCING {references} FOR EACH STATEMENT "
                "EXECUTE FUNCTION crm_owner_revision_write()"
            )
        op.execute(
            f"CREATE TRIGGER owner_revision_truncate AFTER TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION crm_owner_revision_write()"
        )
    # CREATE TRIGGER/ALTER TABLE locks keep concurrent writers out until commit;
    # include preexisting lists/imports even where there are currently no claims.
    op.execute(
        """
        INSERT INTO crm_owner_assessment_revisions (organization_id, revision)
        SELECT organization_id, nextval('crm_owner_assessment_revision_seq')
        FROM (
            SELECT organization_id FROM crm_contact_imports
            UNION SELECT organization_id FROM crm_contact_lists
            UNION SELECT organization_id FROM crm_property_contact_claims
            ORDER BY 1
        ) organizations
        ON CONFLICT (organization_id) DO UPDATE SET revision = EXCLUDED.revision
        """
    )


def downgrade() -> None:
    for table in _TABLES:
        for event in ("insert", "delete", "update", "truncate"):
            op.execute(f"DROP TRIGGER owner_revision_{event} ON {table}")
    op.execute("DROP FUNCTION crm_owner_revision_write()")
    for table, target, function in (
        ("crm_contact_imports", "owner_source_metadata", "crm_owner_import_projection"),
        ("crm_property_contact_claims", "owner_history_evidence", "crm_owner_history_projection"),
    ):
        op.execute(f"DROP TRIGGER owner_source_projection ON {table}")
        op.execute(f"DROP FUNCTION {function}_write()")
        op.drop_column(table, target)
        op.execute(f"DROP FUNCTION {function}(json)")
    op.drop_table("crm_owner_assessment_revisions")
