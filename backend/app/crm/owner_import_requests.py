"""Owner files sent by agents wait for a manager's approval before they are imported.

Agreed (meeting of 13 Nov 2026, 23:56-24:44, and the product decision that followed): an agent's
owner file is held until a supervisor of the selected owning team, or an organization
administrator, approves it; an agent in no team needs an administrator. Managers and
administrators import owner files directly, as before. Ordinary lead imports are not affected.

The file is kept in private, organization-scoped object storage while it waits. Approving runs
the ordinary owner import, attributed to the agent who sent the file. Each decision locks the
request row, so two managers deciding at once cannot both import it.

Large files are durable jobs. The approving request writes `queued` before it returns; a worker
claims it with a lease and retries a crashed attempt. Small files keep the existing immediate
result. The same PostgreSQL advisory lock fences direct imports and retries across transaction
commits. A retry never imports the same file twice: the owner import is keyed by the file's
digest per organization, so a finished earlier attempt is reused, and an attempt that crashed
half-way is replayed under its own import record.
"""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import or_, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import assignment, import_repository
from app.crm.import_drop_log import _storage
from app.crm.import_models import (
    CrmContactImport,
    CrmOwnerImportRequest,
    OwnerImportRequestResponse,
)
from app.crm.imports import _EMPTY_FILE, _MAX_FILE_BYTES, process_contact_import
from app.organization import teams as org_teams

logger = logging.getLogger(__name__)

# Longer than any owner import observed so far; a crash mid-import is retryable after this.
PROCESSING_LEASE = timedelta(minutes=30)
MAX_PROCESSING_ATTEMPTS = 3
LARGE_OWNER_IMPORT_BYTES = 5 * 1024 * 1024


def needs_approval(scope: assignment.AssignmentScope) -> bool:
    """Agents (neither manager nor administrator) send owner files for approval."""
    return not scope.can_assign


def _may_decide(scope: assignment.AssignmentScope, request: CrmOwnerImportRequest) -> bool:
    if scope.organization_admin:
        return True
    # A manager decides for the people in the teams they supervise, never their own file.
    return (
        request.requested_by_user_id != scope.user_id
        and request.team_id in scope.supervised_team_ids
    )


def _may_see(scope: assignment.AssignmentScope, request: CrmOwnerImportRequest) -> bool:
    return request.requested_by_user_id == scope.user_id or _may_decide(scope, request)


def _response(request: CrmOwnerImportRequest) -> OwnerImportRequestResponse:
    return OwnerImportRequestResponse.model_validate(request, from_attributes=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lease_expired(started_at: datetime | None, now: datetime) -> bool:
    return started_at is None or started_at + PROCESSING_LEASE <= now


def _crashed(request: CrmOwnerImportRequest, now: datetime) -> bool:
    """An attempt that began more than the lease ago and never recorded an outcome."""
    return request.status == "processing" and _lease_expired(request.processing_started_at, now)


def _mark_failed(db: AsyncSession, request: CrmOwnerImportRequest, message: str) -> None:
    request.status = "failed"
    request.error_message = message
    db.add(request)


async def _read_upload(upload: UploadFile) -> tuple[str, bytes]:
    filename = Path(upload.filename or "").name
    if Path(filename).suffix.lower() not in {".xlsx", ".csv"}:
        raise HTTPException(status_code=400, detail="Upload an XLSX or CSV file")
    data = await upload.read(_MAX_FILE_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail=_EMPTY_FILE)
    if len(data) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="The uploaded file exceeds 50 MB")
    return filename, data


async def _save_request(
    db: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    team_id: str | None,
    filename: str,
    data: bytes,
    name: str,
    status: str,
    decided_by_user_id: str | None = None,
) -> OwnerImportRequestResponse:
    key = f"crm-owner-import-requests/{organization_id}/{uuid4().hex}/{filename}"
    await _storage().upload(key, data)
    now = _now()
    request = CrmOwnerImportRequest(
        organization_id=organization_id,
        requested_by_user_id=user_id,
        team_id=team_id,
        name=name.strip() or Path(filename).stem,
        original_filename=filename,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        storage_key=key,
        status=status,
        decided_by_user_id=decided_by_user_id,
        decided_at=now if decided_by_user_id else None,
        created_at=now,
    )
    db.add(request)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        await _storage().delete_many([key])
        raise
    await db.refresh(request)
    return _response(request)


async def request_import(
    db: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    upload: UploadFile,
    name: str,
    team_id: str | None = None,
) -> OwnerImportRequestResponse:
    scope = await assignment.load_scope(db, organization_id, user_id)
    if not needs_approval(scope):
        raise HTTPException(status_code=409, detail="Managers import owner files directly")
    if team_id is not None and team_id not in scope.member_team_ids:
        raise HTTPException(status_code=403, detail="Choose a team you belong to")
    if team_id is None:
        if len(scope.member_team_ids) > 1:
            raise HTTPException(status_code=422, detail="Choose the team that owns this owner file")
        team_id = next(iter(scope.member_team_ids), None)
    filename, data = await _read_upload(upload)
    return await _save_request(
        db,
        organization_id=organization_id,
        user_id=user_id,
        team_id=team_id,
        filename=filename,
        data=data,
        name=name,
        status="pending",
    )


async def queue_large_direct_import(
    db: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    upload: UploadFile,
    name: str,
) -> tuple[OwnerImportRequestResponse | None, UploadFile | None]:
    """Persist only large manager/admin uploads; small files retain their immediate response."""
    filename, data = await _read_upload(upload)
    if len(data) < LARGE_OWNER_IMPORT_BYTES:
        return None, UploadFile(file=io.BytesIO(data), filename=filename)
    return (
        await _save_request(
            db,
            organization_id=organization_id,
            user_id=user_id,
            team_id=None,
            filename=filename,
            data=data,
            name=name,
            status="queued",
            decided_by_user_id=user_id,
        ),
        None,
    )


async def list_requests(
    db: AsyncSession, *, organization_id: str, user_id: str
) -> list[OwnerImportRequestResponse]:
    """Your own requests, and those you may decide, newest first."""
    scope = await assignment.load_scope(db, organization_id, user_id)
    rows = (
        await db.exec(
            select(CrmOwnerImportRequest)
            .where(CrmOwnerImportRequest.organization_id == organization_id)
            .order_by(CrmOwnerImportRequest.created_at.desc())  # type: ignore[attr-defined]
        )
    ).all()
    visible = [row for row in rows if _may_see(scope, row)]
    # Small imports still run in the approval request. Preserve their existing explicit retry path.
    now = _now()
    for row in visible:
        if row.size_bytes >= LARGE_OWNER_IMPORT_BYTES or not _crashed(row, now):
            continue
        try:
            async with import_repository.processing_file(db, organization_id, row.sha256):
                locked = (
                    await db.exec(
                        select(CrmOwnerImportRequest)
                        .where(CrmOwnerImportRequest.id == row.id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).one()
                if _crashed(locked, now):
                    _mark_failed(
                        db,
                        locked,
                        "The import did not finish (the server stopped). Approve it again to retry.",
                    )
                await db.commit()
        except HTTPException as error:
            if error.status_code != 409:
                raise
    return [_response(row) for row in visible]


async def _lock_for_decision(
    db: AsyncSession, scope: assignment.AssignmentScope, request_id: int, now: datetime
) -> CrmOwnerImportRequest:
    request = (
        await db.exec(
            select(CrmOwnerImportRequest)
            .where(
                CrmOwnerImportRequest.organization_id == scope.organization_id,
                CrmOwnerImportRequest.id == request_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()
    if not request or not _may_see(scope, request):
        raise HTTPException(status_code=404, detail="Import request not found")
    if not _may_decide(scope, request):
        raise HTTPException(status_code=403, detail="Only the sender's manager can decide this")
    if _crashed(request, now) and request.size_bytes < LARGE_OWNER_IMPORT_BYTES:
        _mark_failed(
            db,
            request,
            "The import did not finish (the server stopped). Approve it again to retry.",
        )
    if request.status == "processing":
        raise HTTPException(
            status_code=409, detail="This file is being imported now; try again in a few minutes"
        )
    if request.status not in {"pending", "failed"}:
        raise HTTPException(status_code=409, detail="This request has already been decided")
    return request


async def reject(
    db: AsyncSession, *, organization_id: str, user_id: str, request_id: int
) -> OwnerImportRequestResponse:
    scope = await assignment.load_scope(db, organization_id, user_id)
    request = await db.get(CrmOwnerImportRequest, request_id)
    if not request or request.organization_id != organization_id or not _may_see(scope, request):
        raise HTTPException(status_code=404, detail="Import request not found")
    async with import_repository.processing_file(db, organization_id, request.sha256):
        now = _now()
        request = await _lock_for_decision(db, scope, request_id, now)
        request.status = "rejected"
        request.decided_by_user_id = user_id
        request.decided_at = now
        db.add(request)
        await db.commit()
        await _discard_file(request)
        return _response(request)


async def _earlier_import(
    db: AsyncSession, request: CrmOwnerImportRequest, now: datetime
) -> CrmContactImport | None:
    """The import record an earlier attempt (or a manager's direct import) made for this exact
    file, if any. One still processing within the lease is somebody else's live work."""
    record = await import_repository.find_import_by_digest(
        db, request.organization_id, request.sha256
    )
    if record is not None and record.status == "processing":
        if not _lease_expired(record.created_at, now):
            raise HTTPException(
                status_code=409,
                detail="This file is being imported now; try again in a few minutes",
            )
        # The earlier attempt died mid-import: let the owner import replay it under its record.
        record.status = "failed"
        import_repository.save(db, record)
    return record


async def approve(
    db: AsyncSession, *, organization_id: str, user_id: str, request_id: int
) -> OwnerImportRequestResponse:
    """Approve an owner's held file. Large files become a durable worker job."""
    scope = await assignment.load_scope(db, organization_id, user_id)
    request = await db.get(CrmOwnerImportRequest, request_id)
    if not request or request.organization_id != organization_id or not _may_see(scope, request):
        raise HTTPException(status_code=404, detail="Import request not found")
    async with import_repository.processing_file(db, organization_id, request.sha256):
        request = await _lock_for_decision(db, scope, request_id, _now())
        if request.size_bytes >= LARGE_OWNER_IMPORT_BYTES:
            request.status = "queued"
            request.decided_by_user_id = user_id
            request.decided_at = _now()
            request.error_message = None
            db.add(request)
            await db.commit()
            return _response(request)
        return await _approve_locked(db, scope, request_id, request=request)


async def _approve_locked(
    db: AsyncSession,
    scope: assignment.AssignmentScope,
    request_id: int,
    *,
    request: CrmOwnerImportRequest | None = None,
):
    organization_id, user_id = scope.organization_id, scope.user_id
    now = _now()
    request = request or await _lock_for_decision(db, scope, request_id, now)
    if not await org_teams.get_membership(db, organization_id, request.requested_by_user_id):
        raise HTTPException(status_code=409, detail="The sender has left the organization")
    # Committed before the long import: a second approval now sees "processing" and stops, and
    # a crash from here on leaves a dated attempt that becomes retryable when the lease runs out.
    request.status = "processing"
    request.processing_started_at = now
    request.attempts = (request.attempts or 0) + 1
    request.decided_by_user_id = user_id
    request.decided_at = now
    request.error_message = None
    db.add(request)
    await db.commit()
    return await _finish_processing(db, request.id)


async def _finish_processing(
    db: AsyncSession, request_id: int | None
) -> OwnerImportRequestResponse:
    if request_id is None:
        raise HTTPException(status_code=500, detail="Import request could not be saved")
    request = await db.get(CrmOwnerImportRequest, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Import request not found")
    organization_id = request.organization_id
    request_pk = request.id
    try:
        earlier = await _earlier_import(db, request, _now())
        if earlier is not None and earlier.status == "completed":
            result = earlier  # the same file was already imported for this organization
        else:
            data = await _storage().download(request.storage_key)
            if hashlib.sha256(data).hexdigest() != request.sha256:
                raise ValueError("The held file no longer matches the approved upload")
            result = await process_contact_import(
                db,
                upload=UploadFile(file=io.BytesIO(data), filename=request.original_filename),
                name=request.name,
                user_id=request.requested_by_user_id,
                organization_id=organization_id,
                reprocess_import_id=earlier.id if earlier is not None else None,
            )
        # process_contact_import hands the file to the durable import queue, which holds its own
        # copy and owns retries; only an import that has already failed is a failed approval.
        outcome, import_id, error = (
            ("failed", result.id, "The import failed. Check the file and approve again.")
            if result.status == "failed"
            else ("approved", result.id, None)
        )
    except Exception:
        await db.rollback()
        logger.exception("Owner import request %s failed", request_pk)
        outcome, import_id, error = "failed", None, "The import failed. Approve it again to retry."
    request = await db.get(CrmOwnerImportRequest, request_pk)
    request.status = outcome
    request.import_id = import_id
    request.error_message = error
    db.add(request)
    await db.commit()
    if outcome == "approved":
        await _discard_file(request)
    return _response(request)


async def claim_next_queued_import(
    db: AsyncSession, *, organization_id: str | None = None
) -> int | None:
    """Claim one queued or abandoned job. Row locks make multiple workers safe."""
    now = _now()
    cutoff = now - PROCESSING_LEASE
    await db.exec(
        update(CrmOwnerImportRequest)
        .where(
            CrmOwnerImportRequest.status == "processing",
            CrmOwnerImportRequest.processing_started_at < cutoff,
            CrmOwnerImportRequest.attempts >= MAX_PROCESSING_ATTEMPTS,
        )
        .values(
            status="failed",
            error_message="The import did not finish after three attempts. Approve it again to retry.",
        )
    )
    conditions = [
        or_(
            CrmOwnerImportRequest.status == "queued",
            (
                (CrmOwnerImportRequest.status == "processing")
                & (CrmOwnerImportRequest.processing_started_at < cutoff)
            ),
        )
    ]
    if organization_id is not None:
        conditions.append(CrmOwnerImportRequest.organization_id == organization_id)
    request = (
        await db.exec(
            select(CrmOwnerImportRequest)
            .where(*conditions)
            .order_by(CrmOwnerImportRequest.created_at.asc())  # type: ignore[attr-defined]
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).first()
    if request is None:
        await db.commit()
        return None
    request.status = "processing"
    request.processing_started_at = now
    request.attempts = (request.attempts or 0) + 1
    request.error_message = None
    db.add(request)
    await db.commit()
    return request.id


async def process_queued_import(db: AsyncSession, request_id: int) -> OwnerImportRequestResponse:
    """Run a claimed job. The advisory lock also deduplicates files submitted twice."""
    request = await db.get(CrmOwnerImportRequest, request_id)
    if request is None or request.status != "processing":
        raise HTTPException(status_code=409, detail="Import request is no longer queued")
    async with import_repository.processing_file(db, request.organization_id, request.sha256):
        request = await db.get(CrmOwnerImportRequest, request_id)
        if request is None or request.status != "processing":
            raise HTTPException(status_code=409, detail="Import request is no longer queued")
        return await _finish_processing(db, request_id)


async def _discard_file(request: CrmOwnerImportRequest) -> None:
    try:
        await _storage().delete_many([request.storage_key])
    except Exception:
        # The decision stands; an orphaned private file is cleaned up by bucket lifecycle rules.
        logger.exception("Could not delete held owner file for request %s", request.id)
