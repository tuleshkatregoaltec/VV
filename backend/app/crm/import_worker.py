"""One leased CRM import per bounded child process; no HTTP background tasks."""

import argparse
import asyncio
import hashlib
import io
import logging
import os
import resource
import subprocess
import sys
import time
from contextlib import suppress

from botocore.exceptions import ClientError
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import import_job_repository as jobs
from app.crm import import_jobs
from app.crm.import_job_models import CrmImportJob
from app.postgres.client import get_postgres_engine

logger = logging.getLogger(__name__)


class InvalidImportInput(Exception):
    pass


async def read_input(job: CrmImportJob) -> bytes:
    """Bound reads even if the private object has been replaced with a larger one."""
    client = import_jobs.storage()
    limit = 100 * 1024 * 1024 if job.parameters.get("kind") == "source_only" else 50 * 1024 * 1024
    if not 0 < job.input_size_bytes <= limit:
        raise InvalidImportInput("Invalid input size")
    async with client.client() as s3:
        response = await s3.get_object(Bucket=client.bucket_name, Key=job.input_object_key)
        body = response["Body"]
        async with body:
            if response.get("ContentLength", 0) > limit:
                raise InvalidImportInput("Input object exceeds its size limit")
            data = bytearray()
            # The context yields the raw HTTP response; use the SDK wrapper so
            # reads stay bounded, and allow short network chunks before EOF.
            while len(data) <= job.input_size_bytes:
                chunk = await body.read(min(1024 * 1024, job.input_size_bytes + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
    if len(data) != job.input_size_bytes or hashlib.sha256(data).hexdigest() != job.input_sha256:
        raise InvalidImportInput("Input object does not match its saved checksum and size")
    return bytes(data)


async def _heartbeat(factory, job_id: str, token: str, lease_seconds: int):
    while True:
        await asyncio.sleep(lease_seconds / 3)
        try:
            async with factory() as db:
                await jobs.heartbeat(db, job_id, token, lease_seconds)
        except Exception:
            logger.warning("CRM import heartbeat stopped; publication still requires a valid lease")
            return


def _actor(job: CrmImportJob):
    from app.postgres.actor_context import transaction_actor

    return transaction_actor(
        actor_id=job.created_by_user_id, organization_id=job.organization_id, request_id=job.id
    )


async def run_once(factory, *, lease_seconds: int = 120) -> bool:
    async with factory() as db:
        job = await jobs.claim(db, lease_seconds=lease_seconds)
    if job is None:
        return False
    job_id, token = job.id, job.lease_token
    heartbeat = asyncio.create_task(_heartbeat(factory, job_id, token, lease_seconds))
    try:
        async with factory() as auth_db:
            await jobs.authorize(auth_db, job)
        data = await read_input(job)
        with _actor(job):
            async with factory() as db:
                await jobs.authorize(db, job)
                record = await jobs.target(db, job)
                if record is None:
                    raise jobs.LostImportLease()
                kind = job.parameters["kind"]
                if kind == "owner":
                    from app.crm.imports import _execute_contact_import as execute
                elif kind == "inbound":
                    from app.crm.inbound_imports import _execute_inbound_import as execute
                elif kind == "source_only":
                    from app.crm.source_audit import _execute_source_audit_import as execute
                else:
                    raise InvalidImportInput("Unknown import kind")
                kwargs = {
                    key: job.parameters[key]
                    for key in (
                        "mapping_override",
                        "campaign_context",
                        "reprocess_import_id",
                        "assignment_policy",
                    )
                    if key in job.parameters
                }
                if kind == "source_only":
                    kwargs = {}
                elif kind == "owner":
                    kwargs["_drop_log_revision"] = token

                async def commit():
                    await jobs.publish(db, job_id, token)

                await execute(
                    db,
                    upload=UploadFile(file=io.BytesIO(data), filename=record.original_filename),
                    name=job.parameters.get("source_name", record.name),
                    user_id=job.created_by_user_id,
                    organization_id=job.organization_id,
                    _record=record,
                    _commit=commit,
                    **kwargs,
                )
    except jobs.LostImportLease:
        logger.info("CRM import attempt lost its lease")
    except Exception as exc:
        missing = isinstance(exc, ClientError) and exc.response.get("Error", {}).get("Code") in {
            "NoSuchKey",
            "NoSuchBucket",
            "404",
        }
        permanent = missing or (
            isinstance(exc, (InvalidImportInput, jobs.ImportAuthorizationRevoked, ValueError))
            or isinstance(exc, HTTPException)
            and 400 <= exc.status_code < 500
        )
        if missing:
            error = "Import input object is missing"
        elif isinstance(exc, jobs.ImportAuthorizationRevoked):
            error = "Import creator membership or active subscription was revoked"
        elif isinstance(exc, InvalidImportInput):
            error = str(exc)
        elif isinstance(exc, HTTPException):
            error = "Import input could not be processed"
        elif isinstance(exc, ValueError):
            error = "Import input or mapping is invalid"
        else:
            error = "Import worker dependency failed"
        # Never copy raw row/contact/provider exceptions into job logs.
        logger.warning("CRM import attempt failed (%s)", type(exc).__name__)
        async with factory() as db:
            await jobs.fail(db, job_id, token, error=error, permanent=permanent)
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError, jobs.LostImportLease):
            await heartbeat
    return True


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--once", action="store_true", help="Run at most one job and exit")
    result.add_argument("--execute-one", action="store_true", help=argparse.SUPPRESS)
    result.add_argument("--lease-seconds", type=int, default=120)
    result.add_argument("--wall-seconds", type=int, default=1800)
    result.add_argument("--memory-mib", type=int, default=2048)
    result.add_argument("--poll-seconds", type=int, default=5)
    return result


def main():
    cli = parser()
    args = cli.parse_args()
    for value, minimum, maximum, label in (
        (args.lease_seconds, 30, 900, "lease-seconds"),
        (args.wall_seconds, 30, 3600, "wall-seconds"),
        (args.memory_mib, 512, 8192, "memory-mib"),
        (args.poll_seconds, 1, 60, "poll-seconds"),
    ):
        if not minimum <= value <= maximum:
            cli.error(f"{label} must be between {minimum} and {maximum}")
    if args.execute_one:
        if sys.platform != "darwin":
            resource.setrlimit(resource.RLIMIT_AS, (args.memory_mib * 1024 * 1024,) * 2)
        factory = async_sessionmaker(
            get_postgres_engine(), class_=AsyncSession, expire_on_commit=False
        )
        return 0 if asyncio.run(run_once(factory, lease_seconds=args.lease_seconds)) else 3
    while True:
        outcome = 0
        try:
            child = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app.crm.import_worker",
                    "--execute-one",
                    "--lease-seconds",
                    str(args.lease_seconds),
                    "--memory-mib",
                    str(args.memory_mib),
                ],
                timeout=args.wall_seconds,
                check=False,
                env=os.environ,
            )
            if child.returncode not in (0, 3):
                outcome = 1
                logger.warning(
                    "CRM import worker process exited (%s); lease reconciliation will recover its job",
                    child.returncode,
                )
        except subprocess.TimeoutExpired:
            outcome = 1
            logger.warning(
                "CRM import worker exceeded its wall limit; lease reconciliation will recover its job"
            )
        if args.once:
            return outcome
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
