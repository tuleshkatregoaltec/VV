"""The connection status API tells the truth about whether automatic replies are running."""

from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.whatsapp import customer_connections as connections
from app.whatsapp import customer_repository as repository
from app.whatsapp.customer_models import WhatsAppConnection


def connection(enabled=True, status="connected"):
    return WhatsAppConnection(
        id="c1",
        user_id="u",
        organization_id="o",
        phone_number_id="p",
        account_id="w",
        display_name="Agent",
        access_token_encrypted="x",
        enabled=enabled,
        status=status,
    )


@pytest.fixture
def stored(monkeypatch):
    def put(row):
        monkeypatch.setattr(repository, "agent_connections", AsyncMock(return_value=[row]))
        monkeypatch.setattr(repository, "contact_counts", AsyncMock(return_value=(0, 0)))
        monkeypatch.setattr(
            repository,
            "admin_overview",
            AsyncMock(
                return_value=[
                    {
                        "connection": row,
                        "organization_name": "Org",
                        "contacts_total": 0,
                        "contacts_blocked": 0,
                        "last_message_at": None,
                    }
                ]
            ),
        )
        return row

    return put


def db():
    return AsyncMock()


async def status(config):
    return await connections.agent_status(db(), user_id="u", organization_id="o", config=config)


async def test_agent_switch_on_but_assistant_disabled_reports_paused_with_a_reason(stored):
    stored(connection(enabled=True))
    result = await status(settings.model_copy(update={"ASSISTANT_ENABLED": False}))
    assert result.automation_enabled is True  # the agent's own switch stays readable
    assert result.automation_active is False
    assert result.automation_paused_reason == "assistant_disabled"


async def test_agent_switch_on_and_assistant_enabled_reports_active(stored):
    stored(connection(enabled=True))
    result = await status(
        settings.model_copy(
            update={"ASSISTANT_ENABLED": True, "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": True}
        )
    )
    assert (result.automation_enabled, result.automation_active) == (True, True)
    assert result.automation_paused_reason is None


async def test_agent_switch_off_is_not_reported_as_paused_by_the_server(stored):
    stored(connection(enabled=False))
    result = await status(settings.model_copy(update={"ASSISTANT_ENABLED": False}))
    assert (result.automation_enabled, result.automation_active) == (False, False)
    assert result.automation_paused_reason is None


async def test_admin_summary_does_not_count_paused_connections_as_on(stored, monkeypatch):
    stored(connection(enabled=True))
    monkeypatch.setattr(
        "app.auth.service.get_user_by_id", AsyncMock(side_effect=RuntimeError("no auth"))
    )
    off = settings.model_copy(update={"ASSISTANT_ENABLED": False})
    overview = await connections.admin_connections(db(), config=off)
    assert overview.automation_on == 0
    assert overview.automation_paused == 1
    item = overview.items[0]
    assert item.automation_enabled is True
    assert item.automation_active is False
    assert item.automation_paused_reason == "assistant_disabled"
    on = settings.model_copy(
        update={"ASSISTANT_ENABLED": True, "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": True}
    )
    overview = await connections.admin_connections(db(), config=on)
    assert (overview.automation_on, overview.automation_paused) == (1, 0)


async def test_intake_flag_off_pauses_a_switched_on_agent_with_its_own_reason(stored):
    stored(connection(enabled=True))
    result = await status(
        settings.model_copy(
            update={"ASSISTANT_ENABLED": True, "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": False}
        )
    )
    assert result.automation_enabled is True
    assert result.automation_active is False
    assert result.automation_paused_reason == "intake_disabled"


async def test_intake_flag_on_and_assistant_on_reports_active(stored):
    stored(connection(enabled=True))
    result = await status(
        settings.model_copy(
            update={"ASSISTANT_ENABLED": True, "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": True}
        )
    )
    assert (result.automation_active, result.automation_paused_reason) == (True, None)


async def test_admin_summary_counts_intake_disabled_rows_as_paused(stored, monkeypatch):
    stored(connection(enabled=True))
    monkeypatch.setattr(
        "app.auth.service.get_user_by_id", AsyncMock(side_effect=RuntimeError("no auth"))
    )
    cfg = settings.model_copy(
        update={"ASSISTANT_ENABLED": True, "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": False}
    )
    overview = await connections.admin_connections(db(), config=cfg)
    assert (overview.automation_on, overview.automation_paused) == (0, 1)
    assert overview.items[0].automation_paused_reason == "intake_disabled"
