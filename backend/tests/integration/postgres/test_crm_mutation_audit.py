"""Real migrated PostgreSQL: private writes and their metadata commit together."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.crm.inbound_models import CrmInboundContact
from app.postgres.actor_context import install_actor_context, transaction_actor


@pytest.fixture
async def audit_session(pg_session):
    install_actor_context(pg_session.bind)
    yield pg_session


async def contacts(session, org, count=1):
    await session.exec(
        text("""
            INSERT INTO crm_inbound_contacts (
                organization_id, full_name, phone, email, consent_status, do_not_contact,
                created_at, updated_at
            ) SELECT :org, 'PRIVATE ORIGINAL NAME', '+971501234567', 'private@example.invalid',
                'unknown', false, now(), now() FROM generate_series(1, :count)
        """),
        params={"org": org, "count": count},
    )
    await session.commit()


async def events(session, org):
    result = await session.exec(
        text("SELECT * FROM public.crm_mutation_audit WHERE organization_id=:org ORDER BY id"),
        params={"org": org},
    )
    return [dict(row) for row in result.mappings()]


async def test_bulk_direct_sql_aggregates_org_counts_and_never_copies_contact_values(audit_session):
    org = str(uuid4())
    await contacts(audit_session, org, count=1000)
    initial = await events(audit_session, org)
    assert len(initial) == 1
    assert initial[0]["row_count"] == 1000
    assert initial[0]["action"] == "INSERT"
    assert initial[0]["actor_kind"] == "database"
    assert initial[0]["actor_id"] == initial[0]["database_actor"]
    assert initial[0]["request_id"] is None
    # An older value edit must be recorded even when business timestamps do not change.
    await audit_session.exec(
        text("UPDATE crm_inbound_contacts SET full_name='PRIVATE EDIT' WHERE organization_id=:org"),
        params={"org": org},
    )
    await audit_session.commit()
    await audit_session.exec(
        text("DELETE FROM crm_inbound_contacts WHERE organization_id=:org"), params={"org": org}
    )
    await audit_session.commit()
    records = await events(audit_session, org)
    assert [(record["action"], record["row_count"]) for record in records] == [
        ("INSERT", 1000),
        ("UPDATE", 1000),
        ("DELETE", 1000),
    ]
    assert {record["resource"] for record in records} == {"crm_inbound_contacts"}
    assert {record["outcome"] for record in records} == {"success"}
    assert set(records[0]) == {
        "id",
        "organization_id",
        "actor_id",
        "actor_kind",
        "database_actor",
        "request_id",
        "action",
        "resource",
        "outcome",
        "row_count",
        "occurred_at",
    }
    payload = json.dumps(records, default=str)
    for private in ("PRIVATE", "+971501234567", "private@example.invalid"):
        assert private not in payload


async def test_actor_survives_orm_service_commits_and_does_not_leak_to_pool(audit_session):
    from datetime import datetime, timezone

    org, actor, request = (str(uuid4()) for _ in range(3))
    now = datetime.now(timezone.utc)
    with transaction_actor(actor_id=actor, organization_id=org, request_id=request):
        contact = CrmInboundContact(
            organization_id=org, full_name="PRIVATE ORM", created_at=now, updated_at=now
        )
        audit_session.add(contact)
        await audit_session.commit()
        contact.full_name = "PRIVATE AFTER COMMIT"
        audit_session.add(contact)
        await audit_session.commit()
    records = await events(audit_session, org)
    assert len(records) == 2
    assert {(row["actor_id"], row["request_id"], row["actor_kind"]) for row in records} == {
        (actor, request, "user")
    }
    await audit_session.rollback()
    await contacts(audit_session, org)
    records = await events(audit_session, org)
    assert records[-1]["actor_kind"] == "database"
    assert records[-1]["request_id"] is None
    assert records[-1]["actor_id"] == records[-1]["database_actor"]


async def test_rollback_discards_audit_and_audit_failure_rolls_back_private_write(audit_session):
    org = str(uuid4())
    await contacts(audit_session, org)
    await audit_session.exec(
        text("UPDATE crm_inbound_contacts SET full_name='ROLLED BACK' WHERE organization_id=:org"),
        params={"org": org},
    )
    assert len(await events(audit_session, org)) == 2
    await audit_session.rollback()
    assert len(await events(audit_session, org)) == 1
    # Simulate an unavailable/rejecting audit store using transactional test-only DDL.
    await audit_session.exec(
        text(
            "ALTER TABLE crm_mutation_audit ADD CONSTRAINT test_audit_unavailable "
            "CHECK (action <> 'UPDATE') NOT VALID"
        )
    )
    with pytest.raises(DBAPIError, match="test_audit_unavailable"):
        await audit_session.exec(
            text(
                "UPDATE crm_inbound_contacts SET full_name='CANNOT COMMIT' WHERE organization_id=:org"
            ),
            params={"org": org},
        )
    await audit_session.rollback()
    names = (
        (
            await audit_session.exec(
                text("SELECT full_name FROM crm_inbound_contacts WHERE organization_id=:org"),
                params={"org": org},
            )
        )
        .scalars()
        .all()
    )
    assert names == ["PRIVATE ORIGINAL NAME"]
    assert len(await events(audit_session, org)) == 1


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE crm_mutation_audit SET actor_id='spoofed'",
        "DELETE FROM crm_mutation_audit",
        "TRUNCATE crm_mutation_audit",
        "INSERT INTO crm_mutation_audit (organization_id, actor_id, actor_kind, database_actor, "
        "action, resource, row_count) VALUES ('spoof', 'spoof', 'user', 'spoof', 'INSERT', 'spoof', 1)",
        "TRUNCATE crm_inbound_contacts CASCADE",
    ],
)
async def test_direct_sql_cannot_change_or_forge_audit_or_bypass_it(audit_session, statement):
    with pytest.raises(DBAPIError, match="CRM audit"):
        await audit_session.exec(text(statement))
    await audit_session.rollback()


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE crm_inbound_contacts SET full_name='CROSS ORG' WHERE organization_id IN (:org, :other)",
        "UPDATE crm_inbound_contacts SET organization_id=:other WHERE organization_id=:org",
        "UPDATE crm_inbound_contacts SET organization_id=:org WHERE organization_id=:other",
        "DELETE FROM crm_inbound_contacts WHERE organization_id=:other",
        "INSERT INTO crm_inbound_contacts (organization_id, full_name, consent_status, do_not_contact, "
        "created_at, updated_at) VALUES (:other, 'CROSS ORG', 'unknown', false, now(), now())",
    ],
)
async def test_actor_mismatch_rejects_entire_statement_for_old_and_new_orgs(
    audit_session, mutation
):
    org, other = str(uuid4()), str(uuid4())
    await contacts(audit_session, org)
    await contacts(audit_session, other)
    with transaction_actor(actor_id="test-actor", organization_id=org, request_id=uuid4().hex):
        with pytest.raises(DBAPIError, match="organization does not match"):
            await audit_session.exec(text(mutation), params={"org": org, "other": other})
        await audit_session.rollback()
    for tenant in (org, other):
        assert [
            (row["action"], row["row_count"]) for row in await events(audit_session, tenant)
        ] == [("INSERT", 1)]
    assert (
        await audit_session.exec(
            text(
                "SELECT count(*) FROM crm_inbound_contacts WHERE organization_id IN (:org, :other) "
                "AND full_name='PRIVATE ORIGINAL NAME'"
            ),
            params={"org": org, "other": other},
        )
    ).scalar_one() == 2


async def test_system_writer_org_reassignment_records_both_affected_tenants(audit_session):
    org, other = str(uuid4()), str(uuid4())
    await contacts(audit_session, org)
    await audit_session.exec(
        text("UPDATE crm_inbound_contacts SET organization_id=:other WHERE organization_id=:org"),
        params={"org": org, "other": other},
    )
    await audit_session.commit()
    for tenant in (org, other):
        row = (await events(audit_session, tenant))[-1]
        assert (row["organization_id"], row["action"], row["row_count"]) == (tenant, "UPDATE", 1)
        assert row["actor_kind"] == "database"


async def test_every_private_store_has_statement_transition_and_no_truncate_triggers(audit_session):
    tables = (
        (
            await audit_session.exec(
                text("""
        SELECT table_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name LIKE 'crm_%'
        AND column_name='organization_id'
        AND table_name NOT IN ('crm_mutation_audit', 'crm_owner_assessment_revisions')
    """)
            )
        )
        .scalars()
        .all()
    )
    assert len(tables) >= 16
    for table in tables:
        triggers = (
            (
                await audit_session.exec(
                    text("""
            SELECT tgname, tgoldtable, tgnewtable, tgtype::int AS kind
            FROM pg_trigger WHERE tgrelid=CAST(:table AS regclass) AND NOT tgisinternal
            AND tgname LIKE 'crm_audit_%'
        """),
                    params={"table": table},
                )
            )
            .mappings()
            .all()
        )
        assert {row["tgname"] for row in triggers} == {
            "crm_audit_insert",
            "crm_audit_update",
            "crm_audit_delete",
        }, table
        assert all(not (row["kind"] & 1) for row in triggers), table
        assert all(row["tgoldtable"] or row["tgnewtable"] for row in triggers), table
        assert (
            await audit_session.exec(
                text("""
            SELECT count(*) FROM pg_trigger WHERE tgrelid=CAST(:table AS regclass)
            AND tgname='crm_no_truncate'
        """),
                params={"table": table},
            )
        ).scalar_one() == 1


async def test_incomplete_direct_database_actor_fails_closed(audit_session):
    org = str(uuid4())
    await contacts(audit_session, org)
    await audit_session.exec(text("SELECT set_config('app.actor_id', 'partial-user', true)"))
    with pytest.raises(DBAPIError, match="Incomplete CRM transaction actor"):
        await audit_session.exec(
            text("DELETE FROM crm_inbound_contacts WHERE organization_id=:org"),
            params={"org": org},
        )
    await audit_session.rollback()
    assert len(await events(audit_session, org)) == 1


async def test_temporary_relation_cannot_redirect_audit_sink(audit_session):
    org = str(uuid4())
    await audit_session.exec(
        text("CREATE TEMP TABLE crm_mutation_audit (LIKE public.crm_mutation_audit INCLUDING ALL)")
    )
    await contacts(audit_session, org)
    assert len(await events(audit_session, org)) == 1
    assert (
        await audit_session.exec(text("SELECT count(*) FROM pg_temp.crm_mutation_audit"))
    ).scalar_one() == 0
