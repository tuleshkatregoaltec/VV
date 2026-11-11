"""Agent self-service WhatsApp connection (Embedded Signup) and admin overview.

Identities always come from the server session, never from request bodies.
"""

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.core.dependencies import AuthContext, require_active_subscription, require_admin
from app.postgres import get_db_session
from app.whatsapp import customer_connections as connections
from app.whatsapp.customer_models import (
    AdminConnectionList,
    AgentConnectionStatus,
    AutomationToggle,
    BlockRequest,
    BlockResult,
    ContactPage,
    SignupComplete,
    SignupConfigResponse,
)

router = APIRouter(prefix="/api/v1/whatsapp", tags=["WhatsApp connection"])
admin_router = APIRouter(
    prefix="/api/v1/admin/whatsapp", tags=["admin"], dependencies=[Depends(require_admin)]
)


def _identity(context):
    return {"user_id": str(context.user.id), "organization_id": str(context.organization.id)}


@router.get("/signup/config", response_model=SignupConfigResponse)
async def signup_config(context: AuthContext = Depends(require_active_subscription)):
    """Start: public FB.login values plus a state the completion must return."""
    values = connections.signup_settings(settings)
    identity = _identity(context)
    state = (
        connections.signup_state(identity["user_id"], identity["organization_id"], settings)
        if values["configured"]
        else None
    )
    return SignupConfigResponse(**values, state=state)


@router.post("/signup/complete", response_model=AgentConnectionStatus)
async def signup_complete(
    request: SignupComplete,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await connections.connect(db, **_identity(context), request=request, config=settings)


@router.get("/connection", response_model=AgentConnectionStatus)
async def connection_status(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await connections.agent_status(db, **_identity(context), config=settings)


@router.patch("/connection/automation", response_model=AgentConnectionStatus)
async def toggle_automation(
    request: AutomationToggle,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await connections.set_automation(
        db, **_identity(context), enabled=request.enabled, config=settings
    )


@router.post("/connection/disconnect", response_model=AgentConnectionStatus)
async def disconnect(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await connections.disconnect_agent(db, **_identity(context), config=settings)


@router.get("/connection/contacts", response_model=ContactPage)
async def list_contacts(
    search: str | None = Query(default=None, max_length=100),
    blocked: bool | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await connections.list_agent_contacts(
        db,
        **_identity(context),
        search=search,
        blocked=blocked,
        limit=limit,
        offset=offset,
    )


@router.put("/connection/contacts/blocked", response_model=BlockResult)
async def set_blocked(
    request: BlockRequest,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await connections.block_contacts(db, **_identity(context), request=request)


@router.post("/connection/contacts/sync", response_model=AgentConnectionStatus)
async def request_contacts_sync(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await connections.retry_contacts_sync(db, **_identity(context), config=settings)


@admin_router.get("/connections", response_model=AdminConnectionList)
async def admin_connections(db: AsyncSession = Depends(get_db_session)):
    """How many agents are connected, and the state of each number."""
    return await connections.admin_connections(db, config=settings)
