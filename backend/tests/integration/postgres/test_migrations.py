import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def repair(connection):
    path = (
        Path(__file__).parents[3]
        / "migrations/versions/a34d19c0b621_restore_conversation_org_column.py"
    )
    spec = importlib.util.spec_from_file_location("conversation_repair", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    module.upgrade()


async def test_repair_refuses_to_guess_historical_tenant_ownership(pg_session):
    connection = await pg_session.connection()

    def verify(sync):
        sync.execute(sa.text("DROP TABLE conversations CASCADE"))
        sync.execute(
            sa.text("CREATE TABLE conversations (id integer PRIMARY KEY, user_id varchar NOT NULL)")
        )
        sync.execute(sa.text("INSERT INTO conversations VALUES (1, 'legacy-user')"))
        with pytest.raises(RuntimeError, match="historical organization assignment"):
            repair(sync)
        assert sync.execute(sa.text("SELECT user_id FROM conversations")).scalar() == "legacy-user"
        assert "organization_id" not in {
            column["name"] for column in sa.inspect(sync).get_columns("conversations")
        }

    try:
        await connection.run_sync(verify)
    finally:
        await pg_session.rollback()  # PostgreSQL restores all test-only DDL too.


async def test_repair_preserves_an_existing_organization_assignment(pg_session):
    connection = await pg_session.connection()

    def verify(sync):
        sync.execute(
            sa.text(
                "INSERT INTO conversations (user_id, organization_id, created_at, updated_at) VALUES ('legacy-user', 'historical-org', now(), now())"
            )
        )
        repair(sync)
        repair(sync)
        assert (
            sync.execute(
                sa.text("SELECT organization_id FROM conversations WHERE user_id='legacy-user'")
            ).scalar()
            == "historical-org"
        )

    try:
        await connection.run_sync(verify)
    finally:
        await pg_session.rollback()
