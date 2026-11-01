"""Persist private input and the job together before acknowledging an import."""

import hashlib
import json
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.config import settings
from app.core.object_storage import ObjectStorageClient
from app.crm import import_job_repository as jobs
from app.crm import import_repository, inbound_repository
from app.crm.import_events import IMPORT_RESOLVER_VERSION
from app.crm.import_job_models import CrmImportJob, utcnow
from app.crm.import_models import CrmContactImport
from app.crm.inbound_models import CrmInboundImport

logger = logging.getLogger(__name__)
ACTIVE_STATUSES = {"queued", "processing", "retry_wait"}


def storage() -> ObjectStorageClient:
    return ObjectStorageClient(
        endpoint_url=str(settings.OBJECT_STORAGE_ENDPOINT_URL)
        if settings.OBJECT_STORAGE_ENDPOINT_URL
        else None,
        access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        bucket_name=settings.OBJECT_STORAGE_BUCKET,
        region=settings.OBJECT_STORAGE_REGION,
        use_path_style=settings.OBJECT_STORAGE_USE_PATH_STYLE,
    )


def semantic_key(kind: str, digest: str, parameters: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            {"kind": kind, "sha256": digest, "parameters": parameters},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


async def remove_input(key: str) -> None:
    try:
        await storage().delete_many([key])
    except Exception:
        # Reconcile orphan objects with the documented private-prefix lifecycle.
        logger.warning("CRM import input cleanup failed")


async def enqueue(
    db,
    *,
    kind: str,
    data: bytes,
    filename: str,
    name: str,
    user_id: str,
    organization_id: str,
    mapping_override: dict | None = None,
    campaign_context: str = "",
    reprocess_import_id: int | None = None,
):
    mapping_override = mapping_override or None
    raw_digest = hashlib.sha256(data).hexdigest()
    campaign_context = campaign_context.strip()[:4_000]
    parameters = {"kind": kind, "mapping_override": mapping_override}
    if kind == "inbound":
        parameters["campaign_context"] = campaign_context
        # Preserve the historical inbound source+campaign identity.
        digest = hashlib.sha256(data + b"\0" + campaign_context.casefold().encode()).hexdigest()
    else:
        digest = raw_digest
    if reprocess_import_id is not None:
        if mapping_override is not None:
            raise HTTPException(
                status_code=409,
                detail="Replay uses the saved mapping; new mapping overrides are not supported.",
            )
        parameters["reprocess_import_id"] = reprocess_import_id
    identity_parameters = {
        key: value for key, value in parameters.items() if key != "reprocess_import_id"
    }
    if kind == "inbound":
        identity_parameters["campaign_context"] = campaign_context.casefold()
    fingerprint = semantic_key(kind, raw_digest, identity_parameters)
    if kind == "source_only":
        parameters["source_name"] = name.strip()[:200]
    repository = inbound_repository if kind == "inbound" else import_repository
    replay = reprocess_import_id is not None
    try:
        record = (
            await import_repository.lock_import_for_replay(db, reprocess_import_id, organization_id)
            if replay
            else await repository.find_import_by_digest(
                db, *([digest, organization_id] if kind == "inbound" else [organization_id, digest])
            )
        )
    except DBAPIError as exc:
        if replay and getattr(exc.orig, "sqlstate", None) == "55P03":
            await db.rollback()
            raise HTTPException(
                status_code=409, detail="This import is already processing."
            ) from None
        raise
    if replay:
        if record is None or record.sha256 != raw_digest:
            raise HTTPException(status_code=409, detail="Replay requires the original import file.")
        previous_job = await jobs.for_import(db, record)
        if (
            record.mapping.get("mode") in {"source_only", "source_transaction_matched"}
            or previous_job is not None
            and previous_job.parameters.get("kind") != "owner"
        ):
            raise HTTPException(
                status_code=409,
                detail="Reviewed source imports cannot be replayed as owner spreadsheets.",
            )
        if record.status in ACTIVE_STATUSES:
            raise HTTPException(status_code=409, detail="This import is already processing.")
        if record.mapping.get("resolver_version") == IMPORT_RESOLVER_VERSION:
            return record
    elif record is not None:
        previous_job = await jobs.for_import(db, record)
        if previous_job is not None and previous_job.idempotency_key != fingerprint:
            raise HTTPException(
                status_code=409,
                detail="This file was already imported with different options. Use the original options or an explicit replay.",
            )
        return record

    # Every attempt owns a unique object. A failed deduplication race can only
    # delete its own blob, never the winner's object at a digest-derived key.
    key = f"crm/{organization_id}/import-inputs/{uuid4().hex}/input"
    await storage().upload(key, data)
    old_key = None
    try:
        if record is None:
            model = CrmInboundImport if kind == "inbound" else CrmContactImport
            record = model(
                organization_id=organization_id,
                created_by_user_id=user_id,
                name=name.strip()[:200] or Path(filename).stem[:200],
                original_filename=filename,
                sha256=digest,
                size_bytes=len(data),
                status="queued",
                mapping={},
                summary={},
                created_at=utcnow(),
            )
            db.add(record)
            await db.flush()
        job = await jobs.for_import(db, record) if replay else None
        if job is None:
            job = CrmImportJob(
                organization_id=organization_id,
                created_by_user_id=user_id,
                input_object_key=key,
                input_sha256=raw_digest,
                input_size_bytes=len(data),
                idempotency_key=fingerprint,
                parameters=parameters,
                owner_import_id=record.id if kind != "inbound" else None,
                inbound_import_id=record.id if kind == "inbound" else None,
            )
        else:
            old_key = job.input_object_key
            job.input_object_key = key
            job.input_sha256 = raw_digest
            job.input_size_bytes = len(data)
            job.idempotency_key = fingerprint
            job.parameters = parameters
            job.created_by_user_id = user_id
            job.status = "queued"
            job.attempt_count = 0
            job.available_at = job.updated_at = utcnow()
            job.completed_at = job.lease_expires_at = job.lease_token = job.last_error = None
        record.status = "queued"
        record.completed_at = None
        record.error_message = None
        db.add(record)
        db.add(job)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        await remove_input(key)
        winner = await repository.find_import_by_digest(
            db, *([digest, organization_id] if kind == "inbound" else [organization_id, digest])
        )
        if winner is None or replay:
            raise
        winner_job = await jobs.for_import(db, winner)
        if winner_job is not None and winner_job.idempotency_key != fingerprint:
            raise HTTPException(
                status_code=409, detail="This file was already imported with different options."
            ) from None
        return winner
    except BaseException:
        await db.rollback()
        # A connection failure can hide a successful COMMIT. Retain the object
        # unless PostgreSQL confirms it is unreferenced; an orphan is recoverable.
        try:
            referenced = await jobs.input_is_referenced(db, key)
        except Exception:
            logger.warning("CRM import input cleanup deferred until database recovery")
        else:
            if not referenced:
                await remove_input(key)
        raise
    if old_key:
        await remove_input(old_key)
    return record


async def delete_input_for_import(db, record) -> str | None:
    job = await jobs.for_import(db, record)
    return job.input_object_key if job else None
