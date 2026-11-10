"""Short-lived Redis cache of successful auth-service token checks.

Every authenticated API request asks the auth service who a bearer token belongs to. With a hosted
auth service that is tens of milliseconds per request, so successful answers are kept for a short
time. Redis is shared by every uvicorn worker, so invalidation done by one worker reaches all of them.

Rules:
- Only successful answers are stored. Failures and unreachable-service errors are never cached.
- Keys are a SHA-256 of the token. The raw token is never a key, a value or a log line.
- Lifetime is the TTL (60 s by default) but never beyond the token's own `exp`. A token without a
  readable future `exp` is not cached.
- Size is bounded: at most `max_entries` live entries, beyond which new answers are simply not stored.
- Anything that changes a user through this backend calls `invalidate_user`, so the next request
  re-reads the auth service. A check that started before an invalidation is not stored, which closes the
  race where a stale in-flight answer would be cached after the update.
- Any Redis error is swallowed: the cache is an optimisation and the auth service stays the authority.

Accepted staleness: a token that was signed out, or a user changed or banned directly in the auth
service (not through this backend), stays accepted for up to the TTL.
"""

import base64
import hashlib
import json
import logging
import time
from typing import Any, Optional

from supabase_auth import User as AuthUser

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 60.0
DEFAULT_MAX_ENTRIES = 10_000
# How long an invalidation is remembered, to reject answers from checks that were already in flight.
_INVALIDATION_MEMORY_MS = 120_000

_ENTRY = "auth:jwt:"
_USER_TOKENS = "auth:jwt-user:"
_LIVE = "auth:jwt-live"
_INVALIDATED = "auth:jwt-inv:"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _token_expiry_ms(token: str) -> Optional[int]:
    """The `exp` claim in milliseconds, read without verifying (the auth service already did)."""
    try:
        payload = token.split(".")[1]
        claims: Any = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return int(float(claims["exp"]) * 1000)
    except Exception:
        return None


class AuthUserCache:
    def __init__(
        self,
        redis_client: Any,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._redis = redis_client
        self._ttl_ms = int(ttl_seconds * 1000)
        self._max_entries = max_entries

    async def get(self, token: str) -> Optional[AuthUser]:
        try:
            raw = await self._redis.get(_ENTRY + _token_hash(token))
            if raw is None:
                return None
            return AuthUser.model_validate_json(raw)
        except Exception:
            logger.warning("Auth user cache read failed")
            return None

    async def put(self, token: str, user: AuthUser, *, started_at: float) -> None:
        """Store a successful check. `started_at` is `time.time()` from before the check was made."""
        try:
            now = _now_ms()
            expiry = _token_expiry_ms(token)
            if expiry is None:
                return
            ttl_ms = min(self._ttl_ms, expiry - now)
            if ttl_ms <= 0:
                return

            invalidated_at = await self._redis.get(_INVALIDATED + user.id)
            if invalidated_at is not None and int(invalidated_at) >= int(started_at * 1000):
                return

            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.zremrangebyscore(_LIVE, "-inf", now)
                pipe.zcard(_LIVE)
                _, live_entries = await pipe.execute()
            if live_entries >= self._max_entries:
                return

            digest = _token_hash(token)
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.set(_ENTRY + digest, user.model_dump_json(), px=ttl_ms)
                pipe.zadd(_LIVE, {digest: now + ttl_ms})
                pipe.pexpire(_LIVE, self._ttl_ms * 2)
                pipe.sadd(_USER_TOKENS + user.id, digest)
                pipe.pexpire(_USER_TOKENS + user.id, self._ttl_ms + 1000)
                await pipe.execute()
        except Exception:
            logger.warning("Auth user cache write failed")

    async def invalidate_user(self, user_id: str) -> None:
        """Forget every cached token of this user, in every worker process."""
        try:
            await self._redis.set(_INVALIDATED + user_id, _now_ms(), px=_INVALIDATION_MEMORY_MS)
            digests = await self._redis.smembers(_USER_TOKENS + user_id)
            async with self._redis.pipeline(transaction=True) as pipe:
                for digest in digests:
                    pipe.delete(_ENTRY + digest)
                    pipe.zrem(_LIVE, digest)
                pipe.delete(_USER_TOKENS + user_id)
                await pipe.execute()
        except Exception:
            logger.warning("Auth user cache invalidation failed")
