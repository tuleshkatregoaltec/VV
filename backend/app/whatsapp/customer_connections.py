"""Per-agent WhatsApp connection lifecycle: Embedded Signup, status, disconnect, env pilot."""

import hashlib
import hmac
import logging
import secrets
import time
from datetime import timedelta

from fastapi import HTTPException

from app.whatsapp import customer_graph as graph
from app.whatsapp import customer_repository as repository
from app.whatsapp import token_crypto
from app.whatsapp.customer_models import WhatsAppConnection
from app.whatsapp.models import utcnow

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 30 * 60
ONBOARDING = {
    "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING": "coexistence",
    "FINISH": "cloud_api",
}
# FB.login `extras` for coexistence (agent keeps the WhatsApp Business app).
SIGNUP_EXTRAS = {
    "setup": {},
    "featureType": "whatsapp_business_app_onboarding",
    "sessionInfoVersion": "3",
}


def signup_settings(config):
    missing = [
        name
        for name in (
            "WHATSAPP_APP_ID",
            "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID",
            "WHATSAPP_APP_SECRET",
            "WHATSAPP_GRAPH_API_VERSION",
        )
        if not getattr(config, name)
    ]
    if not token_crypto.available(config):
        missing.append("WHATSAPP_TOKEN_ENCRYPTION_KEY")
    if not config.WHATSAPP_CUSTOMER_AUTOMATION_ENABLED:
        missing.append("WHATSAPP_CUSTOMER_AUTOMATION_ENABLED")
    return {
        "configured": not missing,
        "missing": missing,
        "app_id": config.WHATSAPP_APP_ID,
        "config_id": config.WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID,
        "graph_api_version": config.WHATSAPP_GRAPH_API_VERSION,
        "extras": dict(SIGNUP_EXTRAS),
    }


def _state_signature(user_id, organization_id, expires, config):
    message = f"whatsapp-signup|{user_id}|{organization_id}|{expires}".encode()
    return hmac.new(config.SESSION_SECRET.encode(), message, hashlib.sha256).hexdigest()


def signup_state(user_id, organization_id, config):
    """Binds a signup completion to the agent who started it (30 minutes)."""
    expires = int(time.time()) + STATE_TTL_SECONDS
    return f"{expires}.{_state_signature(user_id, organization_id, expires, config)}"


def valid_state(state, user_id, organization_id, config):
    expires, _, signature = state.partition(".")
    if not expires.isdigit() or int(expires) < time.time():
        return False
    expected = _state_signature(user_id, organization_id, int(expires), config)
    return hmac.compare_digest(expected.encode(), signature.encode())


def _health(raw):
    if not isinstance(raw, dict):
        return None
    errors = []
    for entity in raw.get("entities", []) if isinstance(raw.get("entities"), list) else []:
        for error in entity.get("errors", []) if isinstance(entity, dict) else []:
            if isinstance(error, dict):
                errors.append(
                    {
                        key: str(error[key])[:500]
                        for key in ("error_code", "error_description", "possible_solution")
                        if key in error
                    }
                )
    status = raw.get("can_send_message")
    return {"can_send_message": status if isinstance(status, str) else None, "errors": errors}


def _text(value, limit=200):
    return value[:limit] if isinstance(value, str) and value.strip() else None


async def complete_signup(db, *, user_id, organization_id, request, config):
    """Exchange the code, verify asset ownership, subscribe webhooks, store the token.

    Each Meta step fails closed before anything is persisted. The contacts sync is
    requested once, right after a coexistence connect (Meta allows it within 24h).
    """
    if not signup_settings(config)["configured"]:
        raise HTTPException(503, "WhatsApp Embedded Signup is not configured")
    if not valid_state(request.state, user_id, organization_id, config):
        raise HTTPException(400, "Signup session expired; start again")
    onboarding = ONBOARDING.get(request.event)
    if onboarding is None or not request.phone_number_id:
        raise HTTPException(422, "A WhatsApp phone number must be connected")
    existing = await repository.connection_by_phone(db, request.phone_number_id)
    if existing is not None and (existing.user_id, existing.organization_id) != (
        user_id,
        organization_id,
    ):
        await db.rollback()
        raise HTTPException(409, "This WhatsApp number is linked to another Vitevue account")
    others = [
        row
        for row in await repository.agent_connections(db, user_id, organization_id)
        if row.status == "connected" and row.phone_number_id != request.phone_number_id
    ]
    if others:
        await db.rollback()
        raise HTTPException(409, "Disconnect your current WhatsApp number first")
    # Release row locks while Meta is called; re-check under lock before writing.
    await db.rollback()
    try:
        token = await graph.exchange_code(request.code, config)
        numbers = await graph.phone_numbers(request.waba_id, token, config)
        number = next((n for n in numbers if n.get("id") == request.phone_number_id), None)
        if number is None:
            raise HTTPException(403, "That phone number is not in the WhatsApp account you shared")
        await graph.subscribe_app(request.waba_id, token, config)
        if onboarding == "cloud_api":
            await graph.register_number(
                request.phone_number_id, token, f"{secrets.randbelow(10**6):06d}", config
            )
    except graph.GraphError as exc:
        logger.warning("WhatsApp signup Graph step failed (%s)", exc.error_code)
        raise HTTPException(502, f"Meta rejected the connection ({exc.error_code})") from None

    row = await repository.connection_by_phone(db, request.phone_number_id)
    if row is not None and (row.user_id, row.organization_id) != (user_id, organization_id):
        await db.rollback()
        raise HTTPException(409, "This WhatsApp number is linked to another Vitevue account")
    now = utcnow()
    if row is None:
        row = WhatsAppConnection(
            user_id=user_id,
            organization_id=organization_id,
            phone_number_id=request.phone_number_id,
            account_id=request.waba_id,
            display_name="WhatsApp",
            enabled=False,
        )
        db.add(row)
    row.account_id = request.waba_id
    row.business_id = request.business_id
    row.display_phone_number = _text(number.get("display_phone_number"), 32)
    row.display_name = (
        _text(number.get("verified_name")) or row.display_phone_number or row.display_name
    )
    row.quality_rating = _text(number.get("quality_rating"), 32)
    row.access_token_encrypted = token_crypto.encrypt_token(token, config)
    row.onboarding_type = onboarding
    if row.status != "connected" or row.connected_at is None:
        row.connected_at = now  # starts Meta's 24-hour contacts sync window
        # A (re)connect starts from an empty address book: request a fresh contacts sync
        # and keep automation off until the agent re-reviews blocks and switches it on.
        row.enabled = False
        row.contacts_sync_requested_at = None
        row.contacts_synced_at = None
    row.status = "connected"
    row.disconnected_at = None
    row.last_account_event = None
    row.updated_at = now
    await db.flush()
    await db.commit()

    if onboarding == "coexistence" and row.contacts_sync_requested_at is None:
        await request_contacts_sync(db, row, token, config)
    try:
        row.health = _health(await graph.phone_health(request.phone_number_id, token, config))
        await db.commit()
    except graph.GraphError as exc:
        logger.info("WhatsApp health check unavailable (%s)", exc.error_code)
    return row


async def request_contacts_sync(db, row, token, config):
    try:
        await graph.request_contacts_sync(row.phone_number_id, token, config)
    except graph.GraphError as exc:
        # Left unset so the agent can retry within Meta's 24-hour window.
        logger.warning("WhatsApp contacts sync request failed (%s)", exc.error_code)
        return False
    row.contacts_sync_requested_at = utcnow()
    row.updated_at = utcnow()
    await db.commit()
    return True


async def disconnect(db, connection, *, reason):
    """Revoke locally: stop automation, cancel unsent work, delete token and contacts.

    Caller holds the connection lock. Review history stays with its owner.
    """
    from app.whatsapp.customer_service import invalidate_connection

    await invalidate_connection(db, connection.id, "connection_disconnected")
    await repository.delete_contacts(db, connection.id)
    now = utcnow()
    connection.enabled = False
    connection.status = "disconnected"
    connection.access_token_encrypted = None
    # Contacts were deleted above; a reconnect must sync them again.
    connection.contacts_sync_requested_at = None
    connection.contacts_synced_at = None
    connection.disconnected_at = now
    connection.last_account_event = reason
    connection.updated_at = now


async def bootstrap_env_connection(db, config):
    """Move the env-configured pilot number (Kian's) into per-agent storage.

    Idempotent. Encrypts WHATSAPP_CUSTOMER_ACCESS_TOKEN into the matching row, creating
    the row (automation off) if absent. Respects a deliberate disconnect and never
    re-assigns a number owned by someone else.
    """
    phone, account, token = (
        config.WHATSAPP_CUSTOMER_PHONE_NUMBER_ID,
        config.WHATSAPP_CUSTOMER_ACCOUNT_ID,
        config.WHATSAPP_CUSTOMER_ACCESS_TOKEN,
    )
    owner = (config.WHATSAPP_PILOT_USER_ID, config.WHATSAPP_PILOT_ORGANIZATION_ID)
    if not (config.WHATSAPP_CUSTOMER_AUTOMATION_ENABLED and phone and account and token):
        return None
    if not all(owner):
        return None
    if not token_crypto.available(config):
        logger.error("WhatsApp env pilot not migrated: WHATSAPP_TOKEN_ENCRYPTION_KEY missing")
        return None
    row = await repository.connection_by_phone(db, phone)
    if row is None:
        row = WhatsAppConnection(
            user_id=owner[0],
            organization_id=owner[1],
            phone_number_id=phone,
            account_id=account,
            display_name="WhatsApp",
            onboarding_type="env",
            connected_at=utcnow(),
        )
        db.add(row)
    elif (row.user_id, row.organization_id, row.account_id) != (*owner, account):
        logger.warning("WhatsApp env pilot not migrated: number has a different owner")
        await db.rollback()
        return None
    elif row.status != "connected":
        await db.rollback()
        return None
    current = None
    if row.access_token_encrypted:
        try:
            current = token_crypto.decrypt_token(row.access_token_encrypted, config)
        except token_crypto.TokenEncryptionUnavailable:
            current = None
    if current != token:
        row.access_token_encrypted = token_crypto.encrypt_token(token, config)
        row.onboarding_type = row.onboarding_type or "env"
        row.updated_at = utcnow()
    await db.commit()
    return row


# ─── Agent self-service ───────────────────────────────────────────────────────


async def _agent_connection(db, user_id, organization_id):
    rows = await repository.agent_connections(db, user_id, organization_id)
    return rows[0] if rows else None


async def _require_connected(db, user_id, organization_id):
    row = await _agent_connection(db, user_id, organization_id)
    if row is None or row.status != "connected":
        await db.rollback()
        raise HTTPException(404, "No connected WhatsApp number")
    return row


async def agent_status(db, *, user_id, organization_id, config):
    from app.whatsapp.customer_models import AgentConnectionStatus, ContactCounts

    configured = signup_settings(config)["configured"]
    row = await _agent_connection(db, user_id, organization_id)
    if row is None:
        await db.commit()
        return AgentConnectionStatus(
            state="not_connected" if configured else "not_configured",
            signup_configured=configured,
        )
    total, blocked = await repository.contact_counts(db, row.id)
    await db.commit()
    health = row.health or {}
    return AgentConnectionStatus(
        state="connected" if row.status == "connected" else "disconnected",
        signup_configured=configured,
        connection_id=row.id,
        phone_number_id=row.phone_number_id,
        waba_id=row.account_id,
        business_id=row.business_id,
        display_phone_number=row.display_phone_number,
        display_name=row.display_name,
        onboarding_type=row.onboarding_type,
        automation_enabled=row.enabled and row.status == "connected",
        connected_at=row.connected_at,
        disconnected_at=row.disconnected_at,
        last_account_event=row.last_account_event,
        quality_rating=row.quality_rating,
        can_send_message=health.get("can_send_message"),
        health_errors=health.get("errors") or [],
        contacts=ContactCounts(
            total=total,
            blocked=blocked,
            sync_requested_at=row.contacts_sync_requested_at,
            synced_at=row.contacts_synced_at,
        ),
    )


async def connect(db, *, user_id, organization_id, request, config):
    await complete_signup(
        db, user_id=user_id, organization_id=organization_id, request=request, config=config
    )
    return await agent_status(db, user_id=user_id, organization_id=organization_id, config=config)


async def set_automation(db, *, user_id, organization_id, enabled, config):
    from app.whatsapp.customer_service import invalidate_connection

    row = await _require_connected(db, user_id, organization_id)
    if enabled:
        try:
            token_crypto.decrypt_token(row.access_token_encrypted or "", config)
        except token_crypto.TokenEncryptionUnavailable:
            await db.rollback()
            raise HTTPException(409, "Reconnect WhatsApp before turning automation on") from None
    elif row.enabled:
        await invalidate_connection(db, row.id, "connection_disabled")
    row.enabled = enabled
    row.updated_at = utcnow()
    await db.commit()
    return await agent_status(db, user_id=user_id, organization_id=organization_id, config=config)


async def disconnect_agent(db, *, user_id, organization_id, config):
    row = await _require_connected(db, user_id, organization_id)
    waba_id, stored = row.account_id, row.access_token_encrypted
    await disconnect(db, row, reason="AGENT_DISCONNECTED")
    await db.commit()
    # Best effort after the local revoke: stop Meta delivering this WABA's webhooks.
    if stored and row.onboarding_type != "env":
        try:
            token = token_crypto.decrypt_token(stored, config)
            await graph.unsubscribe_app(waba_id, token, config)
        except (graph.GraphError, token_crypto.TokenEncryptionUnavailable) as exc:
            logger.warning(
                "WhatsApp webhook unsubscribe failed (%s)",
                getattr(exc, "error_code", type(exc).__name__),
            )
    return await agent_status(db, user_id=user_id, organization_id=organization_id, config=config)


async def retry_contacts_sync(db, *, user_id, organization_id, config):
    row = await _require_connected(db, user_id, organization_id)
    if row.onboarding_type != "coexistence":
        await db.rollback()
        raise HTTPException(
            409, "Contacts sync is only available for WhatsApp Business app numbers"
        )
    if row.contacts_sync_requested_at is not None:
        await db.rollback()
        raise HTTPException(409, "Contacts sync was already requested")
    if row.connected_at is None or utcnow() - row.connected_at > timedelta(hours=24):
        await db.rollback()
        raise HTTPException(409, "Meta's 24-hour contacts sync window has passed; reconnect")
    try:
        token = token_crypto.decrypt_token(row.access_token_encrypted or "", config)
    except token_crypto.TokenEncryptionUnavailable:
        await db.rollback()
        raise HTTPException(409, "Reconnect WhatsApp to sync contacts") from None
    await db.commit()
    if not await request_contacts_sync(db, row, token, config):
        raise HTTPException(502, "Meta did not accept the contacts sync request")
    return await agent_status(db, user_id=user_id, organization_id=organization_id, config=config)


async def list_agent_contacts(db, *, user_id, organization_id, search, blocked, limit, offset):
    from app.whatsapp.customer_contacts import list_contacts
    from app.whatsapp.customer_models import ContactPage, ContactResponse

    row = await _require_connected(db, user_id, organization_id)
    total, rows = await list_contacts(
        db, row, search=search, blocked=blocked, limit=limit, offset=offset
    )
    await db.commit()
    return ContactPage(
        items=[ContactResponse.model_validate(item) for item in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def block_contacts(db, *, user_id, organization_id, request):
    from app.whatsapp.customer_contacts import set_blocked
    from app.whatsapp.customer_models import BlockResult

    row = await _require_connected(db, user_id, organization_id)
    updated = await set_blocked(
        db,
        row,
        contact_ids=request.contact_ids,
        phone_numbers=request.phone_numbers,
        blocked=request.blocked,
    )
    await db.flush()
    _, blocked_total = await repository.contact_counts(db, row.id)
    await db.commit()
    return BlockResult(updated=updated, blocked_total=blocked_total)


# ─── Admin ────────────────────────────────────────────────────────────────────


async def admin_connections(db):
    from app.auth.service import get_user_by_id
    from app.whatsapp.customer_models import AdminConnectionList, AdminConnectionRow

    rows = await repository.admin_overview(db)
    emails = {}
    for user_id in {row["connection"].user_id for row in rows}:
        try:
            user = await get_user_by_id(user_id)
        except Exception as exc:  # The auth provider is optional for this overview.
            logger.info("Admin overview could not resolve a user (%s)", type(exc).__name__)
            user = None
        emails[user_id] = getattr(user, "email", None)
    items = []
    for row in rows:
        c = row["connection"]
        items.append(
            AdminConnectionRow(
                connection_id=c.id,
                user_id=c.user_id,
                user_email=emails.get(c.user_id),
                organization_id=c.organization_id,
                organization_name=row["organization_name"],
                phone_number_id=c.phone_number_id,
                display_phone_number=c.display_phone_number,
                display_name=c.display_name,
                status=c.status,
                onboarding_type=c.onboarding_type,
                automation_enabled=c.enabled and c.status == "connected",
                contacts_total=row["contacts_total"],
                contacts_blocked=row["contacts_blocked"],
                contacts_synced_at=c.contacts_synced_at,
                last_message_at=row["last_message_at"],
                connected_at=c.connected_at,
                disconnected_at=c.disconnected_at,
                can_send_message=(c.health or {}).get("can_send_message"),
            )
        )
    return AdminConnectionList(
        total=len(items),
        connected=sum(item.status == "connected" for item in items),
        automation_on=sum(item.automation_enabled for item in items),
        items=items,
    )


async def bootstrap_on_startup(config=None):
    """Process start-up hook (API and worker). Never blocks start-up on failure."""
    from contextlib import asynccontextmanager

    from app.config import settings
    from app.postgres import get_db_session

    config = config or settings
    if not (config.WHATSAPP_CUSTOMER_AUTOMATION_ENABLED and config.WHATSAPP_CUSTOMER_ACCESS_TOKEN):
        return
    try:
        async with asynccontextmanager(get_db_session)() as db:
            await bootstrap_env_connection(db, config)
    except Exception as exc:
        logger.error("WhatsApp env pilot migration failed (%s)", type(exc).__name__)
