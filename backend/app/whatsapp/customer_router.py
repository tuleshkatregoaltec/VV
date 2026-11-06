"""Subscription-gated review inbox; identities always come from the server session."""

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.dependencies import AuthContext, require_active_subscription
from app.postgres import get_db_session
from app.whatsapp import customer_service as service
from app.whatsapp.customer_models import (
    ConnectionCreate,
    ConnectionResponse,
    ConnectionUpdate,
    CustomerMessageResponse,
    KnowledgeUpdate,
    PublishedListingCreate,
    PublishedListingResponse,
    PublishedListingUpdate,
    ReplyEdit,
    RevisionDecision,
    ThreadResponse,
    VoiceUpdate,
)

router = APIRouter(prefix="/api/v1/whatsapp", tags=["WhatsApp review"])


def _identity(context):
    return {"user_id": str(context.user.id), "organization_id": str(context.organization.id)}


@router.get("/connections", response_model=list[ConnectionResponse])
async def list_connections(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.list_connections(db, **_identity(context))


@router.post("/connections", response_model=ConnectionResponse, status_code=201)
async def create_connection(
    request: ConnectionCreate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.create_connection(db, **_identity(context), request=request)


@router.get("/connections/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: str,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.get_connection(db, **_identity(context), connection_id=connection_id)


@router.patch("/connections/{connection_id}", response_model=ConnectionResponse)
async def update_connection(
    connection_id: str,
    request: ConnectionUpdate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.update_connection(
        db, **_identity(context), connection_id=connection_id, request=request
    )


@router.put("/connections/{connection_id}/knowledge", response_model=ConnectionResponse)
async def update_knowledge(
    connection_id: str,
    request: KnowledgeUpdate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.update_knowledge(
        db, **_identity(context), connection_id=connection_id, request=request
    )


@router.put("/connections/{connection_id}/voice", response_model=ConnectionResponse)
async def update_voice(
    connection_id: str,
    request: VoiceUpdate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.update_voice(
        db, **_identity(context), connection_id=connection_id, request=request
    )


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: str,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    await service.delete_connection(db, **_identity(context), connection_id=connection_id)
    return Response(status_code=204)


@router.get("/connections/{connection_id}/threads", response_model=list[ThreadResponse])
async def list_threads(
    connection_id: str,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.list_threads(
        db, **_identity(context), connection_id=connection_id, limit=limit, offset=offset
    )


@router.post("/threads/{thread_id}/takeover", response_model=ThreadResponse)
async def takeover(
    thread_id: str,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.set_takeover(db, **_identity(context), thread_id=thread_id, paused=True)


@router.post("/threads/{thread_id}/resume", response_model=ThreadResponse)
async def resume(
    thread_id: str,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.set_takeover(db, **_identity(context), thread_id=thread_id, paused=False)


@router.get("/threads/{thread_id}/messages", response_model=list[CustomerMessageResponse])
async def list_messages(
    thread_id: str,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.list_messages(
        db, **_identity(context), thread_id=thread_id, limit=limit, offset=offset
    )


@router.get("/notifications", response_model=list[CustomerMessageResponse])
async def notifications(
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.list_notifications(db, **_identity(context), limit=limit, offset=offset)


@router.post("/messages/{message_id:path}/approve", response_model=CustomerMessageResponse)
async def approve(
    message_id: str,
    request: RevisionDecision,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.decide(
        db, **_identity(context), message_id=message_id, request=request, action="approve"
    )


@router.post("/messages/{message_id:path}/cancel", response_model=CustomerMessageResponse)
async def cancel(
    message_id: str,
    request: RevisionDecision,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.decide(
        db, **_identity(context), message_id=message_id, request=request, action="cancel"
    )


@router.patch("/messages/{message_id:path}", response_model=CustomerMessageResponse)
async def edit(
    message_id: str,
    request: ReplyEdit,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.decide(
        db, **_identity(context), message_id=message_id, request=request, action="edit"
    )


@router.post("/notifications/{message_id:path}/seen", response_model=CustomerMessageResponse)
async def seen(
    message_id: str,
    request: RevisionDecision,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.mark_seen(db, **_identity(context), message_id=message_id, request=request)


@router.get("/connections/{connection_id}/listings", response_model=list[PublishedListingResponse])
async def list_published_listings(
    connection_id: str,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.list_published_listings(
        db, **_identity(context), connection_id=connection_id, limit=limit, offset=offset
    )


@router.post(
    "/connections/{connection_id}/listings",
    response_model=PublishedListingResponse,
    status_code=201,
)
async def publish_listing(
    connection_id: str,
    request: PublishedListingCreate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.publish_listing(
        db, **_identity(context), connection_id=connection_id, request=request
    )


@router.put(
    "/connections/{connection_id}/listings/{listing_id}", response_model=PublishedListingResponse
)
async def renew_listing(
    connection_id: str,
    listing_id: str,
    request: PublishedListingUpdate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.publish_listing(
        db,
        **_identity(context),
        connection_id=connection_id,
        listing_id=listing_id,
        request=request,
    )


@router.post(
    "/connections/{connection_id}/listings/{listing_id}/revoke",
    response_model=PublishedListingResponse,
)
async def revoke_listing(
    connection_id: str,
    listing_id: str,
    request: RevisionDecision,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await service.revoke_listing(
        db,
        **_identity(context),
        connection_id=connection_id,
        listing_id=listing_id,
        request=request,
    )
