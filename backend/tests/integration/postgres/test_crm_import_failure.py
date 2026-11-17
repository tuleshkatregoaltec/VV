"""An upstream failure must leave a retryable report, not an orphaned processing row."""

import io
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from sqlmodel import select

from app.crm import imports
from app.crm.import_models import CrmContactImport, CrmPropertyContactClaim


async def test_warehouse_failure_is_recorded_after_session_rollback(pg_session, monkeypatch):
    monkeypatch.setattr(imports, "_llm_mapping", AsyncMock(side_effect=lambda profile: profile))
    monkeypatch.setattr(
        imports,
        "prepare_file_context",
        AsyncMock(side_effect=RuntimeError("Warehouse unavailable")),
    )
    monkeypatch.setattr(imports, "delete_drop_log", AsyncMock())
    org = str(uuid4())
    with pytest.raises(HTTPException) as error:
        await imports._execute_contact_import(
            pg_session,
            upload=UploadFile(
                file=io.BytesIO(b"NameEn,BuildingNameEn,UnitNumber\nExample,Tower,101\n"),
                filename="failure.csv",
            ),
            name="Failure regression",
            user_id=str(uuid4()),
            organization_id=org,
        )
    assert error.value.status_code == 422
    record = (
        await pg_session.exec(
            select(CrmContactImport).where(CrmContactImport.organization_id == org)
        )
    ).one()
    assert record.status == "failed"
    # Persist a retryable, client-safe report without exposing upstream exception details.
    assert record.error_message == "The file could not be processed. Check it and try again."
    assert error.value.detail == f"Import failed: {record.error_message}"
    assert "Warehouse unavailable" not in error.value.detail
    assert record.completed_at is not None
    assert not (
        await pg_session.exec(
            select(CrmPropertyContactClaim).where(CrmPropertyContactClaim.import_id == record.id)
        )
    ).all()
