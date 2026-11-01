"""PostgreSQL leases and transactional publication fencing for CRM imports."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.import_job_models import CrmImportJob, utcnow
from app.crm.import_models import CrmContactImport
from app.crm.inbound_models import CrmInboundImport
from app.organization.models import Organization, OrganizationMembership


class LostImportLease(Exception):
    """Another attempt owns the job, the lease expired, or the import was deleted."""


class ImportAuthorizationRevoked(Exception):
    """The original creator can no longer write into the original organization."""


async def target(db: AsyncSession, job: CrmImportJob):
    model = CrmContactImport if job.owner_import_id is not None else CrmInboundImport
    import_id = job.owner_import_id if job.owner_import_id is not None else job.inbound_import_id
    return (
        await db.exec(
            select(model).where(model.id == import_id, model.organization_id == job.organization_id)
        )
    ).first()


async def for_import(db: AsyncSession, record):
    field = (
        CrmImportJob.owner_import_id
        if isinstance(record, CrmContactImport)
        else CrmImportJob.inbound_import_id
    )
    return (
        await db.exec(
            select(CrmImportJob).where(
                field == record.id, CrmImportJob.organization_id == record.organization_id
            )
        )
    ).first()


async def authorize(db: AsyncSession, job: CrmImportJob, *, lock: bool = False) -> None:
    statement = (
        select(OrganizationMembership)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .where(
            OrganizationMembership.organization_id == job.organization_id,
            OrganizationMembership.user_id == job.created_by_user_id,
            Organization.subscription_status.in_(("active", "trialing")),
        )
    )
    if lock:
        statement = statement.with_for_update(read=True)
    if (await db.exec(statement)).first() is None:
        raise ImportAuthorizationRevoked()


async def lock_lease(db: AsyncSession, job_id: str, token: str) -> CrmImportJob:
    # Prevent autoflush from publishing before the fence has been checked. Flushes
    # earlier in the operation remain uncommitted and are rolled back on failure.
    with db.no_autoflush:
        job = (
            await db.exec(
                select(CrmImportJob)
                .where(
                    CrmImportJob.id == job_id,
                    CrmImportJob.status == "processing",
                    CrmImportJob.lease_token == token,
                    CrmImportJob.lease_expires_at > func.clock_timestamp(),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).first()
    if job is None:
        raise LostImportLease()
    return job


async def publish(db: AsyncSession, job_id: str, token: str) -> None:
    job = await lock_lease(db, job_id, token)
    await authorize(db, job, lock=True)
    job.status = "completed"
    job.completed_at = job.updated_at = utcnow()
    job.lease_token = None
    job.lease_expires_at = None
    job.last_error = None
    db.add(job)
    await db.commit()


async def heartbeat(db: AsyncSession, job_id: str, token: str, lease_seconds: int) -> bool:
    job = await lock_lease(db, job_id, token)
    job.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)
    job.updated_at = utcnow()
    db.add(job)
    await db.commit()
    return True


async def _set_status(db: AsyncSession, job: CrmImportJob, status: str, error: str | None = None):
    record = await target(db, job)
    if record is None:
        return
    # A failed replay retains the last published result and its summary.
    replay = job.parameters.get("reprocess_import_id") is not None
    record.status = "completed" if replay and status == "failed" else status
    record.error_message = error
    record.completed_at = utcnow() if status == "failed" else None
    db.add(record)


async def reconcile(db: AsyncSession, *, limit: int = 100) -> int:
    exhausted = (
        await db.exec(
            select(CrmImportJob)
            .where(
                CrmImportJob.status.in_(("processing", "retry_wait", "queued")),
                CrmImportJob.attempt_count >= CrmImportJob.max_attempts,
                or_(
                    CrmImportJob.status != "processing",
                    CrmImportJob.lease_expires_at <= func.clock_timestamp(),
                ),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for job in exhausted:
        job.status = "failed"
        job.last_error = "Import worker exhausted its retry limit"
        job.lease_token = None
        job.lease_expires_at = None
        job.completed_at = job.updated_at = utcnow()
        db.add(job)
        await _set_status(db, job, "failed", job.last_error)
    await db.commit()
    return len(exhausted)


async def claim(db: AsyncSession, *, lease_seconds: int = 120) -> CrmImportJob | None:
    await reconcile(db)
    job = (
        await db.exec(
            select(CrmImportJob)
            .where(
                CrmImportJob.attempt_count < CrmImportJob.max_attempts,
                or_(
                    and_(
                        CrmImportJob.status.in_(("queued", "retry_wait")),
                        CrmImportJob.available_at <= func.clock_timestamp(),
                    ),
                    and_(
                        CrmImportJob.status == "processing",
                        CrmImportJob.lease_expires_at <= func.clock_timestamp(),
                    ),
                ),
            )
            .order_by(CrmImportJob.available_at, CrmImportJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).first()
    if job is None:
        await db.rollback()
        return None
    job.status = "processing"
    job.attempt_count += 1
    job.lease_token = str(uuid4())
    job.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)
    job.updated_at = utcnow()
    db.add(job)
    await _set_status(db, job, "processing")
    await db.commit()
    return job


async def fail(db: AsyncSession, job_id: str, token: str, *, error: str, permanent: bool) -> bool:
    try:
        job = await lock_lease(db, job_id, token)
    except LostImportLease:
        await db.rollback()
        return False
    terminal = permanent or job.attempt_count >= job.max_attempts
    job.status = "failed" if terminal else "retry_wait"
    job.last_error = error[:200]
    job.updated_at = utcnow()
    job.completed_at = utcnow() if terminal else None
    job.available_at = utcnow() + timedelta(seconds=min(300, 5 * 2**job.attempt_count))
    job.lease_expires_at = None
    job.lease_token = None
    db.add(job)
    await _set_status(db, job, job.status, job.last_error)
    await db.commit()
    return True


async def input_is_referenced(db: AsyncSession, key: str) -> bool:
    return (
        await db.exec(select(CrmImportJob.id).where(CrmImportJob.input_object_key == key))
    ).first() is not None
