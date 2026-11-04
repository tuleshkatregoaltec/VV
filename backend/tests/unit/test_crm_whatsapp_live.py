import fakeredis
import pytest
from conftest import get_app, make_mock_auth_context
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.crm.whatsapp import live

LIVE = "/api/v1/crm/whatsapp/live"


def test_agents_only_hear_about_chats_on_their_own_number():
    """An agent must not learn that a colleague's customer wrote in."""
    mine = {"purpose": "agent", "user_id": "sara", "wa_id": "1"}
    theirs = {"purpose": "agent", "user_id": "omar", "wa_id": "1"}
    assert live.visible_to(mine, user_id="sara", owner=False)
    assert not live.visible_to(theirs, user_id="sara", owner=False)
    # Being an owner does not open other agents' chats either.
    assert not live.visible_to(theirs, user_id="sara", owner=True)


def test_campaign_replies_are_for_owners_only():
    """The campaign inbox is an owner screen; agents get leads handed over, not the inbox."""
    change = {"purpose": "campaign", "user_id": None, "wa_id": "1"}
    assert live.visible_to(change, user_id="sara", owner=True)
    assert not live.visible_to(change, user_id="sara", owner=False)


@pytest.fixture
def fake_redis(monkeypatch):
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        live, "_client", lambda: fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    )
    return server


@pytest.fixture
def signed_in(monkeypatch):
    context = make_mock_auth_context()

    async def verify(token):
        return context.user if token == "good" else None

    async def membership(user, db):
        return context

    async def session():
        yield None

    monkeypatch.setattr(live, "verify_user", verify)
    monkeypatch.setattr(live, "require_membership", membership)
    monkeypatch.setattr(live, "get_db_session", session)
    return context


def test_a_socket_without_a_valid_token_is_closed_before_it_hears_anything(fake_redis, signed_in):
    with TestClient(get_app()) as client, client.websocket_connect(LIVE) as ws:
        ws.send_json({"token": "forged"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == live.UNAUTHORIZED


def test_a_new_message_reaches_its_agent_live(fake_redis, signed_in):
    """The point of the socket: Sara sees her customer's message without reloading, and never a
    colleague's."""
    org = str(signed_in.organization.id)
    me = str(signed_in.user.id)
    with TestClient(get_app()) as client, client.websocket_connect(LIVE) as ws:
        ws.send_json({"token": "good"})
        assert ws.receive_json() == {"type": "ready"}

        changes = {
            live.ChatChange(wa_id="971500000001", purpose="agent", user_id="someone-else"),
        }
        client.portal.call(live.publish, org, changes)
        client.portal.call(
            live.publish, org, {live.ChatChange(wa_id="971500000002", purpose="agent", user_id=me)}
        )
        assert ws.receive_json() == {"type": "chat.changed", "wa_id": "971500000002"}


async def test_publish_never_fails_the_webhook_when_redis_is_down(monkeypatch):
    class Down:
        async def publish(self, *args):
            raise ConnectionError("redis down")

        async def aclose(self):
            pass

    monkeypatch.setattr(live, "_client", lambda: Down())
    await live.publish("org", {live.ChatChange(wa_id="1", purpose="agent", user_id="u")})
