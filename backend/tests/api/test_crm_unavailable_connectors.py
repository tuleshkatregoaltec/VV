"""Unqualified prototypes must not bypass the current assistant/WhatsApp boundaries."""

import pytest
from conftest import get_app


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/crm/email/status"),
        ("POST", "/api/v1/crm/email/send"),
        ("POST", "/api/v1/crm/email/brevo-webhook"),
        ("POST", "/api/v1/crm/email/brevo-inbound"),
        ("GET", "/api/v1/crm/calendar/google"),
        ("POST", "/api/v1/crm/calendar/google/connect"),
        ("GET", "/api/v1/crm/calendar/google/callback"),
        ("POST", "/api/v1/crm/calendar/events"),
        ("GET", "/api/v1/crm/whatsapp/status"),
        ("POST", "/api/v1/crm/whatsapp/webhook"),
        ("GET", "/api/v1/crm/assistant/conversations"),
        ("POST", "/api/v1/crm/assistant/voice"),
    ],
)
async def test_unfinished_connector_endpoints_are_unavailable_even_to_signed_in_users(
    client, method, path
):
    # Disabling credentials is insufficient: these endpoints and their side effects
    # must remain absent until they meet deployed tenancy, persistence and consent rules.
    assert (await client.request(method, path, json={})).status_code == 404


def test_no_prototype_route_is_registered_even_if_hidden_from_openapi():
    forbidden = (
        "/api/v1/crm/email",
        "/api/v1/crm/calendar",
        "/api/v1/crm/whatsapp",
        "/api/v1/crm/assistant",
    )
    assert not [route.path for route in get_app().routes if route.path.startswith(forbidden)]
    routes = {route.path for route in get_app().routes}
    assert {
        "/api/v1/chat/conversations",
        "/api/v1/assistant/actions/proposals",
        "/api/v1/whatsapp/connection",
        "/api/v1/whatsapp/signup/complete",
        "/api/v1/webhooks/whatsapp",
    } <= routes


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/chat/conversations",
        "/api/v1/assistant/actions/reminders",
        "/api/v1/whatsapp/connection",
        "/api/v1/whatsapp/connections",
    ],
)
async def test_current_shared_assistant_and_whatsapp_routes_still_require_auth(
    client_no_auth, path
):
    assert (await client_no_auth.get(path)).status_code in {401, 403}
