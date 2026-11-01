"""Real commits prove recovery cannot duplicate or publish revoked tenant writes."""

import asyncio
import hashlib
import io
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException, UploadFile
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import import_job_repository as jobs
from app.crm import import_jobs, import_worker, imports, inbound_imports, source_audit
from app.crm.import_job_models import CrmImportJob, utcnow
from app.crm.import_models import CrmContactImport, CrmContactList, CrmPropertyContactClaim
from app.crm.inbound_models import CrmInboundEnquiry, CrmInboundImport
from app.organization.models import Organization, OrganizationMembership
from app.postgres.actor_context import install_actor_context

OWNER = b"NameEn,Mobile,Project,UnitNumber\nExample,0501111111,Cluster,101\n"
INBOUND = b"Full Name,Phone,Intent\nExample,0501111111,buy\n"


class Storage:
    bucket_name = "disposable-mocked-imports"

    def __init__(self):
        self.objects = {}
        self.deleted = []

    async def upload(self, key, data):
        self.objects[key] = data

    async def delete_many(self, keys):
        self.deleted.extend(keys)
        for key in keys:
            self.objects.pop(key, None)

    @asynccontextmanager
    async def client(self):
        yield self

    async def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        data = self.objects[Key]

        class Body:
            def __init__(self):
                self.stream = io.BytesIO(data)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def read(self, limit):
                return self.stream.read(limit)

        return {"ContentLength": len(data), "Body": Body()}


@pytest.fixture
async def durable(postgres_test_url, monkeypatch):
    engine = create_async_engine(postgres_test_url)
    install_actor_context(engine)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    storage = Storage()
    monkeypatch.setattr(import_jobs, "storage", lambda: storage)
    org, user = str(uuid4()), str(uuid4())
    async with factory() as db:
        # Each example owns this disposable queue; claims scan across tenants.
        await db.exec(delete(CrmImportJob))
        db.add(Organization(id=org, name="Disposable import tenant", subscription_status="active"))
        await db.flush()
        db.add(OrganizationMembership(organization_id=org, user_id=user))
        await db.commit()
    for method in (
        "prepare_file_context",
        "recover_from_file_context",
        "_recover_property_identity_from_transaction",
        "_recover_property_identity_from_near_transaction",
        "_apply_registry_unit_fallbacks",
        "_enrich_workspaces",
        "run_owner_matching",
    ):
        monkeypatch.setattr(imports, method, AsyncMock())
    monkeypatch.setattr(imports, "_sales_evidence", AsyncMock(return_value={}))
    monkeypatch.setattr(imports, "_rental_evidence", AsyncMock(return_value={}))
    monkeypatch.setattr(imports, "save_drop_log", AsyncMock(return_value=True))
    monkeypatch.setattr(imports, "_llm_mapping", AsyncMock(side_effect=lambda profile: profile))
    monkeypatch.setattr(inbound_imports, "_bulk_ownership_enrichments", AsyncMock(return_value={}))
    monkeypatch.setattr(inbound_imports, "_ai_extract", AsyncMock(return_value=({}, 1.0, [])))
    yield SimpleNamespace(factory=factory, storage=storage, org=org, user=user)
    await engine.dispose()


async def queue(d, *, kind="owner", data=None, **options):
    data = data if data is not None else INBOUND if kind == "inbound" else OWNER
    async with d.factory() as db:
        record = await import_jobs.enqueue(
            db,
            kind=kind,
            data=data,
            filename="leads.csv",
            name="Example",
            user_id=d.user,
            organization_id=d.org,
            **options,
        )
        return record.id


async def load(d, import_id, *, inbound=False):
    async with d.factory() as db:
        model = CrmInboundImport if inbound else CrmContactImport
        record = await db.get(model, import_id)
        job = await jobs.for_import(db, record) if record else None
        return record, job


@pytest.mark.parametrize("kind", ["owner", "inbound", "source_only"])
async def test_http_operation_queues_without_parsing(durable, monkeypatch, kind):
    d = durable
    if kind == "owner":
        monkeypatch.setattr(
            imports, "_inspect_csv", lambda *args: pytest.fail("HTTP parsed owner input")
        )
        execute = imports.process_contact_import
    elif kind == "inbound":
        monkeypatch.setattr(
            inbound_imports, "_file_rows", lambda *args: pytest.fail("HTTP parsed inbound input")
        )
        execute = inbound_imports.process_inbound_import
    else:
        monkeypatch.setattr(
            source_audit.SourceAuditPayload,
            "model_validate_json",
            lambda *args: pytest.fail("HTTP parsed JSON input"),
        )
        execute = source_audit.process_source_audit_import
    async with d.factory() as db:
        response = await execute(
            db,
            upload=UploadFile(filename="input.csv", file=io.BytesIO(OWNER)),
            name="Queued",
            user_id=d.user,
            organization_id=d.org,
        )
        record = await db.get(
            CrmInboundImport if kind == "inbound" else CrmContactImport, response.id
        )
        job = await jobs.for_import(db, record)
        assert response.status == "queued"
        assert job.input_sha256 == hashlib.sha256(OWNER).hexdigest()
        assert job.parameters["kind"] == kind
        assert d.storage.objects[job.input_object_key] == OWNER


async def test_two_tenants_have_independent_jobs_and_skip_locked_claims(durable):
    d = durable
    first = await queue(d)
    async with d.factory() as db:
        other = Organization(
            id=str(uuid4()), name="Other disposable tenant", subscription_status="active"
        )
        db.add(other)
        await db.commit()
    async with d.factory() as db:
        second = await import_jobs.enqueue(
            db,
            kind="owner",
            data=OWNER,
            filename="same.csv",
            name="Other",
            user_id=str(uuid4()),
            organization_id=other.id,
        )
    async with d.factory() as locked, d.factory() as claimant:
        row = (
            await locked.exec(
                select(CrmImportJob).where(CrmImportJob.owner_import_id == first).with_for_update()
            )
        ).one()
        claimed = await jobs.claim(claimant)
        assert claimed.owner_import_id == second.id
        assert claimed.organization_id == other.id
        first_job_id = row.id
        await locked.rollback()
    async with d.factory() as db:
        assert (await jobs.claim(db)).id == first_job_id


async def test_success_is_atomic_and_cannot_duplicate_on_repoll(durable):
    d = durable
    import_id = await queue(d)
    assert await import_worker.run_once(d.factory)
    record, job = await load(d, import_id)
    assert record.status == job.status == "completed"
    assert job.attempt_count == 1 and job.lease_token is None
    async with d.factory() as db:
        claims = (
            await db.exec(
                select(CrmPropertyContactClaim).where(
                    CrmPropertyContactClaim.import_id == import_id
                )
            )
        ).all()
        assert len(claims) == 1
    assert not await import_worker.run_once(d.factory)
    assert await queue(d) == import_id


async def test_expired_lease_reclaim_fences_late_publication(durable):
    d = durable
    import_id = await queue(d)
    async with d.factory() as db:
        first = await jobs.claim(db)
        old_token = first.lease_token
        first.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.add(first)
        await db.commit()
    async with d.factory() as late, d.factory() as current:
        late.add(
            CrmContactList(
                organization_id=d.org,
                created_by_user_id=d.user,
                source_import_id=import_id,
                name="Must roll back",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        reclaimed = await jobs.claim(current)
        assert reclaimed.id == first.id and reclaimed.lease_token != old_token
        with pytest.raises(jobs.LostImportLease):
            await jobs.publish(late, first.id, old_token)
        await late.rollback()
    async with d.factory() as db:
        assert not (
            await db.exec(
                select(CrmContactList).where(CrmContactList.source_import_id == import_id)
            )
        ).all()
        with pytest.raises(jobs.LostImportLease):
            await jobs.heartbeat(db, first.id, old_token, 120)


@pytest.mark.parametrize("revocation", ["membership", "subscription"])
async def test_removed_creator_or_inactive_tenant_cannot_process(durable, monkeypatch, revocation):
    d = durable
    import_id = await queue(d)
    async with d.factory() as db:
        if revocation == "membership":
            member = (
                await db.exec(
                    select(OrganizationMembership).where(OrganizationMembership.user_id == d.user)
                )
            ).one()
            await db.delete(member)
        else:
            org = await db.get(Organization, d.org)
            org.subscription_status = "canceled"
            db.add(org)
        await db.commit()
    read = AsyncMock(side_effect=AssertionError("Revoked job reached private input"))
    monkeypatch.setattr(import_worker, "read_input", read)
    await import_worker.run_once(d.factory)
    record, job = await load(d, import_id)
    assert record.status == job.status == "failed"
    assert "revoked" in job.last_error
    read.assert_not_awaited()


@pytest.mark.parametrize("corruption", ["missing", "checksum"])
async def test_missing_or_corrupt_input_is_terminal_and_visible(durable, corruption):
    d = durable
    import_id = await queue(d)
    _, job = await load(d, import_id)
    if corruption == "missing":
        d.storage.objects.pop(job.input_object_key)
    else:
        d.storage.objects[job.input_object_key] = b"x" * job.input_size_bytes
    await import_worker.run_once(d.factory)
    record, job = await load(d, import_id)
    assert record.status == job.status == "failed"
    assert "missing" in job.last_error if corruption == "missing" else "checksum" in job.last_error


async def test_retry_backoff_and_crash_exhaustion_reconcile_status(durable, monkeypatch):
    d = durable
    import_id = await queue(d)
    monkeypatch.setattr(
        import_worker,
        "read_input",
        AsyncMock(side_effect=ConnectionError("private dependency failure")),
    )
    await import_worker.run_once(d.factory)
    record, job = await load(d, import_id)
    assert record.status == job.status == "retry_wait"
    assert job.available_at > utcnow()
    assert not await import_worker.run_once(d.factory)
    async with d.factory() as db:
        pending = await db.get(CrmImportJob, job.id)
        pending.status = "processing"
        pending.attempt_count = pending.max_attempts
        pending.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.add(pending)
        await db.commit()
        assert await jobs.reconcile(db) == 1
    record, job = await load(d, import_id)
    assert record.status == job.status == "failed"


async def test_digest_race_removes_only_losing_private_object(durable, monkeypatch):
    d = durable
    arrived = 0
    ready = asyncio.Event()
    original = d.storage.upload

    async def upload(key, data):
        nonlocal arrived
        await original(key, data)
        arrived += 1
        if arrived == 2:
            ready.set()
        await ready.wait()

    monkeypatch.setattr(d.storage, "upload", upload)
    first, second = await asyncio.gather(queue(d), queue(d))
    assert first == second
    record, job = await load(d, first)
    assert record.status == "queued"
    assert list(d.storage.objects) == [job.input_object_key]
    assert len(d.storage.deleted) == 1
    assert job.input_object_key not in d.storage.deleted


async def test_mapping_and_campaign_semantics_are_preserved_on_dedup(durable):
    d = durable
    first = await queue(
        d, kind="inbound", campaign_context="Campaign A", mapping_override={"sheets": []}
    )
    assert (
        await queue(
            d, kind="inbound", campaign_context="campaign a", mapping_override={"sheets": []}
        )
        == first
    )
    assert (
        await queue(
            d, kind="inbound", campaign_context="Campaign B", mapping_override={"sheets": []}
        )
        != first
    )
    with pytest.raises(HTTPException) as error:
        await queue(
            d,
            kind="inbound",
            campaign_context="Campaign A",
            mapping_override={"sheets": [{"sheet": "changed"}]},
        )
    assert error.value.status_code == 409


async def test_database_failure_cleans_owned_upload(durable, monkeypatch):
    d = durable
    async with d.factory() as db:
        monkeypatch.setattr(
            db, "commit", AsyncMock(side_effect=RuntimeError("Database unavailable"))
        )
        with pytest.raises(RuntimeError):
            await import_jobs.enqueue(
                db,
                kind="owner",
                data=OWNER,
                filename="owner.csv",
                name="Example",
                user_id=d.user,
                organization_id=d.org,
            )
    assert not d.storage.objects
    assert len(d.storage.deleted) == 1


async def test_deleted_import_cascades_job_and_stale_worker_cannot_recreate(durable, monkeypatch):
    d = durable
    import_id = await queue(d)
    async with d.factory() as db:
        claimed = await jobs.claim(db)
    monkeypatch.setattr(imports, "delete_drop_log", AsyncMock())
    async with d.factory() as db:
        await imports.delete_contact_import(db, import_id=import_id, organization_id=d.org)
    async with d.factory() as db:
        assert await db.get(CrmImportJob, claimed.id) is None
        assert await db.get(CrmContactImport, import_id) is None
        with pytest.raises(jobs.LostImportLease):
            await jobs.publish(db, claimed.id, claimed.lease_token)
    assert not d.storage.objects


async def test_publication_rechecks_revocation_after_processing(durable):
    d = durable
    import_id = await queue(d)
    async with d.factory() as db:
        claimed = await jobs.claim(db)
    async with d.factory() as revoked:
        membership = (
            await revoked.exec(
                select(OrganizationMembership).where(OrganizationMembership.user_id == d.user)
            )
        ).one()
        await revoked.delete(membership)
        await revoked.commit()
    async with d.factory() as late:
        late.add(
            CrmContactList(
                organization_id=d.org,
                created_by_user_id=d.user,
                source_import_id=import_id,
                name="No unauthorized result",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        with pytest.raises(jobs.ImportAuthorizationRevoked):
            await jobs.publish(late, claimed.id, claimed.lease_token)
        await late.rollback()
    async with d.factory() as db:
        assert not (
            await db.exec(
                select(CrmContactList).where(CrmContactList.source_import_id == import_id)
            )
        ).all()


async def test_inbound_worker_publishes_once_with_original_campaign(durable):
    d = durable
    import_id = await queue(d, kind="inbound", campaign_context="Campaign provenance")
    await import_worker.run_once(d.factory)
    record, job = await load(d, import_id, inbound=True)
    assert record.status == job.status == "completed"
    assert record.mapping["campaign_context"] == "Campaign provenance"
    async with d.factory() as db:
        enquiries = (
            await db.exec(
                select(CrmInboundEnquiry).where(CrmInboundEnquiry.source_import_id == import_id)
            )
        ).all()
        assert len(enquiries) == 1
        assert enquiries[0].organization_id == d.org


async def test_source_only_worker_retains_reviewed_classification(durable):
    import json

    d = durable
    payload = {
        "schema_version": "owner-source-audit/1",
        "dataset_id": "disposable-review",
        "original_filename": "reviewed.xlsx",
        "source_sha256": "a" * 64,
        "cleaned_sha256": "b" * 64,
        "references": [
            {
                "reference_id": "plot:1",
                "source_key": ["District", "Plot 1"],
                "disposition": "latest_recorded_buyer_candidate",
                "review_required": False,
                "decision_basis": "Reviewed fixture",
                "owner_candidate_groups": [[2]],
                "previous_nonbank_candidate_rows": [],
            }
        ],
        "rows": [
            {
                "cleaned_row_number": 2,
                "original_rows": [2],
                "reference_id": "plot:1",
                "recorded_at": "2020-01-01",
                "amount_aed": "1234567.89",
                "size_sqm": "123.45",
                "project": "District",
                "building_name": "",
                "building_number": "",
                "unit_number": "",
                "land_number": "1",
                "dm_sub_number": "2",
                "property_type": "Land",
                "party_role": "Buyer",
                "contact_name": "Reviewed Buyer",
                "phone": "+971501234567",
                "country": "UAE",
                "source_values": ["original", 2, None],
            }
        ],
    }
    import_id = await queue(d, kind="source_only", data=json.dumps(payload).encode())
    await import_worker.run_once(d.factory)
    record, job = await load(d, import_id)
    assert record.status == job.status == "completed"
    assert record.mapping["mode"] == "source_only"
    assert record.original_filename == "reviewed.xlsx"
    async with d.factory() as db:
        claim = (
            await db.exec(
                select(CrmPropertyContactClaim).where(
                    CrmPropertyContactClaim.import_id == import_id
                )
            )
        ).one()
        assert claim.ownership_status == "probable_current_owner"
        assert claim.evidence["source_audit"]["disposition"] == "latest_recorded_buyer_candidate"


async def test_transient_attempt_retries_same_import_without_duplicate_claims(durable, monkeypatch):
    d = durable
    import_id = await queue(d)
    original = import_worker.read_input
    monkeypatch.setattr(import_worker, "read_input", AsyncMock(side_effect=ConnectionError()))
    await import_worker.run_once(d.factory)
    _, job = await load(d, import_id)
    async with d.factory() as db:
        pending = await db.get(CrmImportJob, job.id)
        pending.available_at = utcnow() - timedelta(seconds=1)
        db.add(pending)
        await db.commit()
    monkeypatch.setattr(import_worker, "read_input", original)
    await import_worker.run_once(d.factory)
    record, job = await load(d, import_id)
    assert record.status == job.status == "completed"
    assert job.attempt_count == 2
    async with d.factory() as db:
        assert (
            len(
                (
                    await db.exec(
                        select(CrmPropertyContactClaim).where(
                            CrmPropertyContactClaim.import_id == import_id
                        )
                    )
                ).all()
            )
            == 1
        )


async def test_failed_durable_replay_preserves_previous_result(durable, monkeypatch):
    d = durable
    import_id = await queue(d)
    await import_worker.run_once(d.factory)
    record, original_job = await load(d, import_id)
    async with d.factory() as db:
        previous = await db.get(CrmContactImport, import_id)
        previous.mapping = {}
        db.add(previous)
        await db.commit()
    assert await queue(d, reprocess_import_id=import_id) == import_id
    monkeypatch.setattr(
        imports, "prepare_file_context", AsyncMock(side_effect=ValueError("Invalid replay"))
    )
    await import_worker.run_once(d.factory)
    record, job = await load(d, import_id)
    assert record.status == "completed" and job.status == "failed"
    assert job.id == original_job.id
    async with d.factory() as db:
        assert (
            len(
                (
                    await db.exec(
                        select(CrmPropertyContactClaim).where(
                            CrmPropertyContactClaim.import_id == import_id
                        )
                    )
                ).all()
            )
            == 1
        )


async def test_worker_publication_audit_uses_original_actor_and_job_correlation(durable):
    from app.crm.audit_models import CrmMutationAudit

    d = durable
    import_id = await queue(d)
    await import_worker.run_once(d.factory)
    _, job = await load(d, import_id)
    async with d.factory() as db:
        audit = (
            await db.exec(
                select(CrmMutationAudit).where(
                    CrmMutationAudit.organization_id == d.org,
                    CrmMutationAudit.resource == "crm_property_contact_claims",
                    CrmMutationAudit.action == "INSERT",
                )
            )
        ).one()
        assert audit.actor_id == d.user
        assert audit.actor_kind == "user"
        assert audit.request_id == job.id


async def test_ambiguous_commit_keeps_the_referenced_private_input(durable, monkeypatch):
    d = durable
    async with d.factory() as db:
        real_commit = db.commit

        async def persisted_but_response_lost():
            await real_commit()
            raise ConnectionError("Commit acknowledgement was lost")

        monkeypatch.setattr(db, "commit", persisted_but_response_lost)
        with pytest.raises(ConnectionError):
            await import_jobs.enqueue(
                db,
                kind="owner",
                data=OWNER,
                filename="owner.csv",
                name="Example",
                user_id=d.user,
                organization_id=d.org,
            )
    async with d.factory() as db:
        record = (
            await db.exec(select(CrmContactImport).where(CrmContactImport.organization_id == d.org))
        ).one()
        job = await jobs.for_import(db, record)
        assert job.input_object_key in d.storage.objects
    assert not d.storage.deleted
    assert await import_worker.run_once(d.factory)


async def test_retry_limit_is_enforced_without_operator_reconciliation(durable, monkeypatch):
    d = durable
    import_id = await queue(d)
    monkeypatch.setattr(import_worker, "read_input", AsyncMock(side_effect=ConnectionError()))
    for attempt in range(1, 4):
        await import_worker.run_once(d.factory)
        record, job = await load(d, import_id)
        assert job.attempt_count == attempt
        assert job.status == ("failed" if attempt == 3 else "retry_wait")
        async with d.factory() as db:
            pending = await db.get(CrmImportJob, job.id)
            pending.available_at = utcnow() - timedelta(seconds=1)
            db.add(pending)
            await db.commit()
    assert record.status == "failed"
    assert not await import_worker.run_once(d.factory)


async def test_successful_durable_replay_keeps_claim_identity_and_normal_dedup(durable):
    d = durable
    import_id = await queue(d)
    await import_worker.run_once(d.factory)
    async with d.factory() as db:
        old = await db.get(CrmContactImport, import_id)
        old.mapping = {}
        db.add(old)
        claims = (
            await db.exec(
                select(CrmPropertyContactClaim).where(
                    CrmPropertyContactClaim.import_id == import_id
                )
            )
        ).all()
        original_ids = [claim.id for claim in claims]
        await db.commit()
    assert await queue(d, reprocess_import_id=import_id) == import_id
    await import_worker.run_once(d.factory)
    record, job = await load(d, import_id)
    assert record.status == job.status == "completed"
    async with d.factory() as db:
        claims = (
            await db.exec(
                select(CrmPropertyContactClaim).where(
                    CrmPropertyContactClaim.import_id == import_id
                )
            )
        ).all()
        assert [claim.id for claim in claims] == original_ids
    assert await queue(d) == import_id


async def test_busy_replay_returns_conflict_instead_of_database_error(durable):
    d = durable
    import_id = await queue(d)
    async with d.factory() as locked:
        (
            await locked.exec(
                select(CrmContactImport).where(CrmContactImport.id == import_id).with_for_update()
            )
        ).one()
        with pytest.raises(HTTPException) as error:
            await queue(d, reprocess_import_id=import_id)
        assert error.value.status_code == 409
        await locked.rollback()
