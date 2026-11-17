"""Admin failures reach the client as a generic message; the cause is logged server-side."""

import logging
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.admin import service
from app.admin.models import CreateUserRequest

SECRET = "supabase says: key sk_live_123 rejected for host db.internal"


async def test_create_user_failure_does_not_leak_the_exception(monkeypatch, caplog):
    monkeypatch.setattr(service, "create_user_admin", AsyncMock(side_effect=RuntimeError(SECRET)))
    request = CreateUserRequest(
        email="a@b.co",
        password="pw-123456",
        first_name="A",
        last_name="B",
        org_mode="new",
        org_name="Acme",
    )
    with caplog.at_level(logging.ERROR), pytest.raises(HTTPException) as caught:
        await service.create_user(request, db=AsyncMock())
    assert caught.value.status_code == 400
    assert SECRET not in str(caught.value.detail)
    assert "sk_live" not in str(caught.value.detail)
    assert SECRET in caplog.text


async def test_delete_user_failure_does_not_leak_the_exception(monkeypatch, caplog):
    monkeypatch.setattr(service, "get_membership_for_user", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "delete_user_admin", AsyncMock(side_effect=RuntimeError(SECRET)))
    with caplog.at_level(logging.ERROR), pytest.raises(HTTPException) as caught:
        await service.delete_user("user-1", db=AsyncMock())
    assert caught.value.status_code == 400
    assert SECRET not in str(caught.value.detail)
    assert SECRET in caplog.text
