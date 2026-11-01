"""Network chunking must not permanently reject valid durable import inputs."""

import hashlib
import io
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiobotocore.response import StreamingBody

from app.crm import import_jobs, import_worker
from app.crm.import_job_models import CrmImportJob


def streaming_input(monkeypatch, saved, actual, *, kind="owner", content_length=None):
    stream = io.BytesIO(actual)

    async def read_chunk(amount):
        # A network read may finish before filling the requested buffer.
        return stream.read(min(amount, 3))

    class Response:
        content = SimpleNamespace(read=AsyncMock(side_effect=read_chunk))
        closed = False

        async def read(self):
            return stream.read()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

    response = Response()
    body = StreamingBody(response, str(len(actual)))
    s3 = SimpleNamespace(
        get_object=AsyncMock(
            return_value={
                "Body": body,
                "ContentLength": len(actual) if content_length is None else content_length,
            }
        )
    )

    @asynccontextmanager
    async def client():
        yield s3

    monkeypatch.setattr(
        import_jobs, "storage", lambda: SimpleNamespace(client=client, bucket_name="private")
    )
    job = CrmImportJob(
        organization_id="tenant",
        created_by_user_id="creator",
        input_object_key="private/input.csv",
        input_size_bytes=len(saved),
        input_sha256=hashlib.sha256(saved).hexdigest(),
        idempotency_key="digest",
        parameters={"kind": kind},
    )
    return job, response, stream


@pytest.mark.parametrize("kind", ["owner", "inbound", "source_only"])
async def test_short_network_reads_reassemble_verified_input(monkeypatch, kind):
    data = b"Name,Phone\nExample,0501111111\n"
    job, response, stream = streaming_input(monkeypatch, data, data, kind=kind)
    assert await import_worker.read_input(job) == data
    assert response.closed
    assert stream.tell() == len(data)
    assert response.content.read.await_count > 2


@pytest.mark.parametrize("actual", [b"short", b"different!", b"saved-data-extra-bytes"])
async def test_invalid_stream_is_rejected_and_reads_stop_at_saved_size(monkeypatch, actual):
    saved = b"saved-data"
    job, response, stream = streaming_input(monkeypatch, saved, actual)
    with pytest.raises(import_worker.InvalidImportInput, match="checksum and size"):
        await import_worker.read_input(job)
    assert response.closed
    assert stream.tell() <= len(saved) + 1


async def test_oversized_response_is_closed_without_reading(monkeypatch):
    job, response, stream = streaming_input(
        monkeypatch, b"saved", b"saved", content_length=50 * 1024 * 1024 + 1
    )
    with pytest.raises(import_worker.InvalidImportInput, match="size limit"):
        await import_worker.read_input(job)
    assert response.closed
    assert stream.tell() == 0
