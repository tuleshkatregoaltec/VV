from types import SimpleNamespace

import httpx
import pytest

from app.whatsapp import service


def config():
    return SimpleNamespace(
        WHATSAPP_DEMO_ENABLED=True,
        WHATSAPP_VERIFY_TOKEN="verify",
        WHATSAPP_APP_SECRET="secret",
        WHATSAPP_ACCESS_TOKEN="private-token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        WHATSAPP_TEST_RECIPIENT="971500000000",
        WHATSAPP_GRAPH_API_VERSION="v26.0",
        WHATSAPP_TEST_TEMPLATE="hello_world",
        WHATSAPP_AUTOMATION_ENABLED=False,
        WHATSAPP_PILOT_USER_ID=None,
        WHATSAPP_PILOT_ORGANIZATION_ID=None,
    )


@pytest.mark.parametrize("template", ["hello_world", "jaspers_market_order_confirmation_v1"])
async def test_test_send_can_only_target_configured_recipient(monkeypatch, template):
    original_client = httpx.AsyncClient

    def respond(request):
        import json

        body = json.loads(request.content)
        assert str(request.url) == "https://graph.facebook.com/v26.0/123/messages"
        assert request.headers["authorization"] == "Bearer private-token"
        assert body["to"] == "971500000000"
        assert body["template"]["name"] == template
        if template == "jaspers_market_order_confirmation_v1":
            parameters = body["template"]["components"][0]["parameters"]
            assert len(parameters) == 3
            assert [item["text"] for item in parameters[:2]] == ["John Doe", "123456"]
        else:
            assert "components" not in body["template"]
        return httpx.Response(200, json={"messages": [{"id": "wamid.test"}]})

    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    settings = config()
    settings.WHATSAPP_TEST_TEMPLATE = template
    settings.WHATSAPP_APP_SECRET = None
    assert await service.send_test_template(settings) == "wamid.test"


async def test_incomplete_configuration_never_sends():
    settings = config()
    settings.WHATSAPP_ACCESS_TOKEN = None
    with pytest.raises(ValueError, match="incomplete"):
        await service.send_test_template(settings)
