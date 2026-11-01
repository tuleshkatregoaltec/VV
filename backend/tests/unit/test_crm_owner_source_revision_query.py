"""A warm owner read must not scale its source-validation work with claim count."""

from sqlalchemy.dialects import postgresql

from app.crm import owner_assessment, owner_repository


async def test_source_revision_uses_one_tenant_key_lookup():
    statements = []

    class Result:
        def first(self):
            return 123456789012345678

    class Session:
        async def exec(self, statement):
            statements.append(statement)
            return Result()

    assert await owner_assessment._source_revision(Session(), "tenant-A") == "123456789012345678"
    assert len(statements) == 1
    query = str(statements[0].compile(dialect=postgresql.dialect()))
    assert "crm_owner_assessment_revisions.organization_id =" in query
    assert "crm_property_contact_claims" not in query
    assert "crm_contact_imports" not in query
    assert "crm_contact_lists" not in query


async def test_empty_tenant_has_a_stable_zero_token_without_creating_state():
    class Result:
        def first(self):
            return None

    class Session:
        async def exec(self, statement):
            return Result()

    assert await owner_repository.owner_assessment_revision(Session(), "empty-tenant") == 0
