"""Fail-closed admission and accounting for every external model request.

Redis is the authoritative reservation ledger, not an evictable response cache.
Deployment requires persistent Redis with noeviction and restricted key access.
Unknown provider usage remains charged at the reserved maximum, including crashes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal

import redis.asyncio as redis
from pydantic_core import to_jsonable_python

from app.config import settings

logger = logging.getLogger(__name__)
POLICY_VERSION = "ai-policy-v1"
LEDGER_PREFIX = "ai-policy:v1:"


class AIPolicyError(RuntimeError):
    """Safe public error: never includes prompts, credentials, or tenant IDs."""


@dataclass
class Execution:
    user_id: str
    organization_id: str
    execution_id: str
    daily_token_limit: int
    authorize: Callable[[], Awaitable[None]] | None = None
    calls: int = 0
    prompt_version: str | None = None
    data_release: str | None = None


_scope: ContextVar[Execution | None] = ContextVar("ai_execution", default=None)


def client():
    return redis.from_url(
        settings.REDIS_URL,
        password=settings.REDIS_PASSWORD or None,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


def _identity(value):
    return hashlib.sha256(value.encode()).hexdigest()


def microdollars(value):
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise AIPolicyError("AI pricing and budget configuration is invalid")
    return int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def cost(input_tokens, output_tokens):
    if settings.AI_INPUT_USD_PER_MILLION is None or settings.AI_OUTPUT_USD_PER_MILLION is None:
        raise AIPolicyError("AI pricing must be configured before model use")
    return int(
        (
            input_tokens * settings.AI_INPUT_USD_PER_MILLION
            + output_tokens * settings.AI_OUTPUT_USD_PER_MILLION
        ).to_integral_value(rounding=ROUND_CEILING)
    )


def provider_privacy():
    policy = {
        "zdr": True,
        "data_collection": "deny",
        "allow_fallbacks": False,
        "require_parameters": True,
    }
    if settings.AI_PROVIDER_ALLOWLIST:
        policy["only"] = list(settings.AI_PROVIDER_ALLOWLIST)
    return policy


def safe_model_settings(model_settings):
    supplied = dict(model_settings or {})
    # Extra bodies, presets and model fallbacks must not override the privacy policy.
    for key in ("extra_body", "openrouter_models", "openrouter_preset", "openrouter_transforms"):
        if supplied.get(key):
            raise AIPolicyError("Unapproved provider override")
    supplied["max_tokens"] = min(
        supplied.get("max_tokens") or settings.AI_MAX_OUTPUT_TOKENS,
        settings.AI_MAX_OUTPUT_TOKENS,
    )
    supplied["openrouter_provider"] = provider_privacy()
    return supplied


@asynccontextmanager
async def ai_execution(
    *,
    user_id,
    organization_id,
    execution_id,
    daily_token_limit,
    authorize=None,
    prompt_version=None,
    data_release=None,
):
    if not user_id or not organization_id or not execution_id or daily_token_limit <= 0:
        raise AIPolicyError("Authenticated AI execution context is required")
    token = _scope.set(
        Execution(
            str(user_id),
            str(organization_id),
            str(execution_id),
            daily_token_limit,
            authorize,
            prompt_version=prompt_version,
            data_release=data_release,
        )
    )
    try:
        async with asyncio.timeout(settings.AI_EXECUTION_TIMEOUT_SECONDS):
            yield _scope.get()
    finally:
        _scope.reset(token)


# Single Redis transaction checks all limits before writing any reservation. Budget
# keys intentionally have no TTL: losing an unknown charge would permit overspend.
_RESERVE = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 'duplicate' end
for i=2,6 do
 if tonumber(redis.call('GET', KEYS[i]) or '0') + tonumber(ARGV[i]) > tonumber(ARGV[i+5]) then
  return 'budget'
 end
end
for i=7,8 do
 redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', ARGV[12])
 if redis.call('ZCARD', KEYS[i]) >= tonumber(ARGV[i+6]) then return 'concurrency' end
end
for i=9,10 do
 if tonumber(redis.call('GET', KEYS[i]) or '0') >= tonumber(ARGV[15]) then return 'rate' end
end
for i=2,6 do redis.call('INCRBY', KEYS[i], ARGV[i]) end
for i=7,8 do redis.call('ZADD', KEYS[i], ARGV[16], ARGV[1]) end
for i=9,10 do redis.call('INCR', KEYS[i]); redis.call('EXPIRE', KEYS[i], 120) end
redis.call('HSET', KEYS[1], 'status', 'reserved', 'cost', ARGV[2], 'tokens', ARGV[6])
redis.call('SADD', KEYS[11], ARGV[17])
redis.call('HSET', KEYS[1], 'execution_id', ARGV[18], 'prompt_version', ARGV[19],
 'data_release', ARGV[20], 'provider', 'openrouter', 'endpoint', 'chat/completions')
return 'ok'
"""
_SETTLE = """
if redis.call('HGET', KEYS[1], 'status') ~= 'reserved' then return 0 end
local old_cost = tonumber(redis.call('HGET', KEYS[1], 'cost'))
local old_tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens'))
for i=2,5 do redis.call('INCRBY', KEYS[i], tonumber(ARGV[2])-old_cost) end
redis.call('INCRBY', KEYS[6], tonumber(ARGV[3])-old_tokens)
for i=7,8 do redis.call('ZREM', KEYS[i], ARGV[1]) end
redis.call('HSET', KEYS[1], 'status', ARGV[4], 'cost', ARGV[2], 'tokens', ARGV[3],
 'input_tokens', ARGV[5], 'output_tokens', ARGV[6], 'model', ARGV[7], 'policy', ARGV[8])
return 1
"""


@dataclass
class Reservation:
    redis: object
    keys: list[str]
    identifier: str
    model: str
    reserved_cost: int
    reserved_tokens: int
    usage: tuple[int, int] | None = None

    def reconcile(self, input_tokens, output_tokens):
        if (
            isinstance(input_tokens, int)
            and isinstance(output_tokens, int)
            and input_tokens >= 0
            and output_tokens >= 0
            and input_tokens + output_tokens > 0
        ):
            self.usage = (input_tokens, output_tokens)

    async def finish(self):
        input_tokens, output_tokens = self.usage or (0, 0)
        actual_cost = cost(input_tokens, output_tokens) if self.usage else self.reserved_cost
        actual_tokens = input_tokens + output_tokens if self.usage else self.reserved_tokens
        await self.redis.eval(
            _SETTLE,
            len(self.keys),
            *self.keys,
            self.identifier,
            actual_cost,
            actual_tokens,
            "settled" if self.usage else "unknown",
            input_tokens,
            output_tokens,
            self.model,
            POLICY_VERSION,
        )


@asynccontextmanager
async def provider_reservation(model: str, payload, *, output_tokens: int):
    scope = _scope.get()
    if scope is None:
        raise AIPolicyError("Authenticated AI execution context is required")
    if scope.authorize:
        await scope.authorize()
    if model != settings.DEFAULT_CHAT_MODEL:
        raise AIPolicyError("Unapproved AI model")
    if settings.AI_PRICING_MODEL != model:
        raise AIPolicyError("AI pricing must identify the configured model")
    if settings.ENVIRONMENT != "local" and not settings.AI_PROVIDER_ALLOWLIST:
        raise AIPolicyError("Approved AI providers must be configured")
    scope.calls += 1
    if scope.calls > settings.AI_MAX_CALLS_PER_EXECUTION:
        raise AIPolicyError("AI model-call limit reached")
    # UTF-8 bytes are a conservative text-token upper bound, including tool schema.
    # Multimodal payloads are not enabled on these product paths.
    payload_bytes = len(json.dumps(to_jsonable_python(payload), ensure_ascii=False).encode())
    input_tokens = payload_bytes + 4096  # framing/system/schema overhead margin
    if input_tokens > settings.AI_MAX_INPUT_TOKENS or output_tokens > settings.AI_MAX_OUTPUT_TOKENS:
        raise AIPolicyError("AI context or output limit exceeded")
    budgets = [
        settings.AI_USER_DAILY_USD,
        settings.AI_USER_MONTHLY_USD,
        settings.AI_ORG_DAILY_USD,
        settings.AI_ORG_MONTHLY_USD,
    ]
    if any(value is None for value in budgets):
        raise AIPolicyError("AI spending budgets must be configured before model use")
    reserved_cost = cost(input_tokens, output_tokens)
    reserved_tokens = input_tokens + output_tokens
    now = datetime.now(timezone.utc)
    user, org = _identity(scope.user_id), _identity(scope.organization_id)
    identifier = _identity(
        f"{scope.user_id}:{scope.organization_id}:{scope.execution_id}:{scope.calls}"
    )
    prefix = LEDGER_PREFIX
    keys = [
        prefix + "request:" + identifier,
        f"{prefix}user:{user}:day:{now:%Y-%m-%d}",
        f"{prefix}user:{user}:month:{now:%Y-%m}",
        f"{prefix}org:{org}:day:{now:%Y-%m-%d}",
        f"{prefix}org:{org}:month:{now:%Y-%m}",
        f"{prefix}tokens:{user}:{now:%Y-%m-%d}",
        f"{prefix}active:user:{user}",
        f"{prefix}active:org:{org}",
        f"{prefix}rate:user:{user}:{int(time.time() // 60)}",
        f"{prefix}rate:org:{org}:{int(time.time() // 60)}",
        f"{prefix}users:{now:%Y-%m-%d}",
    ]
    connection = client()
    reservation = Reservation(connection, keys, identifier, model, reserved_cost, reserved_tokens)
    try:
        try:
            admitted = await connection.eval(
                _RESERVE,
                len(keys),
                *keys,
                identifier,
                *([reserved_cost] * 4),
                reserved_tokens,
                *(microdollars(value) for value in budgets),
                scope.daily_token_limit,
                time.time(),
                settings.AI_USER_CONCURRENCY,
                settings.AI_ORG_CONCURRENCY,
                settings.AI_REQUESTS_PER_MINUTE,
                time.time() + settings.AI_EXECUTION_TIMEOUT_SECONDS + 30,
                scope.user_id,
                scope.execution_id,
                scope.prompt_version or "unversioned",
                scope.data_release or "unverified",
            )
        except Exception:
            raise AIPolicyError("AI accounting is unavailable") from None
        if admitted != "ok":
            raise AIPolicyError(f"AI {admitted} limit reached")
        try:
            yield reservation
        finally:
            # Shield reconciliation from client cancellation. A process crash leaves
            # the reservation charged and the concurrency lease eventually expires.
            task = asyncio.create_task(reservation.finish())
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
            except Exception:
                logger.error("AI accounting reconciliation failed; reservation retained")
                raise AIPolicyError("AI accounting reconciliation is pending") from None
    finally:
        await connection.aclose()


async def direct_provider_request(client, url, **kwargs):
    """The CRM direct HTTP path uses the same admission, privacy and ledger."""
    from app.core.observability import provider_request

    if url != "https://openrouter.ai/api/v1/chat/completions":
        raise AIPolicyError("Unapproved AI endpoint")
    body = dict(kwargs["json"])
    body["provider"] = provider_privacy()
    output_tokens = min(
        body.get("max_tokens", settings.AI_MAX_OUTPUT_TOKENS), settings.AI_MAX_OUTPUT_TOKENS
    )
    body["max_tokens"] = output_tokens
    kwargs["json"] = body
    async with provider_reservation(body["model"], body, output_tokens=output_tokens) as usage:
        response = await provider_request(client, url, **kwargs)
        response.raise_for_status()
        reported = response.json().get("usage", {})
        usage.reconcile(reported.get("prompt_tokens"), reported.get("completion_tokens"))
        return response


async def reserved_daily_tokens(user_id: str, day):
    """Read authoritative tokens, including conservatively charged unknown usage."""
    connection = client()
    try:
        return int(
            await connection.get(f"{LEDGER_PREFIX}tokens:{_identity(user_id)}:{day:%Y-%m-%d}") or 0
        )
    except Exception:
        raise AIPolicyError("AI accounting is unavailable") from None
    finally:
        await connection.aclose()


async def reserved_token_records(day, user_ids=None):
    """Batched private usage reads for the existing authorized admin service."""
    connection = client()
    try:
        identities = (
            list(user_ids)
            if user_ids is not None
            else sorted(await connection.smembers(f"{LEDGER_PREFIX}users:{day:%Y-%m-%d}"))
        )
        if not identities:
            return {}
        values = await connection.mget(
            [f"{LEDGER_PREFIX}tokens:{_identity(user_id)}:{day:%Y-%m-%d}" for user_id in identities]
        )
        return {user_id: int(value or 0) for user_id, value in zip(identities, values, strict=True)}
    except Exception:
        raise AIPolicyError("AI accounting is unavailable") from None
    finally:
        await connection.aclose()
