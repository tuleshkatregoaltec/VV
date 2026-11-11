"""Real committed source changes must invalidate every owner cache consumer."""

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import owner_assessment, owner_repository
from app.crm.import_models import CrmContactImport, CrmContactList, CrmPropertyContactClaim


async def seed(session, *, count=1, evidence=None):
    now = datetime.now(timezone.utc)
    org = str(uuid4())
    source = CrmContactImport(
        organization_id=org,
        created_by_user_id="synthetic-user",
        name="Synthetic revision test",
        original_filename="synthetic.csv",
        sha256=uuid4().hex,
        size_bytes=1,
        mapping={"resolver_version": "test", "mode": "source_only", "sheets": []},
        created_at=now,
    )
    session.add(source)
    await session.flush()
    contact_list = CrmContactList(
        organization_id=org,
        created_by_user_id="synthetic-user",
        source_import_id=source.id,
        name="Synthetic list",
        created_at=now,
        updated_at=now,
    )
    session.add(contact_list)
    await session.flush()
    claims = []
    for number in range(count):
        claim = CrmPropertyContactClaim(
            organization_id=org,
            import_id=source.id,
            list_id=contact_list.id,
            source_sheet="Owners",
            source_row_number=number + 1,
            row_fingerprint=str(number),
            owner_key="synthetic-owner",
            property_key=f"synthetic-tower|{number}",
            contact_name="Synthetic contact",
            ownership_status="unmatched",
            confidence_score=20,
            match_reason="Synthetic evidence",
            evidence=evidence or {},
            created_at=now,
            updated_at=now + timedelta(minutes=number),
        )
        session.add(claim)
        claims.append(claim)
    await session.commit()
    return org, source, contact_list, claims


async def revision(session, org):
    return await owner_assessment._source_revision(session, org)


async def test_late_commit_and_rollback_cannot_publish_stale_source_cache(pg_session):
    """An uncommitted source cache cannot collide with a later committed token."""
    org, _, _, claims = await seed(pg_session, count=2)
    initial = await revision(pg_session, org)
    await owner_assessment._source_rows(pg_session, org, initial)
    async with AsyncSession(pg_session.bind) as writer:
        await writer.exec(
            text("UPDATE crm_property_contact_claims SET confidence_score=31 WHERE id=:id"),
            params={"id": claims[0].id},
        )
        uncommitted = await revision(writer, org)
        assert uncommitted != initial
        assert await revision(pg_session, org) == initial
        uncommitted_rows = await owner_assessment._source_rows(writer, org, uncommitted)
        assert (
            next(row for row in uncommitted_rows if row["id"] == claims[0].id)["confidence_score"]
            == 31
        )
        await writer.rollback()
        assert await revision(pg_session, org) == initial
        await writer.exec(
            text("UPDATE crm_property_contact_claims SET confidence_score=42 WHERE id=:id"),
            params={"id": claims[0].id},
        )
        # The oldest business timestamp changes; the newer row and count do not.
        assert await revision(pg_session, org) == initial
        await writer.commit()
    committed = await revision(pg_session, org)
    assert committed not in {initial, uncommitted}
    rows = await owner_assessment._source_rows(pg_session, org, committed)
    assert next(row for row in rows if row["id"] == claims[0].id)["confidence_score"] == 42
    assert (
        next(row for row in rows if row["id"] == claims[0].id)["updated_at"] == claims[0].updated_at
    )


async def test_direct_writers_replay_delete_and_tenant_reassignment_invalidate(pg_session):
    org, source, contact_list, claims = await seed(pg_session)
    other = str(uuid4())
    unrelated = str(uuid4())
    assert await revision(pg_session, other) == "0"
    assert await revision(pg_session, unrelated) == "0"
    previous = await revision(pg_session, org)
    # Direct SQL replay changes evidence without touching a business timestamp.
    await pg_session.exec(
        text("UPDATE crm_property_contact_claims SET evidence=CAST(:value AS json) WHERE id=:id"),
        params={"id": claims[0].id, "value": json.dumps({"source_fields": {"size_sqft": "123"}})},
    )
    await pg_session.commit()
    current = await revision(pg_session, org)
    assert current != previous
    assert (await owner_repository.list_owner_history_rows(pg_session, organization_id=org))[0][
        "source_size_sqft"
    ] == "123"
    for table, identifier in (
        ("crm_contact_imports", source.id),
        ("crm_contact_lists", contact_list.id),
        ("crm_property_contact_claims", claims[0].id),
    ):
        before = (await revision(pg_session, org), await revision(pg_session, other))
        await pg_session.exec(
            text(f"UPDATE {table} SET organization_id=:other WHERE id=:id"),
            params={"id": identifier, "other": other},
        )
        await pg_session.commit()
        assert await revision(pg_session, org) != before[0]
        assert await revision(pg_session, other) != before[1]
        assert await revision(pg_session, unrelated) == "0"
    assert await owner_repository.list_owner_history_rows(pg_session, organization_id=org) == []
    assert (
        len(await owner_repository.list_owner_history_rows(pg_session, organization_id=other)) == 1
    )
    before_delete = await revision(pg_session, other)
    await pg_session.exec(
        text("DELETE FROM crm_contact_imports WHERE id=:id"), params={"id": source.id}
    )
    await pg_session.commit()
    assert await revision(pg_session, other) != before_delete
    assert await owner_repository.list_owner_history_rows(pg_session, organization_id=other) == []


async def test_bulk_statement_allocates_one_revision_per_tenant(pg_session):
    """A 100k-row import must not update the same tenant revision 100k times."""
    org, _, _, _ = await seed(pg_session, count=12)
    before = (
        await pg_session.exec(text("SELECT last_value FROM crm_owner_assessment_revision_seq"))
    ).scalar()
    await pg_session.exec(
        text(
            "UPDATE crm_property_contact_claims SET confidence_score=21 WHERE organization_id=:org"
        ),
        params={"org": org},
    )
    after = (
        await pg_session.exec(text("SELECT last_value FROM crm_owner_assessment_revision_seq"))
    ).scalar()
    assert after == before + 1
    await pg_session.rollback()


async def test_projection_cannot_be_overridden_and_source_modes_stay_tenant_scoped(pg_session):
    org, source, _, claims = await seed(pg_session, evidence={"source_fields": {"size_sqm": "10"}})
    assert await owner_repository.owner_sources_only(pg_session, org)
    await pg_session.exec(
        text("UPDATE crm_property_contact_claims SET owner_history_evidence='{}' WHERE id=:id"),
        params={"id": claims[0].id},
    )
    await pg_session.exec(
        text("UPDATE crm_contact_imports SET owner_source_metadata='{}' WHERE id=:id"),
        params={"id": source.id},
    )
    await pg_session.commit()
    row = (await owner_repository.list_owner_history_rows(pg_session, organization_id=org))[0]
    assert row["evidence"]["source_fields"] == {"size_sqm": "10"}
    assert row["import_resolver_version"] == "test"
    assert await owner_repository.owner_sources_only(pg_session, org)
    assert not await owner_repository.owner_sources_only(pg_session, str(uuid4()))
    await pg_session.exec(
        text("UPDATE crm_contact_imports SET mapping='{}' WHERE id=:id"), params={"id": source.id}
    )
    await pg_session.commit()
    assert not await owner_repository.owner_sources_only(pg_session, org)


async def test_private_truncate_cannot_bypass_audit_or_change_revision(pg_session):
    org, _, _, _ = await seed(pg_session)
    before = await revision(pg_session, org)
    # The revision trigger supports truncate for controlled schema maintenance, but
    # the final audit policy rejects unauditable private-store bulk removal.
    with pytest.raises(DBAPIError, match="cannot be truncated"):
        await pg_session.exec(text("TRUNCATE crm_property_contact_claims"))
    await pg_session.rollback()
    assert await revision(pg_session, org) == before


async def test_migration_backfills_without_changing_original_audit_documents(pg_session):
    """Upgrade an old populated schema; downgrade/reupgrade is isolated and rolled back."""
    evidence = {"source_fields": {"size_sqft": "10", "private": "preserved"}, "legacy": [None, 1]}
    org, source, _, claims = await seed(pg_session, evidence=evidence)
    connection = await pg_session.connection()

    def check(sync):
        path = (
            Path(__file__).parents[3]
            / "migrations/versions/b6c2e9a4f871_compact_owner_sources_and_revisions.py"
        )
        spec = importlib.util.spec_from_file_location("owner_source_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.op = Operations(MigrationContext.configure(sync))
        original = sync.execute(
            text("SELECT evidence::text FROM crm_property_contact_claims WHERE id=:id"),
            {"id": claims[0].id},
        ).scalar_one()
        mapping = sync.execute(
            text("SELECT mapping::text FROM crm_contact_imports WHERE id=:id"), {"id": source.id}
        ).scalar_one()
        migration.downgrade()
        migration.upgrade()
        assert (
            sync.execute(
                text("SELECT evidence::text FROM crm_property_contact_claims WHERE id=:id"),
                {"id": claims[0].id},
            ).scalar_one()
            == original
        )
        assert (
            sync.execute(
                text("SELECT mapping::text FROM crm_contact_imports WHERE id=:id"),
                {"id": source.id},
            ).scalar_one()
            == mapping
        )
        assert sync.execute(
            text("SELECT owner_history_evidence FROM crm_property_contact_claims WHERE id=:id"),
            {"id": claims[0].id},
        ).scalar_one() == {"source_fields": {"size_sqft": "10"}}
        assert (
            sync.execute(
                text(
                    "SELECT revision FROM crm_owner_assessment_revisions WHERE organization_id=:org"
                ),
                {"org": org},
            ).scalar_one()
            > 0
        )

    try:
        await connection.run_sync(check)
    finally:
        await pg_session.rollback()


def legacy_projection_sql():
    return (Path(__file__).parent / "fixtures/owner_history_legacy_projection.sql").read_text()


async def test_compact_projection_matches_the_original_source_field_contract(pg_session):
    """Freeze old SQL semantics, including recursive null removal and broker evidence."""
    evidence = {
        "resolver_version": "original-resolver",
        "event_family": "sale",
        "scoped_identity_collision": False,
        "cadastral_identity": {"property_key": "test-key", "nested_null": None},
        "source_size_unit": "sqm",
        "source_fields": {
            "size_sqft": "123.456",
            "size_sqm": "11.469",
            "size_unknown": "12",
            "property_type": "Apartment",
            "unit_number": "001",
            "area_name": "Synthetic Area",
            "master_project": "Synthetic Master",
            "project_name": "Synthetic Project",
            "building_name": "Synthetic Tower",
            "building_number": "01",
            "property_number": "0002",
            "plot_number": "0003",
            "plot_pre_reg_number": "0004",
            "transaction_price_aed": "1000000.50",
            "unselected_private_field": "kept only in original",
        },
        "original_identifiers": {"unit_number": "0001", "nullable": None},
        "original_property_fields": {"building_name": "Old label"},
        "inferred_size_unit": {"value": "sqm"},
        "amount_first_match": {"amount": 1000000.5},
        "property_identity_match": {"nested": [None, {"missing": None, "yes": True}]},
        "owner_match_policy": "original",
        "source_file_sha256": "test-sha",
        "source_identifiers": ["001", None],
        "source_area_field": "Area",
        "source_filename": "evidence.csv",
        "address_recovery": {"status": "resolved"},
        "inferred_file_context": {"area": "Synthetic Area"},
        "source_registry_location_resolution": {"status": "resolved"},
        "property_identity_resolution": {"score": 90},
        "file_context": {"nested": [1, None, {"value": True}]},
        "registry_unit_fallback": {"original": "001"},
        "unit_hierarchy_resolution": {"score": 91},
        "source_unit_number": "001",
        "duplicate_count": 2,
        "source_audit": {"version": "source-only", "nested": [None, {"empty": None}]},
        "owner_match": {"status": "matched", "role": "lender"},
        "broker_contact": {"excluded": True, "reason": "licensed broker"},
        "unselected_original_blob": "preserved outside projection",
    }
    org, source, _, claims = await seed(pg_session, evidence=evidence)
    parameters = {"org": org, "import_id": source.id}
    old = dict(
        (await pg_session.exec(text(legacy_projection_sql()), params=parameters)).mappings().one()
    )
    old_evidence = json.loads(old.pop("history_evidence_json"))
    old_evidence.update(
        event_family=old["event_family"], scoped_identity_collision=old["identity_collision"]
    )
    new = (await owner_repository.list_owner_history_rows(pg_session, organization_id=org))[0]
    assert new["evidence"] == old_evidence
    assert new["claim_resolver_version"] == old["claim_resolver_version"]
    assert new["cadastral_key"] == old["cadastral_key"]
    assert new["identity_collision"] == old["identity_collision"]
    assert claims[0].evidence == evidence
    for value in (
        {},
        {"source_fields": None},
        {"source_fields": {"size_sqft": None}},
        {"source_unit_number": 17, "owner_match_policy": 19, "source_filename": 23},
    ):
        await pg_session.exec(
            text(
                "UPDATE crm_property_contact_claims SET evidence=CAST(:value AS json) WHERE id=:id"
            ),
            params={"id": claims[0].id, "value": json.dumps(value)},
        )
        old = (
            (await pg_session.exec(text(legacy_projection_sql()), params=parameters))
            .mappings()
            .one()
        )
        new = (await owner_repository.list_owner_history_rows(pg_session, organization_id=org))[0]
        assert new["evidence"] == json.loads(old["history_evidence_json"])
    await pg_session.rollback()


async def test_bounded_projection_profile_avoids_large_original_json(pg_session, capsys):
    """Measure the reachable projection on a disposable synthetic TOAST-sized source."""
    import random

    from sqlalchemy.dialects import postgresql

    # Deterministic incompressible padding represents unselected original evidence.
    evidence = {
        "source_fields": {"size_sqft": "123.45", "unit_number": "001"},
        "source_audit": {"mode": "source_only", "reference_count": 1},
        "raw_unselected_evidence": random.Random(0).randbytes(8192).hex(),
    }
    org, source, _, _ = await seed(pg_session, count=1000, evidence=evidence)
    parameters = {"org": org, "import_id": source.id}
    statements = []

    class CapturedRows:
        def all(self):
            from types import SimpleNamespace

            return [
                SimpleNamespace(
                    id=source.id,
                    original_filename="synthetic.csv",
                    sheets=[],
                    resolver_version="test",
                )
            ]

        def keys(self):
            return []

        def __iter__(self):
            return iter(())

    class Capture:
        async def exec(self, statement):
            statements.append(statement)
            return CapturedRows()

    await owner_repository.list_owner_history_rows(Capture(), organization_id=org)
    compact = str(
        statements[-1].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    size = (
        await pg_session.exec(
            text(
                "SELECT avg(pg_column_size(evidence)), avg(pg_column_size(owner_history_evidence)) FROM crm_property_contact_claims WHERE organization_id=:org"
            ),
            params={"org": org},
        )
    ).one()
    old_plan = (
        await pg_session.exec(
            text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + legacy_projection_sql()),
            params=parameters,
        )
    ).scalar_one()[0]
    new_plan = (
        await pg_session.exec(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + compact))
    ).scalar_one()[0]
    assert size[1] < size[0] / 20
    assert old_plan["Plan"]["Actual Rows"] == new_plan["Plan"]["Actual Rows"] == 1000
    assert "json_to_record" not in compact
    assert "crm_property_contact_claims.evidence" not in compact
    with capsys.disabled():
        print(
            f"\nSynthetic 1000-row source: original/projection bytes={float(size[0]):.0f}/{float(size[1]):.0f}; legacy/compact SQL={old_plan['Execution Time']:.3f}/{new_plan['Execution Time']:.3f}ms"
        )
    await pg_session.rollback()


async def test_concurrent_tenant_writers_serialize_revision_without_losing_either_commit(
    pg_session,
):
    """A later commit cannot leave either source change under an already cached token."""
    import asyncio

    org, source, _, claims = await seed(pg_session)
    initial = await revision(pg_session, org)
    async with AsyncSession(pg_session.bind) as first, AsyncSession(pg_session.bind) as second:
        await first.exec(
            text("UPDATE crm_property_contact_claims SET confidence_score=31 WHERE id=:id"),
            params={"id": claims[0].id},
        )
        first_token = await revision(first, org)
        competing = asyncio.create_task(
            second.exec(
                text("UPDATE crm_contact_imports SET original_filename='later.csv' WHERE id=:id"),
                params={"id": source.id},
            )
        )
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(competing), timeout=0.1)
            assert await revision(pg_session, org) == initial
            await first.commit()
            await asyncio.wait_for(competing, timeout=5)
            assert await revision(pg_session, org) == first_token
            await second.commit()
        finally:
            if not competing.done():
                competing.cancel()
                await asyncio.gather(competing, return_exceptions=True)
    final_token = await revision(pg_session, org)
    assert final_token not in {initial, first_token}
    row = (await owner_assessment._source_rows(pg_session, org, final_token))[0]
    assert row["confidence_score"] == 31
    assert row["source_filename"] == "later.csv"


async def test_scoped_history_rows_read_only_the_requested_units_and_their_properties(pg_session):
    """The workspace list needs a few units' owners, not the organization's 311k claims."""
    org, _, _, claims = await seed(pg_session, count=6)
    for claim, (unit, prop, owner) in zip(
        claims,
        [
            ("unit-a", "tower|a", "one"),
            (None, "tower|a", "two"),  # a competing owner on the same property
            ("unit-b", "tower|b", "one"),
            ("unit-c", "tower|c", "one"),  # not requested
            (None, "tower|d", "one"),  # not requested
            ("unit-a", "tower|e", "three"),  # same unit, second property key
        ],
        strict=True,
    ):
        claim.unit_candidate_key, claim.property_key, claim.owner_key = unit, prop, owner
    await pg_session.commit()
    other_org, *_ = await seed(pg_session, count=1)
    other = (
        await pg_session.exec(
            text(
                "UPDATE crm_property_contact_claims SET unit_candidate_key='unit-a', property_key='tower|a' WHERE organization_id=:o RETURNING id"
            ),
            params={"o": other_org},
        )
    ).all()
    assert other
    await pg_session.commit()

    rows = await owner_repository.list_owner_history_rows(
        pg_session, organization_id=org, unit_candidate_keys=["unit-b", "unit-a", "unit-a"]
    )
    assert sorted((row["property_key"], row["owner_key"]) for row in rows) == [
        ("tower|a", "one"),
        ("tower|a", "two"),
        ("tower|b", "one"),
        ("tower|e", "three"),
    ]
    assert (
        await owner_repository.list_owner_history_rows(
            pg_session, organization_id=org, unit_candidate_keys=[]
        )
        == []
    )
    assert len(await owner_repository.list_owner_history_rows(pg_session, organization_id=org)) == 6
