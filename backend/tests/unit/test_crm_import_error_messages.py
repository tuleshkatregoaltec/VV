"""Import failures tell the client what it can act on, never internal exception text."""

import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile

from app.crm import imports, inbound_imports
from app.crm.import_models import CrmContactImport
from app.crm.import_safety import ImportInputError

SECRET = "connection to 10.0.3.7:5432 refused (password=hunter2) /srv/app/imports.py"


def _db():
    added: list[object] = []

    def give_ids(*_):
        for item in added:
            if getattr(item, "id", None) is None:
                item.id = 1

    db = MagicMock()
    db.add.side_effect = added.append
    for name in ("commit", "rollback", "delete", "exec"):
        setattr(db, name, AsyncMock())
    db.refresh = AsyncMock(side_effect=give_ids)
    db.flush = AsyncMock(side_effect=give_ids)
    db.added = added
    return db


async def _contact_import(db):
    return await imports._execute_contact_import(
        db,
        upload=UploadFile(
            file=io.BytesIO(b"NameEn,Mobile,UnitNumber\nAli,0501234567,1\n"), filename="o.csv"
        ),
        name="",
        user_id="user-1",
        organization_id="organization-1",
    )


@pytest.fixture
def contact_pipeline(monkeypatch):
    monkeypatch.setattr(
        imports.import_repository, "find_import_by_digest", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(imports, "delete_drop_log", AsyncMock())


async def test_contact_import_hides_internal_exception_text(monkeypatch, contact_pipeline):
    monkeypatch.setattr(imports, "run_in_thread", AsyncMock(side_effect=RuntimeError(SECRET)))
    db = _db()

    with pytest.raises(HTTPException) as failed:
        await _contact_import(db)

    assert failed.value.status_code == 422
    assert "hunter2" not in failed.value.detail and "10.0.3.7" not in failed.value.detail
    record = next(item for item in db.added if isinstance(item, CrmContactImport))
    assert record.status == "failed"
    assert "hunter2" not in (record.error_message or "")


async def test_contact_import_keeps_validation_messages(monkeypatch, contact_pipeline):
    monkeypatch.setattr(
        imports,
        "run_in_thread",
        AsyncMock(side_effect=ImportInputError("Import exceeds the 500,000-row limit")),
    )

    with pytest.raises(HTTPException) as failed:
        await _contact_import(_db())

    assert "500,000-row limit" in failed.value.detail


async def _inbound_preview():
    return await inbound_imports.preview_inbound_import(
        upload=UploadFile(file=io.BytesIO(b"a,b\n1,2\n"), filename="leads.csv"),
        campaign_context="",
    )


async def test_inbound_preview_hides_internal_exception_text(monkeypatch):
    monkeypatch.setattr(inbound_imports, "run_in_thread", AsyncMock(side_effect=KeyError(SECRET)))

    with pytest.raises(HTTPException) as failed:
        await _inbound_preview()

    assert failed.value.status_code == 422
    assert "hunter2" not in failed.value.detail and "10.0.3.7" not in failed.value.detail


async def test_inbound_preview_keeps_validation_messages(monkeypatch):
    monkeypatch.setattr(
        inbound_imports,
        "run_in_thread",
        AsyncMock(side_effect=ImportInputError("Upload a valid XLSX workbook")),
    )

    with pytest.raises(HTTPException) as failed:
        await _inbound_preview()

    assert "Upload a valid XLSX workbook" in failed.value.detail
