"""Google Calendar sign-in (PR 50 review finding 2): the consent a person gives at Google must
land on the account that started it, once. The PKCE verifier never leaves the server, the
link's state is a random single-use key, and completion requires the same signed-in user."""

from urllib.parse import parse_qs, urlparse

import pytest

from app.crm import calendar_service


class FakeCache:
    def __init__(self):
        self.store: dict[str, object] = {}

    async def put_new(self, key, value, expire=None):
        if key in self.store:
            return False
        self.store[key] = value
        return True

    async def take(self, key):
        return self.store.pop(key, None)


@pytest.fixture
def cache(monkeypatch):
    fake = FakeCache()
    monkeypatch.setattr(calendar_service, "cache", fake)
    monkeypatch.setattr(calendar_service, "configured", lambda: True)
    return fake


@pytest.fixture
def google(monkeypatch):
    """Records token exchanges instead of calling Google."""
    calls: list[dict] = []

    async def exchange(code, verifier):
        calls.append({"code": code, "verifier": verifier})
        return {"refresh_token": "refresh", "access_token": "access"}, "agent@example.com"

    async def store(db, **kwargs):
        calls.append({"stored": kwargs})

    monkeypatch.setattr(calendar_service, "_exchange_code", exchange)
    monkeypatch.setattr(calendar_service, "_store_connection", store)
    return calls


async def _state_of(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


async def test_the_link_carries_a_random_state_and_never_the_verifier(cache):
    url = await calendar_service.authorization_url("omar", "org")
    state = await _state_of(url)
    saved = cache.store[calendar_service.oauth_key(state)]

    assert saved["user_id"] == "omar" and saved["organization_id"] == "org"
    assert saved["verifier"] not in url
    assert "code_challenge" in url


async def test_completion_by_the_same_user_exchanges_once(cache, google):
    state = await _state_of(await calendar_service.authorization_url("omar", "org"))

    await calendar_service.finish_connection(
        None, code="c1", state=state, user_id="omar", organization_id="org"
    )

    assert google[0]["code"] == "c1" and google[0]["verifier"]
    assert google[1]["stored"]["user_id"] == "omar"
    with pytest.raises(ValueError, match="expired or was already used"):
        await calendar_service.finish_connection(
            None, code="c1", state=state, user_id="omar", organization_id="org"
        )


async def test_someone_else_cannot_complete_a_link_another_account_started(cache, google):
    state = await _state_of(await calendar_service.authorization_url("attacker", "org"))

    with pytest.raises(ValueError, match="another account"):
        await calendar_service.finish_connection(
            None, code="victim-code", state=state, user_id="victim", organization_id="org"
        )
    assert google == []  # Google's code was never exchanged


async def test_a_link_from_another_organization_is_refused(cache, google):
    state = await _state_of(await calendar_service.authorization_url("omar", "org-a"))

    with pytest.raises(ValueError, match="another account"):
        await calendar_service.finish_connection(
            None, code="c", state=state, user_id="omar", organization_id="org-b"
        )
    assert google == []


async def test_sign_in_does_not_start_when_the_state_cannot_be_saved(cache, monkeypatch):
    async def down(key, value, expire=None):
        return False

    monkeypatch.setattr(cache, "put_new", down)
    with pytest.raises(RuntimeError, match="Could not start"):
        await calendar_service.authorization_url("omar", "org")
