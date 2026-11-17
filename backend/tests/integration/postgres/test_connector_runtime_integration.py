"""Qualify the retained migration against a fresh disposable current-VV schema."""

import sqlalchemy as sa


async def test_migration_retains_deployed_state_and_excludes_unshipped_connector_tables(pg_session):
    connection = await pg_session.connection()

    def inspect(sync):
        inspector = sa.inspect(sync)
        tables = set(inspector.get_table_names())
        assert {"conversations", "assistant_actions", "whatsapp_connections"} <= tables
        assert not any(
            table.startswith(("crm_assistant_", "crm_whatsapp_", "crm_calendar_"))
            for table in tables
        )
        claim_columns = {
            column["name"]: column
            for column in inspector.get_columns("crm_property_contact_claims")
        }
        for name in ("estimated_value_aed", "estimated_value_low_aed", "estimated_value_high_aed"):
            assert isinstance(claim_columns[name]["type"], sa.BigInteger)
            assert claim_columns[name]["nullable"]
        assert not claim_columns["valuation"]["nullable"]
        registry_columns = {
            column["name"]: column
            for column in inspector.get_columns("crm_owner_registry_properties")
        }
        assert isinstance(registry_columns["estimated_value_aed"]["type"], sa.BigInteger)
        assert registry_columns["estimated_value_aed"]["nullable"]
        assert sync.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all() == [
            "b5e2c9a7d4f1"
        ]

    await connection.run_sync(inspect)
