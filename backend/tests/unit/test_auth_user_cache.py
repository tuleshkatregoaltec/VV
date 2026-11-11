"""Short-lived cache of successful auth-service token checks."""

import asyncio
import base64
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis
import pytest
from supabase_auth import User as AuthUser
from supabase_auth.errors import AuthApiError

from app.providers.auth import client
from app.providers.auth.user_cache import AuthUserCache


def make_token(exp: float | None, sub: str = "user-1", nonce: str = "a") -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    claims: dict = {"sub": sub, "nonce": nonce}
    if exp is not None:
        claims["exp"] = int(exp)
    return f"{part({'alg': 'HS256'})}.{part(claims)}.signature-{nonce}"


def make_user(user_id: str = "user-1", first_name: str = "") -> AuthUser:
    return AuthUser(
        id=user_id,
        app_metadata={"is_admin": False},
        user_metadata={"first_name": first_name, "last_name": ""},
        aud="authenticated",
        created_at="2026-01-01T00:00:00Z",
        email=f"{user_id}@example.com",
    )


@pytest.fixture
def redis_client():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def user_cache(redis_client, monkeypatch):
    cache = AuthUserCache(redis_client, ttl_seconds=60, max_entries=100)
    monkeypatch.setattr(client, "_user_cache", cache)
    return cache


@pytest.fixture
def auth_service(monkeypatch):
    service = SimpleNamespace(get_user=AsyncMock())
    monkeypatch.setattr(client, "auth_client", service)
    return service


def answer(user: AuthUser | None):
    return SimpleNamespace(user=user)


async def test_second_check_of_same_token_is_served_from_cache(user_cache, auth_service):
    token = make_token(time.time() + 3600)
    auth_service.get_user.return_value = answer(make_user())

    first = await client.get_auth_user(token)
    second = await client.get_auth_user(token)

    assert first is not None and second is not None
    assert second.id == "user-1"
    assert second == first
    auth_service.get_user.assert_awaited_once_with(jwt=token)


async def test_different_tokens_each_miss_once(user_cache, auth_service):
    auth_service.get_user.return_value = answer(make_user())

    await client.get_auth_user(make_token(time.time() + 3600, nonce="a"))
    await client.get_auth_user(make_token(time.time() + 3600, nonce="b"))

    assert auth_service.get_user.await_count == 2


async def test_failed_checks_are_not_cached(user_cache, auth_service):
    token = make_token(time.time() + 3600)

    auth_service.get_user.side_effect = AuthApiError("bad jwt", 401, "bad_jwt")
    assert await client.get_auth_user(token) is None
    auth_service.get_user.side_effect = ConnectionError("auth down")
    assert await client.get_auth_user(token) is None
    auth_service.get_user.side_effect = None
    auth_service.get_user.return_value = answer(None)
    assert await client.get_auth_user(token) is None

    # nothing was stored, so a later good answer is used immediately
    auth_service.get_user.return_value = answer(make_user())
    assert await client.get_auth_user(token) is not None
    assert auth_service.get_user.await_count == 4


async def test_cache_entry_expires_after_ttl(redis_client, monkeypatch, auth_service):
    cache = AuthUserCache(redis_client, ttl_seconds=0.1, max_entries=100)
    monkeypatch.setattr(client, "_user_cache", cache)
    token = make_token(time.time() + 3600)
    auth_service.get_user.return_value = answer(make_user())

    await client.get_auth_user(token)
    await client.get_auth_user(token)
    assert auth_service.get_user.await_count == 1

    await asyncio.sleep(0.2)
    await client.get_auth_user(token)
    assert auth_service.get_user.await_count == 2


async def test_ttl_is_capped_at_token_expiry(user_cache, redis_client, auth_service):
    token = make_token(time.time() + 5)
    auth_service.get_user.return_value = answer(make_user())

    await client.get_auth_user(token)

    keys = [k async for k in redis_client.scan_iter(match="auth:jwt:*")]
    assert len(keys) == 1
    assert 0 < await redis_client.pttl(keys[0]) <= 5000


async def test_default_ttl_is_sixty_seconds_for_long_lived_tokens(
    user_cache, redis_client, auth_service
):
    token = make_token(time.time() + 3600)
    auth_service.get_user.return_value = answer(make_user())

    await client.get_auth_user(token)

    keys = [k async for k in redis_client.scan_iter(match="auth:jwt:*")]
    assert 59_000 < await redis_client.pttl(keys[0]) <= 60_000


@pytest.mark.parametrize("exp", [None, time.time() - 10])
async def test_tokens_without_usable_expiry_are_not_cached(user_cache, auth_service, exp):
    token = make_token(exp)
    auth_service.get_user.return_value = answer(make_user())

    await client.get_auth_user(token)
    await client.get_auth_user(token)

    assert auth_service.get_user.await_count == 2


async def test_malformed_token_is_checked_but_never_cached(user_cache, auth_service):
    auth_service.get_user.return_value = answer(make_user())

    await client.get_auth_user("not-a-jwt")
    await client.get_auth_user("not-a-jwt")

    assert auth_service.get_user.await_count == 2


async def test_raw_token_is_never_stored_or_used_as_a_key(user_cache, redis_client, auth_service):
    token = make_token(time.time() + 3600)
    auth_service.get_user.return_value = answer(make_user())

    await client.get_auth_user(token)

    for key in [k async for k in redis_client.scan_iter(match="*")]:
        assert token not in key
        assert token.split(".")[2] not in key
        assert token not in str(await redis_client.type(key))
        if await redis_client.type(key) == "string":
            assert token not in await redis_client.get(key)
        if await redis_client.type(key) == "set":
            assert token not in "".join(await redis_client.smembers(key))


async def test_invalidating_a_user_drops_all_their_tokens_and_only_theirs(user_cache, auth_service):
    mine_a = make_token(time.time() + 3600, nonce="a")
    mine_b = make_token(time.time() + 3600, nonce="b")
    other = make_token(time.time() + 3600, sub="user-2", nonce="c")
    auth_service.get_user.side_effect = lambda jwt: answer(
        make_user("user-2" if jwt == other else "user-1")
    )
    for token in (mine_a, mine_b, other):
        await client.get_auth_user(token)
    assert auth_service.get_user.await_count == 3

    await user_cache.invalidate_user("user-1")

    await client.get_auth_user(mine_a)
    await client.get_auth_user(mine_b)
    assert auth_service.get_user.await_count == 5
    await client.get_auth_user(other)
    assert auth_service.get_user.await_count == 5


async def test_check_that_started_before_an_invalidation_is_not_stored(user_cache, auth_service):
    token = make_token(time.time() + 3600)

    async def slow_check(jwt):
        # a profile update lands while this (now stale) check is in flight
        await user_cache.invalidate_user("user-1")
        return answer(make_user(first_name=""))

    auth_service.get_user.side_effect = slow_check
    await client.get_auth_user(token)

    auth_service.get_user.side_effect = None
    auth_service.get_user.return_value = answer(make_user(first_name="Ada"))
    fresh = await client.get_auth_user(token)

    assert fresh.user_metadata["first_name"] == "Ada"


async def test_cache_is_bounded_in_size(redis_client, monkeypatch, auth_service):
    cache = AuthUserCache(redis_client, ttl_seconds=60, max_entries=2)
    monkeypatch.setattr(client, "_user_cache", cache)
    auth_service.get_user.return_value = answer(make_user())

    for nonce in "abcd":
        await client.get_auth_user(make_token(time.time() + 3600, nonce=nonce))

    stored = [k async for k in redis_client.scan_iter(match="auth:jwt:*")]
    assert len(stored) == 2


async def test_cache_outage_falls_back_to_the_auth_service(monkeypatch, auth_service):
    broken = SimpleNamespace(
        get=AsyncMock(side_effect=ConnectionError("redis down")),
        pipeline=lambda **_: (_ for _ in ()).throw(ConnectionError("redis down")),
    )
    monkeypatch.setattr(client, "_user_cache", AuthUserCache(broken))
    auth_service.get_user.return_value = answer(make_user())

    user = await client.get_auth_user(make_token(time.time() + 3600))

    assert user is not None and user.id == "user-1"


async def test_profile_update_shows_up_on_the_next_check(user_cache, auth_service, monkeypatch):
    token = make_token(time.time() + 3600)
    auth_service.get_user.return_value = answer(make_user(first_name=""))
    before = await client.get_auth_user(token)
    assert before.user_metadata["first_name"] == ""

    admin = SimpleNamespace(
        get_user_by_id=AsyncMock(
            return_value=SimpleNamespace(user=SimpleNamespace(user_metadata={}))
        ),
        update_user_by_id=AsyncMock(),
    )
    monkeypatch.setattr(client, "admin_client", SimpleNamespace(admin=admin))
    await client.update_user_profile_metadata("user-1", "Ada", "Lovelace")

    auth_service.get_user.return_value = answer(make_user(first_name="Ada"))
    after = await client.get_auth_user(token)
    assert after.user_metadata["first_name"] == "Ada"


async def test_token_limit_update_shows_up_on_the_next_check(user_cache, auth_service, monkeypatch):
    token = make_token(time.time() + 3600)
    auth_service.get_user.return_value = answer(make_user())
    await client.get_auth_user(token)

    admin = SimpleNamespace(
        get_user_by_id=AsyncMock(
            return_value=SimpleNamespace(user=SimpleNamespace(app_metadata={}))
        ),
        update_user_by_id=AsyncMock(),
    )
    monkeypatch.setattr(client, "admin_client", SimpleNamespace(admin=admin))
    await client.update_user_token_limit("user-1", 10)

    await client.get_auth_user(token)
    assert auth_service.get_user.await_count == 2


async def test_deleted_user_is_no_longer_authenticated_from_cache(
    user_cache, auth_service, monkeypatch
):
    token = make_token(time.time() + 3600)
    auth_service.get_user.return_value = answer(make_user())
    assert await client.get_auth_user(token) is not None

    admin = SimpleNamespace(delete_user=AsyncMock())
    monkeypatch.setattr(client, "admin_client", SimpleNamespace(admin=admin))
    await client.delete_user_admin("user-1")

    auth_service.get_user.side_effect = AuthApiError("User from sub claim does not exist", 403, "x")
    assert await client.get_auth_user(token) is None


async def test_failed_admin_update_still_invalidates(user_cache, auth_service, monkeypatch):
    token = make_token(time.time() + 3600)
    auth_service.get_user.return_value = answer(make_user())
    await client.get_auth_user(token)

    admin = SimpleNamespace(
        get_user_by_id=AsyncMock(
            return_value=SimpleNamespace(user=SimpleNamespace(user_metadata={}))
        ),
        update_user_by_id=AsyncMock(side_effect=AuthApiError("boom", 500, "x")),
    )
    monkeypatch.setattr(client, "admin_client", SimpleNamespace(admin=admin))
    with pytest.raises(AuthApiError):
        await client.update_user_profile_metadata("user-1", "Ada", "Lovelace")

    await client.get_auth_user(token)
    assert auth_service.get_user.await_count == 2
