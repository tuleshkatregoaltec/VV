"""An agent's owner file waits for their manager's approval (meeting 13 Nov 2026, 23:56-24:44).

The import pipeline itself is replaced here: these tests are about who may decide, deciding once,
and the import being attributed to the agent. Lead imports are not part of this workflow.
"""

import asyncio
import io
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from test_crm_lead_assignment import _agency

from app.crm import assignment, import_repository, owner_import_requests
from app.crm.import_models import CrmContactImport, CrmOwnerImportRequest


class FakeStorage:
    def __init__(self):
        self.files: dict[str, bytes] = {}

    async def upload(self, key, data):
        self.files[key] = data

    async def download(self, key):
        return self.files[key]

    async def delete_many(self, keys):
        for key in keys:
            self.files.pop(key, None)


@pytest.fixture
def pipeline(monkeypatch):
    storage = FakeStorage()
    calls: list[dict] = []
    outcome = {"status": "completed"}

    async def process(db, *, upload, name, user_id, organization_id, reprocess_import_id=None):
        await asyncio.sleep(0)  # the real import is long; let a racing approval interleave
        calls.append(
            {
                "user_id": user_id,
                "data": await upload.read(),
                "organization": organization_id,
                "replay": reprocess_import_id,
            }
        )
        return SimpleNamespace(id=None, status=outcome["status"])

    monkeypatch.setattr(owner_import_requests, "_storage", lambda: storage)
    monkeypatch.setattr(owner_import_requests, "process_contact_import", process)
    return SimpleNamespace(storage=storage, calls=calls, outcome=outcome)


async def _send(db, ids, person, data=b"Name,Unit\nOwner,101\n"):
    return await owner_import_requests.request_import(
        db,
        organization_id=ids["org"],
        user_id=ids[person],
        upload=UploadFile(file=io.BytesIO(data), filename="owners.csv"),
        name="Owners",
        team_id=ids["north"] if person == "omar" else None,
    )


async def _seen_by(db, ids, person):
    return {
        r.id
        for r in await owner_import_requests.list_requests(
            db, organization_id=ids["org"], user_id=ids[person]
        )
    }


async def _decide(db, ids, person, request_id, verb="approve"):
    return await getattr(owner_import_requests, verb)(
        db, organization_id=ids["org"], user_id=ids[person], request_id=request_id
    )


async def test_only_agents_need_approval(pg_session):
    ids = await _agency(pg_session)
    for person, needs in (
        ("owner", False),
        ("nadia", False),
        ("omar", True),
        ("adam", True),  # in no team: an administrator decides
    ):
        scope = await assignment.load_scope(pg_session, ids["org"], ids[person])
        assert owner_import_requests.needs_approval(scope) is needs, person
    with pytest.raises(HTTPException) as direct:
        await _send(pg_session, ids, "nadia")
    assert direct.value.status_code == 409


async def test_the_agents_manager_approves_once_and_the_import_is_the_agents(pg_session, pipeline):
    ids = await _agency(pg_session)
    sent = await _send(pg_session, ids, "omar")
    assert sent.status == "pending" and pipeline.calls == []
    assert len(pipeline.storage.files) == 1

    # Omar's manager and the owner see it; another team's manager and a teammate do not.
    for person, sees in (("nadia", True), ("owner", True), ("karim", False), ("sara", False)):
        assert (sent.id in await _seen_by(pg_session, ids, person)) is sees, person
    for person, status in (("karim", 404), ("sara", 404), ("omar", 403)):
        with pytest.raises(HTTPException) as refused:
            await _decide(pg_session, ids, person, sent.id)
        assert refused.value.status_code == status, person
        await pg_session.rollback()

    approved = await _decide(pg_session, ids, "nadia", sent.id)
    assert (approved.status, approved.decided_by_user_id) == ("approved", ids["nadia"])
    assert [(c["user_id"], c["data"]) for c in pipeline.calls] == [
        (ids["omar"], b"Name,Unit\nOwner,101\n")
    ]
    assert pipeline.storage.files == {}  # the held copy is gone once imported
    with pytest.raises(HTTPException) as again:
        await _decide(pg_session, ids, "owner", sent.id)
    assert again.value.status_code == 409
    assert len(pipeline.calls) == 1


async def test_an_agent_without_a_team_needs_an_administrator(pg_session, pipeline):
    ids = await _agency(pg_session)
    sent = await _send(pg_session, ids, "adam")
    assert sent.id not in await _seen_by(pg_session, ids, "nadia")
    rejected = await _decide(pg_session, ids, "owner", sent.id, "reject")
    assert rejected.status == "rejected" and pipeline.calls == []
    assert pipeline.storage.files == {}


async def test_a_failed_import_can_be_approved_again(pg_session, pipeline):
    ids = await _agency(pg_session)
    sent = await _send(pg_session, ids, "omar")
    pipeline.outcome["status"] = "failed"
    failed = await _decide(pg_session, ids, "nadia", sent.id)
    assert failed.status == "failed" and failed.error_message
    assert len(pipeline.storage.files) == 1  # kept for the retry
    pipeline.outcome["status"] = "completed"
    assert (await _decide(pg_session, ids, "nadia", sent.id)).status == "approved"


async def test_two_managers_approving_at_once_import_the_file_once(postgres_test_url, pipeline):
    from test_crm_lead_assignment import _team

    engine = create_async_engine(postgres_test_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as setup:
            ids = await _agency(setup)
            await _team(setup, ids, "Joint", karim="supervisor", omar="agent")
            sent = await _send(setup, ids, "omar")

        async def approve(person):
            async with AsyncSession(engine, expire_on_commit=False) as db:
                try:
                    return (await _decide(db, ids, person, sent.id)).status
                except HTTPException as error:
                    return error.status_code

        results = await asyncio.gather(approve("nadia"), approve("owner"))
        assert sorted(results, key=str) == [409, "approved"]
        assert len(pipeline.calls) == 1
    finally:
        await engine.dispose()


async def _crash(db, request_id):
    row = await db.get(CrmOwnerImportRequest, request_id)
    row.status = "processing"
    row.processing_started_at = owner_import_requests._now() - timedelta(hours=1)
    row.attempts = 1
    db.add(row)
    await db.commit()
    return row


async def test_crashed_approval_is_persistently_retryable(pg_session, pipeline):
    ids = await _agency(pg_session)
    sent = await _send(pg_session, ids, "omar")
    await _crash(pg_session, sent.id)
    listed = await owner_import_requests.list_requests(
        pg_session, organization_id=ids["org"], user_id=ids["nadia"]
    )
    assert next(r for r in listed if r.id == sent.id).status == "failed"
    result = await _decide(pg_session, ids, "nadia", sent.id)
    assert result.status == "approved" and result.attempts == 2


async def test_a_slow_live_import_cannot_be_retried_or_rejected(postgres_test_url, pipeline):
    engine = create_async_engine(postgres_test_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as live:
            ids = await _agency(live)
            sent = await _send(live, ids, "omar")
            row = await _crash(live, sent.id)
            async with import_repository.processing_file(live, ids["org"], row.sha256):
                # Even an expired lease is not proof of a crash while its processor is alive.
                async with AsyncSession(engine, expire_on_commit=False) as other:
                    listed = await owner_import_requests.list_requests(
                        other, organization_id=ids["org"], user_id=ids["nadia"]
                    )
                    assert next(r for r in listed if r.id == sent.id).status == "processing"
                    for verb in ("approve", "reject"):
                        with pytest.raises(HTTPException) as refused:
                            await _decide(other, ids, "nadia", sent.id, verb)
                        assert refused.value.status_code == 409
                        await other.rollback()
            assert (await _decide(live, ids, "nadia", sent.id)).status == "approved"
            assert len(pipeline.calls) == 1
    finally:
        await engine.dispose()


@pytest.mark.parametrize("status", ["completed", "processing"])
async def test_crash_reuses_the_digest_import_instead_of_creating_another(
    pg_session, pipeline, status
):
    ids = await _agency(pg_session)
    sent = await _send(pg_session, ids, "omar")
    row = await _crash(pg_session, sent.id)
    record = CrmContactImport(
        organization_id=ids["org"],
        created_by_user_id=ids["omar"],
        name="Owners",
        original_filename=row.original_filename,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        status=status,
        created_at=row.processing_started_at,
        mapping={},
        summary={},
    )
    pg_session.add(record)
    await pg_session.commit()
    result = await _decide(pg_session, ids, "nadia", sent.id)
    assert result.status == "approved" and result.attempts == 2
    if status == "completed":
        assert result.import_id == record.id and pipeline.calls == []
    else:
        assert len(pipeline.calls) == 1 and pipeline.calls[0]["replay"] == record.id


async def test_an_unfinished_import_is_never_reported_as_approved(pg_session, pipeline):
    ids = await _agency(pg_session)
    sent = await _send(pg_session, ids, "omar")
    pipeline.outcome["status"] = "processing"
    assert (await _decide(pg_session, ids, "nadia", sent.id)).status == "failed"
    assert pipeline.storage.files


async def test_large_approved_file_is_queued_then_processed_by_a_worker(pg_session, pipeline):
    ids = await _agency(pg_session)
    data = b"Name,Unit\nOwner,101\n" + (b"x" * owner_import_requests.LARGE_OWNER_IMPORT_BYTES)
    sent = await _send(pg_session, ids, "omar", data)

    queued = await _decide(pg_session, ids, "nadia", sent.id)
    assert queued.status == "queued"
    assert pipeline.calls == []

    request_id = await owner_import_requests.claim_next_queued_import(
        pg_session, organization_id=ids["org"]
    )
    assert request_id == sent.id
    completed = await owner_import_requests.process_queued_import(pg_session, request_id)
    assert completed.status == "approved"
    assert [(call["user_id"], call["data"]) for call in pipeline.calls] == [(ids["omar"], data)]
    assert pipeline.storage.files == {}


async def test_large_processing_job_is_reclaimed_after_its_lease(pg_session, pipeline):
    ids = await _agency(pg_session)
    data = b"Name,Unit\nOwner,101\n" + (b"x" * owner_import_requests.LARGE_OWNER_IMPORT_BYTES)
    sent = await _send(pg_session, ids, "omar", data)
    await _decide(pg_session, ids, "nadia", sent.id)
    row = await pg_session.get(CrmOwnerImportRequest, sent.id)
    row.status = "processing"
    row.processing_started_at = owner_import_requests._now() - timedelta(hours=1)
    row.attempts = 1
    await pg_session.commit()

    assert (
        await owner_import_requests.claim_next_queued_import(pg_session, organization_id=ids["org"])
        == sent.id
    )
    result = await owner_import_requests.process_queued_import(pg_session, sent.id)
    assert result.status == "approved" and result.attempts == 2


async def test_large_manager_upload_is_queued_before_the_request_returns(pg_session, pipeline):
    ids = await _agency(pg_session)
    data = b"Name,Unit\nOwner,101\n" + (b"x" * owner_import_requests.LARGE_OWNER_IMPORT_BYTES)
    queued, prepared = await owner_import_requests.queue_large_direct_import(
        pg_session,
        organization_id=ids["org"],
        user_id=ids["nadia"],
        upload=UploadFile(file=io.BytesIO(data), filename="owners.csv"),
        name="Owners",
    )
    assert queued is not None and queued.status == "queued"
    assert prepared is None
    assert len(pipeline.storage.files) == 1


async def test_owner_file_approval_belongs_only_to_the_selected_team(pg_session, pipeline):
    from test_crm_lead_assignment import _team

    ids = await _agency(pg_session)
    other = await _team(pg_session, ids, "Other", karim="supervisor", omar="agent")

    async def send(team_id=None):
        return await owner_import_requests.request_import(
            pg_session,
            organization_id=ids["org"],
            user_id=ids["omar"],
            upload=UploadFile(file=io.BytesIO(b"Name,Unit\nOwner,101\n"), filename="owners.csv"),
            name="Owners",
            team_id=team_id,
        )

    with pytest.raises(HTTPException) as ambiguous:
        await send()
    assert ambiguous.value.status_code == 422 and not pipeline.storage.files
    with pytest.raises(HTTPException) as foreign:
        await send(ids["south"])
    assert foreign.value.status_code == 403
    sent = await send(other)
    assert sent.team_id == other
    assert sent.id not in await _seen_by(pg_session, ids, "nadia")
    assert sent.id in await _seen_by(pg_session, ids, "karim")
    with pytest.raises(HTTPException) as refused:
        await _decide(pg_session, ids, "nadia", sent.id)
    assert refused.value.status_code == 404
    await pg_session.rollback()
    assert (await _decide(pg_session, ids, "karim", sent.id)).status == "approved"


async def test_processing_fence_survives_commits_and_connection_loss_stops_writes(pg_session):
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    engine = pg_session.bind
    async with import_repository.processing_file(pg_session, "test-org", "test-file"):
        pid = await pg_session.scalar(text("SELECT pg_backend_pid()"))
        await pg_session.commit()
        assert await pg_session.scalar(text("SELECT pg_backend_pid()")) == pid
    with pytest.raises(SQLAlchemyError):
        async with import_repository.processing_file(pg_session, "test-org", "test-file"):
            database = await pg_session.scalar(text("SELECT current_database()"))
            assert database.startswith("vv_migration_test_")
            pid = await pg_session.scalar(text("SELECT pg_backend_pid()"))
            async with engine.connect() as killer:
                assert await killer.scalar(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            # Losing the advisory-lock connection must also stop the old processor's writes.
            await pg_session.exec(text("SELECT 1"))
    async with import_repository.processing_file(pg_session, "test-org", "test-file"):
        assert await pg_session.scalar(text("SELECT 1")) == 1
