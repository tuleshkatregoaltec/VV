import json
import secrets
from datetime import date, datetime, time, timedelta
from typing import Literal
from uuid import UUID, uuid4

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.dependencies import AuthContext, require_active_owner, require_active_subscription
from app.crm import (
    agent_analytics,
    agent_languages,
    assignment,
    calendar_service,
    email_store,
    oversight,
    owner_import_requests,
    routing,
)
from app.crm import collections as collection_service
from app.crm.analytics_models import AgentAnalyticsDetail, AnalyticsWindow, TeamAnalyticsResponse
from app.crm.calendar_models import (
    CalendarEventCreate,
    CalendarEventMove,
    CalendarEventResponse,
    CalendarViewingCreate,
    CrmCalendarConnection,
    GoogleCalendarComplete,
    GoogleCalendarConnectResponse,
    GoogleCalendarStatus,
)
from app.crm.collection_models import (
    CollectionCreate,
    CollectionDetailResponse,
    CollectionItemAdd,
    CollectionItemResponse,
    CollectionListResponse,
    CollectionResponse,
    CollectionUpdate,
    ShareLinkResponse,
)
from app.crm.company_listings import (
    clear_company_source,
    get_company_listing,
    list_company_listings,
    select_company_source,
)
from app.crm.document_models import (
    LISTING_KEY_PATTERN,
    DocType,
    DocumentDownloadResponse,
    GeneratedDocumentListResponse,
    GeneratedDocumentResponse,
    GenerateDocumentRequest,
    ListingDocumentInfoResponse,
    ListingDocumentInfoUpdate,
)
from app.crm.documents import (
    download_document,
    generate_document,
    get_document,
    get_document_info,
    list_documents,
    save_document_info,
)
from app.crm.email_models import (
    EmailInboundListResponse,
    EmailLeadListResponse,
    EmailSendBatchResponse,
    EmailSendCreate,
    EmailSendListResponse,
    EmailStatusResponse,
    EmailSyncResponse,
    EmailTemplateResponse,
    EmailTemplateWrite,
    EmailThreadItem,
)
from app.crm.email_pipeline import (
    create_template,
    delete_send,
    delete_template,
    email_status,
    lead_thread,
    list_email_leads,
    list_inbound,
    list_sends,
    list_templates,
    send_emails,
    sync_events,
    update_template,
)
from app.crm.execution import expensive_crm, light_crm
from app.crm.import_models import (
    CrmContactImportPreview,
    CrmContactImportRename,
    CrmContactImportResponse,
    CrmContactListDetail,
    CrmContactListSummary,
    CrmDroppedRowsResponse,
    CrmImportPropertiesResponse,
    CrmLeadImportedContact,
    CrmOwnerBulkUpdate,
    CrmOwnerHistoryResponse,
    CrmOwnerHistorySummary,
    CrmOwnerProfile,
    CrmOwnerRegistryResponse,
    CrmOwnerWorkspaceSummary,
    OwnerImportRequestResponse,
)
from app.crm.imports import (
    delete_contact_import,
    list_contact_imports,
    list_dropped_rows,
    list_import_properties,
    preview_contact_import,
    process_contact_import,
    rename_contact_import,
)
from app.crm.inbound import (
    add_inbound_activity,
    add_inbound_note,
    create_inbound_enquiry,
    get_inbound_enquiry,
    list_inbound_enquiries,
    update_inbound_enquiry,
)
from app.crm.inbound_imports import (
    delete_inbound_import,
    list_inbound_imports,
    preview_inbound_import,
    process_inbound_import,
)
from app.crm.inbound_models import (
    CrmInboundContact,
    CrmInboundEnquiry,
    InboundActivityCreate,
    InboundEnquiryCreate,
    InboundEnquiryListResponse,
    InboundEnquiryResponse,
    InboundEnquiryUpdate,
    InboundImportPreviewResponse,
    InboundImportResponse,
    InboundMatchesResponse,
    InboundMatchResponse,
    InboundMatchUpdate,
    InboundNoteCreate,
)
from app.crm.matching import (
    get_inbound_matches,
    refresh_inbound_matches,
    update_inbound_match_state,
)
from app.crm.models import (
    CrmAreaPreferencesResponse,
    CrmAreaPreferencesUpdate,
    CrmCompanyListingDetail,
    CrmCompanyListingSourceResponse,
    CrmCompanyListingSourceUpdate,
    CrmCompanyListingsResponse,
    CrmDashboardResponse,
    CrmLeadDetailResponse,
    CrmNoteCreate,
    CrmPropertyReportResponse,
    CrmRenewalArea,
    CrmRenewalLeadsResponse,
    CrmRenewalsResponse,
    CrmSavedLeadResponse,
    CrmWorkspacePage,
    CrmWorkspaceResponse,
    CrmWorkspaceUpdate,
)
from app.crm.opportunities import get_dashboard
from app.crm.owner_history import get_owner_history, get_owner_history_summary
from app.crm.owner_issue import OwnerIssueRequest, OwnerIssueResponse, issue_owner_leads
from app.crm.owners import (
    get_contact_list,
    get_owner_profile,
    get_owner_registry,
    list_contact_lists,
    list_lead_imported_contacts,
)
from app.crm.recently_sold import approve_recent_seller
from app.crm.renewal_issue import (
    RenewalIssueRequest,
    RenewalIssueResponse,
    issue_renewal_leads,
)
from app.crm.renewal_leads import (
    get_area_preferences,
    get_renewal_detail,
    list_owner_renewals,
    list_renewal_areas,
    list_renewal_leads,
    open_renewal_lead,
    until_disconnected,
    update_area_preferences,
)
from app.crm.reports import get_property_report
from app.crm.routing_models import (
    AgentLanguagesResponse,
    AgentLanguagesWrite,
    AssignmentEventResponse,
    AssignmentScopeResponse,
    ImportAssignmentPolicy,
    LeadAssignmentRequest,
    LeadAssignmentResponse,
    PoolReleaseRequest,
    RoutingRuleOrder,
    RoutingRuleResponse,
    RoutingRuleUpdate,
    RoutingRuleWrite,
    WorkloadResponse,
)
from app.crm.workspaces import (
    add_lead_note,
    bulk_update_owner_workspaces,
    delete_lead_note,
    delete_saved_lead,
    get_lead_workspace,
    list_lead_workspaces,
    list_owner_workspaces,
    list_saved_leads,
    save_lead,
    update_lead_workspace,
)
from app.postgres import get_db_session
from app.postgres.actor_context import apply_actor_context, transaction_actor


async def _crm_actor(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    with transaction_actor(
        actor_id=str(context.user.id),
        organization_id=str(context.organization.id),
        request_id=uuid4().hex,
    ):
        # Authorization can already have opened this same session's transaction.
        await apply_actor_context(db)
        yield


async def _release_idle_connection(db: AsyncSession) -> None:
    """End the read-only authentication transaction so a queued request holds no pool
    connection; the next query begins a new one with the actor context applied."""
    if db.in_transaction() and not (db.new or db.dirty or db.deleted):
        await db.commit()


async def _expensive_crm(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    async with expensive_crm(
        str(context.organization.id), before_wait=lambda: _release_idle_connection(db)
    ):
        yield


async def _light_crm(context: AuthContext = Depends(require_active_subscription)):
    async with light_crm(str(context.organization.id)):
        yield


# Every route names its lane. Warehouse pages, owner assessments, imports and reports queue in
# the expensive lane; reviewed Postgres reads and writes use the light lane, whose occasional
# heavy step (an uncached owner assessment) is admitted through execution.heavy_section.
EXPENSIVE_LANE = [Depends(_expensive_crm)]
LIGHT_LANE = [Depends(_light_crm)]

router = APIRouter(
    prefix="/api/v1/crm",
    tags=["crm"],
    dependencies=[Depends(_crm_actor)],
)


def _auth_ids(auth: AuthContext) -> tuple[str, str]:
    return str(auth.user.id), str(auth.organization.id)


def _collection_actor(auth: AuthContext) -> collection_service.CollectionActor:
    user_id, organization_id = _auth_ids(auth)
    name = f"{auth.user.first_name} {auth.user.last_name}".strip()
    return collection_service.CollectionActor(
        user_id=user_id,
        organization_id=organization_id,
        is_owner=auth.membership.role == "owner",
        name=name or auth.user.email,
        email=auth.user.email,
    )


# ── Calendar (Google) ──
# Events belong to the signed-in user. A lead linked to an event must be one this user may see
# (lead assignment), so an agent cannot attach or book against another agent's lead.


async def _visible_lead(db: AsyncSession, auth: AuthContext, lead_id: int) -> CrmInboundEnquiry:
    user_id, organization_id = _auth_ids(auth)
    scope = await assignment.load_scope(db, organization_id, user_id)
    return await assignment.load_visible(db, scope, lead_id)


async def _own_event(db: AsyncSession, auth: AuthContext, event_id: int):
    user_id, organization_id = _auth_ids(auth)
    event = await calendar_service.get_event(
        db, id=event_id, user_id=user_id, organization_id=organization_id
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Calendar event not found")
    return event


@router.get("/calendar/google", response_model=GoogleCalendarStatus, dependencies=LIGHT_LANE)
async def crm_google_calendar_status(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    return await calendar_service.connection_status(
        db, user_id=user_id, organization_id=organization_id
    )


@router.post(
    "/calendar/google/connect",
    response_model=GoogleCalendarConnectResponse,
    dependencies=LIGHT_LANE,
)
async def crm_google_calendar_connect(context: AuthContext = Depends(require_active_subscription)):
    """Start Google sign-in. The link's state is single-use and bound to this user."""
    user_id, organization_id = _auth_ids(context)
    try:
        url = await calendar_service.authorization_url(user_id, organization_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"authorization_url": url}


@router.post(
    "/calendar/google/complete", response_model=GoogleCalendarStatus, dependencies=EXPENSIVE_LANE
)
async def crm_google_calendar_complete(
    payload: GoogleCalendarComplete,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Finish Google sign-in: only the signed-in user who started it can complete it."""
    user_id, organization_id = _auth_ids(context)
    try:
        await calendar_service.finish_connection(
            db,
            code=payload.code,
            state=payload.state,
            user_id=user_id,
            organization_id=organization_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail="Google sign-in failed; try again") from exc
    return await calendar_service.connection_status(
        db, user_id=user_id, organization_id=organization_id
    )


@router.delete("/calendar/google", status_code=204, dependencies=EXPENSIVE_LANE)
async def crm_google_calendar_disconnect(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    try:
        await calendar_service.disconnect(db, user_id=user_id, organization_id=organization_id)
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail="Could not disconnect Google Calendar") from exc
    return Response(status_code=204)


@router.get(
    "/calendar/events", response_model=list[CalendarEventResponse], dependencies=EXPENSIVE_LANE
)
async def crm_calendar_events(
    start: date = Query(),
    end: date = Query(),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    if end < start or (end - start).days > 370:
        raise HTTPException(status_code=422, detail="Calendar range must be within 371 days")
    user_id, organization_id = _auth_ids(context)
    try:
        return await calendar_service.list_events(
            db, user_id=user_id, organization_id=organization_id, start=start, end=end
        )
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail="Google Calendar sync failed") from exc


@router.get(
    "/calendar/events/{event_id}", response_model=CalendarEventResponse, dependencies=LIGHT_LANE
)
async def crm_calendar_event(
    event_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return calendar_service.serialize_event(await _own_event(db, context, event_id))


@router.post(
    "/calendar/events",
    response_model=CalendarEventResponse,
    status_code=201,
    dependencies=EXPENSIVE_LANE,
)
async def crm_create_calendar_event(
    payload: CalendarEventCreate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    if payload.lead_id is not None:
        await _visible_lead(db, context, payload.lead_id)
    return await calendar_service.create_event(
        db,
        user_id=user_id,
        organization_id=organization_id,
        title=payload.title.strip(),
        event_date=payload.date,
        event_time=payload.time,
        kind=payload.kind,
        detail=payload.detail.strip(),
        lead_id=payload.lead_id,
        listing_id=payload.listing_id,
        end_date=payload.end_date or payload.date,
        end_time=payload.end_time,
        all_day=payload.all_day,
        repeat=payload.repeat,
        meet=payload.meet,
        location=payload.location.strip(),
        reminders=payload.reminders,
        reminders_use_default=payload.reminders_use_default,
        guests=payload.guests,
        guests_can_modify=payload.guests_can_modify,
        guests_can_invite_others=payload.guests_can_invite_others,
        guests_can_see_other_guests=payload.guests_can_see_other_guests,
        show_as=payload.show_as,
        visibility=payload.visibility,
    )


@router.post(
    "/calendar/viewings/{lead_id}",
    response_model=CalendarEventResponse,
    status_code=201,
    dependencies=EXPENSIVE_LANE,
)
async def crm_book_calendar_viewing(
    payload: CalendarViewingCreate,
    lead_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    lead = await _visible_lead(db, context, lead_id)
    contact = await db.get(CrmInboundContact, lead.contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Lead contact not found")
    details = [payload.note.strip()]
    if payload.listing_id:
        details.append(f"Listing reference: {payload.listing_id}")
    return await calendar_service.create_event(
        db,
        user_id=user_id,
        organization_id=organization_id,
        title=f"Viewing · {contact.full_name}",
        event_date=payload.date,
        event_time=payload.time,
        kind="viewing",
        detail="\n".join(value for value in details if value),
        lead_id=lead_id,
        listing_id=payload.listing_id,
    )


@router.patch(
    "/calendar/events/{event_id}", response_model=CalendarEventResponse, dependencies=EXPENSIVE_LANE
)
async def crm_move_calendar_event(
    event_id: int,
    payload: CalendarEventMove,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    event = await _own_event(db, context, event_id)
    original_date = event.event_date
    original_time = event.event_time
    duration_days = (event.event_end_date or original_date) - original_date
    if (payload.date, payload.time) != (original_date, event.event_time):
        # A new list, so SQLAlchemy sees the JSON change.
        event.rescheduled_from = [
            *event.rescheduled_from,
            {"date": original_date.isoformat(), "time": event.event_time},
        ]
    event.event_date = payload.date
    event.event_time = payload.time
    if payload.time is None:
        event.event_end_date = payload.date + duration_days
        event.event_end_time = None
        event.all_day = True
    else:
        original_start = datetime.combine(
            original_date, time.fromisoformat(original_time or "10:00")
        )
        original_end = datetime.combine(
            event.event_end_date or original_date,
            time.fromisoformat(event.event_end_time or "11:00"),
        )
        new_start = datetime.combine(payload.date, time.fromisoformat(payload.time))
        duration = original_end - original_start
        new_end = new_start + (duration if duration > timedelta(0) else timedelta(hours=1))
        event.event_end_date = new_end.date()
        event.event_end_time = new_end.strftime("%H:%M")
        event.all_day = False
    connection = await db.get(CrmCalendarConnection, (organization_id, user_id))
    return await calendar_service.update_event(db, event=event, connection=connection)


@router.put(
    "/calendar/events/{event_id}", response_model=CalendarEventResponse, dependencies=EXPENSIVE_LANE
)
async def crm_edit_calendar_event(
    event_id: int,
    payload: CalendarEventCreate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    event = await _own_event(db, context, event_id)
    if payload.lead_id is not None and payload.lead_id != event.lead_id:
        await _visible_lead(db, context, payload.lead_id)
    if payload.meet and not event.meet:
        # A fresh request id, or Google treats it as the earlier (removed) conference.
        event.meet_request_id = secrets.token_urlsafe(20)
    if not payload.meet:
        event.meet_link = None
        event.meet_request_id = None
    event.title = payload.title.strip()
    event.event_date = payload.date
    event.event_time = None if payload.all_day else payload.time
    event.event_end_date = payload.end_date or payload.date
    event.event_end_time = None if payload.all_day else payload.end_time
    event.all_day = payload.all_day or payload.time is None
    event.repeat = payload.repeat
    event.meet = payload.meet
    event.location = payload.location.strip()
    event.reminders = payload.reminders
    event.reminders_use_default = payload.reminders_use_default
    event.guests = payload.guests
    event.guests_can_modify = payload.guests_can_modify
    event.guests_can_invite_others = payload.guests_can_invite_others
    event.guests_can_see_other_guests = payload.guests_can_see_other_guests
    event.show_as = payload.show_as
    event.visibility = payload.visibility
    event.kind = payload.kind
    event.detail = payload.detail.strip()
    event.lead_id = payload.lead_id
    event.listing_id = payload.listing_id
    connection = await db.get(CrmCalendarConnection, (organization_id, user_id))
    return await calendar_service.update_event(db, event=event, connection=connection)


@router.post(
    "/calendar/events/{event_id}/done",
    response_model=CalendarEventResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_complete_calendar_event(
    event_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    event = await _own_event(db, context, event_id)
    event.done = True
    connection = await db.get(CrmCalendarConnection, (organization_id, user_id))
    return await calendar_service.update_event(db, event=event, connection=connection)


@router.delete("/calendar/events/{event_id}", status_code=204, dependencies=EXPENSIVE_LANE)
async def crm_delete_calendar_event(
    event_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    event = await _own_event(db, context, event_id)
    connection = await db.get(CrmCalendarConnection, (organization_id, user_id))
    try:
        await calendar_service.delete_event(db, event=event, connection=connection)
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(
            status_code=502, detail="Could not delete the Google Calendar event"
        ) from exc
    return Response(status_code=204)


# ── Connectors › Email (Brevo) ──
# Templates are shared by the organization. Leads, sends, tracking, the inbox and a lead's
# thread follow lead assignment: an agent sees mail about leads they may see.


async def _email_scope(db: AsyncSession, auth: AuthContext) -> assignment.AssignmentScope:
    user_id, organization_id = _auth_ids(auth)
    return await assignment.load_scope(db, organization_id, user_id)


async def _visible_mail_leads(
    db: AsyncSession, scope: assignment.AssignmentScope
) -> set[int] | None:
    """The leads with mail this user may see; None for an administrator (no limit)."""
    if scope.organization_admin:
        return None
    store = await email_store.read()
    org = scope.organization_id
    ids = {s.enquiry_id for s in store.sends if s.organization_id == org and s.enquiry_id}
    ids |= {m.enquiry_id for m in store.inbound if m.organization_id == org and m.enquiry_id}
    return await assignment.visible_ids(db, scope, ids)


@router.get("/email/status", response_model=EmailStatusResponse, dependencies=LIGHT_LANE)
async def crm_email_status(context: AuthContext = Depends(require_active_subscription)):
    """Whether Brevo is configured on the server, and the sender leads see."""
    return email_status()


@router.get("/email/leads", response_model=EmailLeadListResponse, dependencies=EXPENSIVE_LANE)
async def crm_email_leads(
    search: str | None = Query(default=None, max_length=160),
    intent: str | None = Query(default=None, pattern="^(unknown|buy|rent|sell|let)$"),
    source: str | None = Query(default=None, max_length=120),
    ids: list[int] | None = Query(default=None, max_length=100),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Leads this user may see whose contact has an email, each with its latest email status.

    `ids` narrows to those leads (Compose showing who it will send to).
    """
    scope = await _email_scope(db, context)
    return await list_email_leads(
        db,
        organization_id=scope.organization_id,
        search=search,
        intent=intent,
        source=source,
        limit=limit,
        offset=offset,
        ids=ids,
        visible=assignment.visible_clause(scope),
    )


@router.get("/email/templates", response_model=list[EmailTemplateResponse], dependencies=LIGHT_LANE)
async def crm_email_templates(context: AuthContext = Depends(require_active_subscription)):
    """The organization's email templates, shared by every agent."""
    _, organization_id = _auth_ids(context)
    return await list_templates(organization_id=organization_id)


@router.post(
    "/email/templates",
    response_model=EmailTemplateResponse,
    status_code=201,
    dependencies=LIGHT_LANE,
)
async def crm_create_email_template(
    payload: EmailTemplateWrite,
    context: AuthContext = Depends(require_active_subscription),
):
    user_id, organization_id = _auth_ids(context)
    return await create_template(organization_id=organization_id, user_id=user_id, payload=payload)


@router.put(
    "/email/templates/{template_id}", response_model=EmailTemplateResponse, dependencies=LIGHT_LANE
)
async def crm_update_email_template(
    template_id: int,
    payload: EmailTemplateWrite,
    context: AuthContext = Depends(require_active_subscription),
):
    user_id, organization_id = _auth_ids(context)
    return await update_template(
        organization_id=organization_id,
        user_id=user_id,
        template_id=template_id,
        payload=payload,
    )


@router.delete("/email/templates/{template_id}", status_code=204, dependencies=LIGHT_LANE)
async def crm_delete_email_template(
    template_id: int,
    context: AuthContext = Depends(require_active_subscription),
):
    _, organization_id = _auth_ids(context)
    await delete_template(organization_id=organization_id, template_id=template_id)
    return Response(status_code=204)


@router.post("/email/send", response_model=EmailSendBatchResponse, dependencies=EXPENSIVE_LANE)
async def crm_send_email(
    payload: EmailSendCreate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Send one personalised email per lead through Brevo; each lands on the lead's history.

    Only leads this user may see; any other id is reported as not found.
    """
    scope = await _email_scope(db, context)
    return await send_emails(
        db,
        organization_id=scope.organization_id,
        user_id=scope.user_id,
        payload=payload,
        visible=assignment.visible_clause(scope),
    )


@router.get("/email/sends", response_model=EmailSendListResponse, dependencies=EXPENSIVE_LANE)
async def crm_email_sends(
    status: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Tracking: sends to leads this user may see, newest first, with their delivery events."""
    scope = await _email_scope(db, context)
    return await list_sends(
        organization_id=scope.organization_id,
        status=status,
        limit=limit,
        offset=offset,
        visible_lead_ids=await _visible_mail_leads(db, scope),
    )


@router.delete("/email/sends/{send_id}", status_code=204, dependencies=EXPENSIVE_LANE)
async def crm_delete_email_send(
    send_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Remove one sent email from Tracking (and from the lead's Conversation tab)."""
    scope = await _email_scope(db, context)
    await delete_send(
        organization_id=scope.organization_id,
        send_id=send_id,
        visible_lead_ids=await _visible_mail_leads(db, scope),
    )
    return Response(status_code=204)


@router.post("/email/tracking/sync", response_model=EmailSyncResponse, dependencies=EXPENSIVE_LANE)
async def crm_sync_email_events(context: AuthContext = Depends(require_active_subscription)):
    """Pull delivery events from Brevo (the webhook cannot reach localhost)."""
    _, organization_id = _auth_ids(context)
    return await sync_events(organization_id=organization_id)


@router.get("/email/inbound", response_model=EmailInboundListResponse, dependencies=EXPENSIVE_LANE)
async def crm_email_inbound(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Received emails about leads this user may see, newest first."""
    scope = await _email_scope(db, context)
    return await list_inbound(
        db,
        organization_id=scope.organization_id,
        limit=limit,
        offset=offset,
        visible_lead_ids=await _visible_mail_leads(db, scope),
    )


@router.get(
    "/email/leads/{enquiry_id}/thread",
    response_model=list[EmailThreadItem],
    dependencies=LIGHT_LANE,
)
async def crm_email_lead_thread(
    enquiry_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Every email sent to and received from one lead, oldest first."""
    await _visible_lead(db, context, enquiry_id)
    _, organization_id = _auth_ids(context)
    return await lead_thread(organization_id=organization_id, enquiry_id=enquiry_id)


@router.post(
    "/inbound/enquiries",
    response_model=InboundEnquiryResponse,
    status_code=201,
    dependencies=LIGHT_LANE,
)
async def crm_create_inbound_enquiry(
    payload: InboundEnquiryCreate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Create a manually entered buyer, tenant, seller, or landlord enquiry."""
    user_id, organization_id = _auth_ids(context)
    return await create_inbound_enquiry(
        db, payload=payload, user_id=user_id, organization_id=organization_id
    )


@router.get(
    "/inbound/enquiries", response_model=InboundEnquiryListResponse, dependencies=LIGHT_LANE
)
async def crm_inbound_enquiries(
    intent_group: str | None = Query(default=None, pattern="^(demand|instructions)$"),
    workspace: str | None = Query(default=None, pattern="^(inbox|unqualified|qualified|closed)$"),
    status: str | None = Query(default=None, max_length=40),
    search: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    within_days: int | None = Query(default=None, ge=1, le=365),
    leads_only: bool = Query(default=False),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """List organization-visible inbound enquiries and review exceptions.

    `within_days` keeps items dated within that many days (Inbox "Last 30 days"); a recently
    sold owner is dated by the sale. `leads_only` leaves out contacts that are not leads yet
    (the Leads list), so Inbox contacts cannot crowd leads out of a page.
    """
    user_id, organization_id = _auth_ids(context)
    return await list_inbound_enquiries(
        db,
        organization_id=organization_id,
        user_id=user_id,
        intent_group=intent_group,
        workspace=workspace,
        status=status,
        search=search,
        limit=limit,
        offset=offset,
        within_days=within_days,
        leads_only=leads_only,
    )


@router.post(
    "/inbound/enquiries/{enquiry_id}/approve-buyer",
    response_model=InboundEnquiryResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_approve_recent_seller(
    enquiry_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Approve a recently sold owner from the Inbox as a possible buyer lead (no brief yet)."""
    user_id, organization_id = _auth_ids(context)
    return await approve_recent_seller(
        db, enquiry_id=enquiry_id, user_id=user_id, organization_id=organization_id
    )


@router.get(
    "/inbound/enquiries/{enquiry_id}",
    response_model=InboundEnquiryResponse,
    dependencies=LIGHT_LANE,
)
async def crm_inbound_enquiry(
    enquiry_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    return await get_inbound_enquiry(db, enquiry_id, organization_id, user_id=user_id)


@router.patch(
    "/inbound/enquiries/{enquiry_id}",
    response_model=InboundEnquiryResponse,
    dependencies=LIGHT_LANE,
)
async def crm_update_inbound_enquiry(
    enquiry_id: int,
    payload: InboundEnquiryUpdate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    return await update_inbound_enquiry(
        db,
        enquiry_id=enquiry_id,
        organization_id=organization_id,
        user_id=user_id,
        payload=payload,
    )


@router.post(
    "/inbound/enquiries/{enquiry_id}/notes",
    response_model=InboundEnquiryResponse,
    dependencies=LIGHT_LANE,
)
async def crm_add_inbound_note(
    enquiry_id: int,
    payload: InboundNoteCreate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    return await add_inbound_note(
        db,
        enquiry_id=enquiry_id,
        organization_id=organization_id,
        user_id=user_id,
        body=payload.body,
    )


@router.post(
    "/inbound/enquiries/{enquiry_id}/activities",
    response_model=InboundEnquiryResponse,
    dependencies=LIGHT_LANE,
)
async def crm_add_inbound_activity(
    enquiry_id: int,
    payload: InboundActivityCreate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    return await add_inbound_activity(
        db,
        enquiry_id=enquiry_id,
        organization_id=organization_id,
        user_id=user_id,
        activity_type=payload.activity_type,
        body=payload.body,
    )


@router.get(
    "/inbound/enquiries/{enquiry_id}/matches",
    response_model=InboundMatchesResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_inbound_matches(
    enquiry_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    scope = await assignment.load_scope(db, organization_id, user_id)
    return await get_inbound_matches(db, enquiry_id, organization_id, scope=scope)


@router.post(
    "/inbound/enquiries/{enquiry_id}/matches/refresh",
    response_model=InboundMatchesResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_refresh_inbound_matches(
    enquiry_id: int,
    expand_units: bool = Query(default=False),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    return await refresh_inbound_matches(
        db,
        enquiry_id=enquiry_id,
        organization_id=organization_id,
        scope=await assignment.load_scope(db, organization_id, user_id),
        expand_units=expand_units,
    )


@router.patch(
    "/inbound/matches/{match_id}", response_model=InboundMatchResponse, dependencies=LIGHT_LANE
)
async def crm_update_inbound_match(
    match_id: int,
    payload: InboundMatchUpdate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    return await update_inbound_match_state(
        db,
        match_id=match_id,
        organization_id=organization_id,
        state=payload.state,
        scope=await assignment.load_scope(db, organization_id, user_id),
    )


@router.post(
    "/inbound/imports",
    response_model=InboundImportResponse,
    status_code=202,
    dependencies=EXPENSIVE_LANE,
)
async def crm_inbound_import(
    file: UploadFile = File(...),
    name: str = Form(default="", max_length=200),
    campaign_context: str = Form(default="", max_length=4_000),
    mapping_json: str = Form(default="", max_length=50_000),
    assignment_mode: Literal["self", "agent", "rules", "team", "unassigned"] = Form(...),
    assignee_user_id: str | None = Form(default=None, max_length=200),
    team_id: str | None = Form(default=None, max_length=200),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Normalize a campaign or CRM lead export into actionable enquiries.

    `assignment_mode` is required: `self` gives every new lead to the signed-in importer (the
    only mode for agents), `agent` gives them to `assignee_user_id`, `rules` applies the enabled
    routing rules (first match wins), `team` puts them in `team_id`'s shared pool for its agents
    to claim, `unassigned` leaves them with `team_id` for its manager to assign. Every mode but
    `self` needs a manager or organization administrator; `team_id` may be left out when the
    importer manages exactly one team.
    """
    user_id, organization_id = _auth_ids(context)
    try:
        policy = ImportAssignmentPolicy(
            mode=assignment_mode,
            assignee_user_id=assignee_user_id or None,
            team_id=team_id or None,
        )
    except ValidationError as exc:
        message = exc.errors()[0]["msg"].removeprefix("Value error, ")
        raise HTTPException(status_code=422, detail=message) from exc
    try:
        mapping_override = json.loads(mapping_json) if mapping_json else None
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Invalid import mapping") from exc
    return await process_inbound_import(
        db,
        upload=file,
        name=name,
        user_id=user_id,
        organization_id=organization_id,
        campaign_context=campaign_context,
        mapping_override=mapping_override,
        assignment_policy=policy,
    )


@router.get("/assignment/scope", response_model=AssignmentScopeResponse, dependencies=LIGHT_LANE)
async def crm_assignment_scope(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """What the signed-in user may do with lead assignment, and whom they may assign to."""
    user_id, organization_id = _auth_ids(context)
    scope = await assignment.load_scope(db, organization_id, user_id)
    return await assignment.scope_response(db, scope)


@router.put(
    "/assignment/people/{person_user_id}/languages",
    response_model=AgentLanguagesResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_set_agent_languages(
    person_user_id: str,
    payload: AgentLanguagesWrite,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Record the languages a team member speaks (a manager for their teams' people, an
    administrator for anyone). Used by routing rules set to "speakers only"; never inferred."""
    user_id, organization_id = _auth_ids(context)
    scope = await assignment.load_scope(db, organization_id, user_id)
    return await agent_languages.set_languages(db, scope, person_user_id, payload)


@router.post(
    "/inbound/assignments", response_model=LeadAssignmentResponse, dependencies=EXPENSIVE_LANE
)
async def crm_assign_leads(
    payload: LeadAssignmentRequest,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Assign, reassign or (with a null assignee) unassign up to 100 leads, all or none.

    A lead changed since `expected_revisions` was read makes the whole request a 409.
    """
    user_id, organization_id = _auth_ids(context)
    return await assignment.assign_leads(db, organization_id, user_id, payload)


@router.get("/assignment/workload", response_model=WorkloadResponse, dependencies=EXPENSIVE_LANE)
async def crm_team_workload(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """For managers and administrators: each managed team's open leads per person, by stage,
    with first contacts still to make and overdue, the team's waiting and shared leads, and each
    person's last logged activity. Recorded facts only; nothing is scored or ranked."""
    user_id, organization_id = _auth_ids(context)
    return await oversight.team_workload(db, organization_id, user_id)


@router.get(
    "/assignment/analytics", response_model=TeamAnalyticsResponse, dependencies=EXPENSIVE_LANE
)
async def crm_team_analytics(
    days: AnalyticsWindow = Query(AnalyticsWindow.month),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """For managers and administrators: each person in their teams with open work, average
    first-response and pool claim times and leads contacted in the last 24 hours, over the last
    7, 30 or 90 days. Recorded facts only; nothing is scored or ranked."""
    user_id, organization_id = _auth_ids(context)
    return await agent_analytics.team_analytics(db, organization_id, user_id, days=int(days))


@router.get(
    "/assignment/analytics/{agent_user_id}",
    response_model=AgentAnalyticsDetail,
    dependencies=EXPENSIVE_LANE,
)
async def crm_agent_analytics(
    agent_user_id: str,
    days: AnalyticsWindow = Query(AnalyticsWindow.month),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """One person's figures, lead sources, last 7 days of activity and leads, for a manager of
    their team. Anyone outside the caller's teams answers 404. Recorded facts only."""
    user_id, organization_id = _auth_ids(context)
    return await agent_analytics.agent_analytics(
        db, organization_id, user_id, agent_user_id, days=int(days)
    )


@router.post("/inbound/pool", response_model=LeadAssignmentResponse, dependencies=EXPENSIVE_LANE)
async def crm_release_leads_to_pool(
    payload: PoolReleaseRequest,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Put up to 100 leads, unassigned, in a team's shared pool, all or none: the team's agents
    see them and the first to log contact takes each one."""
    user_id, organization_id = _auth_ids(context)
    return await assignment.release_to_pool(db, organization_id, user_id, payload)


@router.get(
    "/inbound/enquiries/{enquiry_id}/assignments",
    response_model=list[AssignmentEventResponse],
    dependencies=LIGHT_LANE,
)
async def crm_lead_assignment_history(
    enquiry_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    return await assignment.assignment_history(db, organization_id, user_id, enquiry_id)


@router.get("/routing/rules", response_model=list[RoutingRuleResponse], dependencies=EXPENSIVE_LANE)
async def crm_routing_rules(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Lead routing rules in first-match order (managers see their own teams' rules)."""
    user_id, organization_id = _auth_ids(context)
    scope = await assignment.load_scope(db, organization_id, user_id)
    return await routing.list_rules(db, scope)


@router.post(
    "/routing/rules",
    response_model=RoutingRuleResponse,
    status_code=201,
    dependencies=EXPENSIVE_LANE,
)
async def crm_create_routing_rule(
    payload: RoutingRuleWrite,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Add a rule at the end of the order (organization administrators)."""
    user_id, organization_id = _auth_ids(context)
    scope = await assignment.load_scope(db, organization_id, user_id)
    return await routing.create_rule(db, scope, payload)


@router.put(
    "/routing/rules/order", response_model=list[RoutingRuleResponse], dependencies=EXPENSIVE_LANE
)
async def crm_reorder_routing_rules(
    payload: RoutingRuleOrder,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    scope = await assignment.load_scope(db, organization_id, user_id)
    return await routing.reorder_rules(db, scope, payload)


@router.put(
    "/routing/rules/{rule_id}", response_model=RoutingRuleResponse, dependencies=EXPENSIVE_LANE
)
async def crm_update_routing_rule(
    rule_id: int,
    payload: RoutingRuleUpdate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    scope = await assignment.load_scope(db, organization_id, user_id)
    return await routing.update_rule(db, scope, rule_id, payload)


@router.delete("/routing/rules/{rule_id}", status_code=204, dependencies=EXPENSIVE_LANE)
async def crm_delete_routing_rule(
    rule_id: int,
    expected_revision: int = Query(ge=1),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    scope = await assignment.load_scope(db, organization_id, user_id)
    await routing.delete_rule(db, scope, rule_id, expected_revision)
    return Response(status_code=204)


@router.post(
    "/inbound/imports/preview",
    response_model=InboundImportPreviewResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_preview_inbound_import(
    file: UploadFile = File(...),
    campaign_context: str = Form(default="", max_length=4_000),
    context: AuthContext = Depends(require_active_subscription),
):
    """Inspect headers and samples without storing contacts or creating enquiries."""
    return await preview_inbound_import(file, campaign_context)


@router.get(
    "/company-listings", response_model=CrmCompanyListingsResponse, dependencies=EXPENSIVE_LANE
)
async def crm_company_listings(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    broker_id: str | None = Query(default=None, max_length=80),
    all_companies: bool = Query(default=False),
    agent_id: str | None = Query(default=None, max_length=120),
    agent_name: str | None = Query(default=None, max_length=200),
    search: str | None = Query(default=None, max_length=120),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Current Property Finder listings for the connected or requested company.

    `search` matches a listing's title, building or area (property name).
    """
    if (agent_id or agent_name) and not broker_id:
        raise HTTPException(status_code=422, detail="Select a company before filtering by agent")
    _, organization_id = _auth_ids(context)
    return await list_company_listings(
        db,
        organization_id,
        limit=limit,
        offset=offset,
        broker_id=broker_id,
        all_companies=all_companies,
        agent_id=agent_id,
        agent_name=agent_name,
        search=search,
    )


@router.get("/collections", response_model=CollectionListResponse, dependencies=EXPENSIVE_LANE)
async def crm_collections(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Collections the signed-in user manages (own; all of the organization's for owners)."""
    return await collection_service.list_collections(
        db, actor=_collection_actor(context), limit=limit, offset=offset
    )


@router.post(
    "/collections", response_model=CollectionResponse, status_code=201, dependencies=EXPENSIVE_LANE
)
async def crm_create_collection(
    payload: CollectionCreate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await collection_service.create_collection(
        db, actor=_collection_actor(context), payload=payload
    )


@router.get(
    "/collections/{collection_id}",
    response_model=CollectionDetailResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_collection(
    collection_id: UUID,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """The collection with its items resolved against current inventory.

    503 `listings_unavailable` when the warehouse cannot be read.
    """
    try:
        return await collection_service.get_collection(
            db, actor=_collection_actor(context), collection_id=collection_id
        )
    except collection_service.WAREHOUSE_ERRORS as exc:
        raise HTTPException(status_code=503, detail="listings_unavailable") from exc


@router.patch(
    "/collections/{collection_id}", response_model=CollectionResponse, dependencies=EXPENSIVE_LANE
)
async def crm_update_collection(
    collection_id: UUID,
    payload: CollectionUpdate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    return await collection_service.update_collection(
        db, actor=_collection_actor(context), collection_id=collection_id, payload=payload
    )


@router.delete("/collections/{collection_id}", status_code=204, dependencies=EXPENSIVE_LANE)
async def crm_delete_collection(
    collection_id: UUID,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    await collection_service.delete_collection(
        db, actor=_collection_actor(context), collection_id=collection_id
    )
    return Response(status_code=204)


@router.put(
    "/collections/{collection_id}/items",
    response_model=CollectionItemResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_add_collection_item(
    collection_id: UUID,
    payload: CollectionItemAdd,
    response: Response,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """201 when added, 200 when the listing was already in the collection."""
    item, created = await collection_service.add_item(
        db, actor=_collection_actor(context), collection_id=collection_id, payload=payload
    )
    response.status_code = 201 if created else 200
    return item


@router.delete(
    "/collections/{collection_id}/items/{item_id}", status_code=204, dependencies=EXPENSIVE_LANE
)
async def crm_remove_collection_item(
    collection_id: UUID,
    item_id: UUID,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    await collection_service.remove_item(
        db, actor=_collection_actor(context), collection_id=collection_id, item_id=item_id
    )
    return Response(status_code=204)


@router.post(
    "/collections/{collection_id}/share-link",
    response_model=ShareLinkResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_collection_share_link(
    collection_id: UUID,
    response: Response,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """The public URL; 409 `sharing_disabled` until sharing is switched on."""
    response.headers["Cache-Control"] = "no-store"
    return await collection_service.share_url(
        db, actor=_collection_actor(context), collection_id=collection_id
    )


@router.post(
    "/collections/{collection_id}/share-link/rotate",
    response_model=ShareLinkResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_rotate_collection_share_link(
    collection_id: UUID,
    response: Response,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Replace the URL; the previous one stops working."""
    response.headers["Cache-Control"] = "no-store"
    return await collection_service.rotate_token(
        db, actor=_collection_actor(context), collection_id=collection_id
    )


@router.get(
    "/company-listings/{listing_key}",
    response_model=CrmCompanyListingDetail,
    dependencies=EXPENSIVE_LANE,
)
async def crm_company_listing(
    listing_key: str = Path(pattern=LISTING_KEY_PATTERN),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """One current Property Finder listing; `managed` when it is the connected company's."""
    _, organization_id = _auth_ids(context)
    listing = await get_company_listing(db, organization_id, listing_key)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return listing


@router.get(
    "/listing-document-info",
    response_model=ListingDocumentInfoResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_listing_document_info(
    source: Literal["property_finder"] = Query(),
    listing_key: str = Query(pattern=LISTING_KEY_PATTERN),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """A managed listing with the document information saved for it (revision 0 = none yet)."""
    _, organization_id = _auth_ids(context)
    return await get_document_info(db, organization_id=organization_id, listing_key=listing_key)


@router.put(
    "/listing-document-info",
    response_model=ListingDocumentInfoResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_save_listing_document_info(
    payload: ListingDocumentInfoUpdate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Save a listing's document information; 409 `stale_revision` if someone saved first."""
    user_id, organization_id = _auth_ids(context)
    return await save_document_info(
        db, organization_id=organization_id, user_id=user_id, payload=payload
    )


@router.post(
    "/documents",
    response_model=GeneratedDocumentResponse,
    status_code=201,
    dependencies=EXPENSIVE_LANE,
)
async def crm_generate_document(
    payload: GenerateDocumentRequest,
    response: Response,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Generate one PDF from a managed listing's saved information.

    201 = made now; 200 = this idempotency key already has a document (returned as is).
    422 `missing_fields`, 409 `stale_revision`, 502 when rendering or storage failed.
    """
    user_id, organization_id = _auth_ids(context)
    document, created = await generate_document(
        db, organization_id=organization_id, user_id=user_id, payload=payload
    )
    if not created:
        response.status_code = 200
    return document


@router.get("/documents", response_model=GeneratedDocumentListResponse, dependencies=EXPENSIVE_LANE)
async def crm_documents(
    listing_key: str | None = Query(default=None, pattern=LISTING_KEY_PATTERN),
    doc_type: DocType | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """The organization's generated documents, newest first."""
    _, organization_id = _auth_ids(context)
    return await list_documents(
        db,
        organization_id=organization_id,
        listing_key=listing_key,
        doc_type=doc_type,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/documents/{document_id}",
    response_model=GeneratedDocumentResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_document(
    document_id: UUID,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    _, organization_id = _auth_ids(context)
    return await get_document(db, organization_id=organization_id, document_id=document_id)


@router.post(
    "/documents/{document_id}/download",
    response_model=DocumentDownloadResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_download_document(
    document_id: UUID,
    response: Response,
    inline: bool = Query(default=False),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """A link valid for 5 minutes (`inline=true` previews it in the browser).

    409 `not_ready` unless the PDF was made.
    """
    _, organization_id = _auth_ids(context)
    link = await download_document(
        db, organization_id=organization_id, document_id=document_id, inline=inline
    )
    # The link is a bearer credential: never cache it.
    response.headers["Cache-Control"] = "no-store"
    return link


@router.put(
    "/company-listings/source",
    response_model=CrmCompanyListingSourceResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_select_company_listing_source(
    payload: CrmCompanyListingSourceUpdate,
    context: AuthContext = Depends(require_active_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Set the Property Finder broker whose inventory belongs in the organization CRM."""
    user_id, organization_id = _auth_ids(context)
    source = await select_company_source(
        db,
        organization_id=organization_id,
        user_id=user_id,
        broker_id=payload.broker_id,
    )
    return CrmCompanyListingSourceResponse(
        broker_id=source.broker_id, broker_name=source.broker_name
    )


@router.delete("/company-listings/source", status_code=204, dependencies=EXPENSIVE_LANE)
async def crm_clear_company_listing_source(
    context: AuthContext = Depends(require_active_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Stop using a Property Finder company for buyer and tenant matching."""
    _, organization_id = _auth_ids(context)
    await clear_company_source(db, organization_id=organization_id)


@router.get("/inbound/imports", response_model=list[InboundImportResponse], dependencies=LIGHT_LANE)
async def crm_inbound_imports(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    return await list_inbound_imports(db, organization_id, user_id=user_id)


@router.delete("/inbound/imports/{import_id}", status_code=204, dependencies=EXPENSIVE_LANE)
async def crm_delete_inbound_import(
    import_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    await delete_inbound_import(db, import_id, organization_id, user_id=user_id)
    return Response(status_code=204)


@router.post(
    "/contact-imports",
    response_model=CrmContactImportResponse,
    status_code=202,
    dependencies=EXPENSIVE_LANE,
)
async def crm_contact_import(
    file: UploadFile = File(...),
    name: str = Form(default="", max_length=200),
    mapping_json: str = Form(default="", max_length=50_000),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Upload, normalize, verify, and publish an owner-contact workbook.

    Managers and organization administrators only: an agent sends the file for approval
    (`POST /contact-import-requests`) instead.
    """
    user_id, organization_id = _auth_ids(context)
    scope = await assignment.load_scope(db, organization_id, user_id)
    if owner_import_requests.needs_approval(scope):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "OWNER_IMPORT_NEEDS_APPROVAL",
                "message": "Send the owner file to your manager for approval.",
            },
        )
    try:
        mapping_override = json.loads(mapping_json) if mapping_json else None
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Invalid import mapping") from exc
    if mapping_override is not None and not isinstance(mapping_override, dict):
        raise HTTPException(status_code=422, detail="Invalid import mapping")
    return await process_contact_import(
        db,
        upload=file,
        name=name,
        user_id=user_id,
        organization_id=organization_id,
        mapping_override=mapping_override,
    )


@router.post(
    "/contact-imports/preview",
    response_model=CrmContactImportPreview,
    dependencies=EXPENSIVE_LANE,
)
async def crm_contact_import_preview(
    file: UploadFile = File(...),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Show which field each column of an owner file feeds, without importing it."""
    _, organization_id = _auth_ids(context)
    return await preview_contact_import(db, upload=file, organization_id=organization_id)


@router.post(
    "/contact-imports/source-only",
    response_model=CrmContactImportResponse,
    status_code=202,
    dependencies=EXPENSIVE_LANE,
)
async def crm_source_only_import(
    file: UploadFile = File(...),
    name: str = Form(default="", max_length=200),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Import reviewed source history without requesting registry evidence."""
    from app.crm.source_audit import process_source_audit_import

    user_id, organization_id = _auth_ids(context)
    return await process_source_audit_import(
        db, upload=file, name=name, user_id=user_id, organization_id=organization_id
    )


@router.post(
    "/contact-import-requests",
    response_model=OwnerImportRequestResponse,
    status_code=201,
    dependencies=EXPENSIVE_LANE,
)
async def crm_request_owner_import(
    file: UploadFile = File(...),
    name: str = Form(default="", max_length=200),
    team_id: str | None = Form(default=None, max_length=200),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """An agent sends an owner file; it is imported once their manager approves it."""
    user_id, organization_id = _auth_ids(context)
    return await owner_import_requests.request_import(
        db,
        organization_id=organization_id,
        user_id=user_id,
        upload=file,
        name=name,
        team_id=team_id,
    )


@router.get(
    "/contact-import-requests",
    response_model=list[OwnerImportRequestResponse],
    dependencies=LIGHT_LANE,
)
async def crm_owner_import_requests(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Your own owner-file requests, and those you may approve, newest first."""
    user_id, organization_id = _auth_ids(context)
    return await owner_import_requests.list_requests(
        db, organization_id=organization_id, user_id=user_id
    )


@router.post(
    "/contact-import-requests/{request_id}/approve",
    response_model=OwnerImportRequestResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_approve_owner_import(
    request_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    return await owner_import_requests.approve(
        db, organization_id=organization_id, user_id=user_id, request_id=request_id
    )


@router.post(
    "/contact-import-requests/{request_id}/reject",
    response_model=OwnerImportRequestResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_reject_owner_import(
    request_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    return await owner_import_requests.reject(
        db, organization_id=organization_id, user_id=user_id, request_id=request_id
    )


@router.get(
    "/contact-imports",
    response_model=list[CrmContactImportResponse],
    dependencies=LIGHT_LANE,
)
async def crm_contact_imports(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """List contact imports for the signed-in organization."""
    _, organization_id = _auth_ids(context)
    return await list_contact_imports(db, organization_id=organization_id)


@router.patch(
    "/contact-imports/{import_id}",
    response_model=CrmContactImportResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_rename_contact_import(
    import_id: int,
    payload: CrmContactImportRename,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Rename an import and its corresponding Saved folder."""
    _, organization_id = _auth_ids(context)
    return await rename_contact_import(
        db,
        import_id=import_id,
        name=payload.name,
        organization_id=organization_id,
    )


@router.delete("/contact-imports/{import_id}", status_code=204, dependencies=EXPENSIVE_LANE)
async def crm_delete_contact_import(
    import_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Delete one source import, its Saved folder, and its imported claims."""
    _, organization_id = _auth_ids(context)
    await delete_contact_import(
        db,
        import_id=import_id,
        organization_id=organization_id,
    )
    return Response(status_code=204)


@router.get(
    "/contact-imports/{import_id}/dropped-rows",
    response_model=CrmDroppedRowsResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_contact_import_dropped_rows(
    import_id: int,
    reason: str | None = Query(
        default=None,
        pattern="^(no_name|not_buyer_seller|not_a_sale|no_unit)$",
    ),
    search: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Rows of one import that were not kept, with the file's values and the reason.

    Read from the dropped-rows log saved at upload; `available` is false for imports made
    before the log existed.
    """
    _, organization_id = _auth_ids(context)
    return await list_dropped_rows(
        db,
        import_id=import_id,
        organization_id=organization_id,
        reason=reason,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/contact-imports/{import_id}/properties",
    response_model=CrmImportPropertiesResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_contact_import_properties(
    import_id: int,
    search: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Distinct properties (building + unit) of one import, each with its kept rows."""
    _, organization_id = _auth_ids(context)
    return await list_import_properties(
        db,
        import_id=import_id,
        organization_id=organization_id,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/contact-lists",
    response_model=list[CrmContactListSummary],
    dependencies=LIGHT_LANE,
)
async def crm_contact_lists(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """List organization owner-contact folders."""
    _, organization_id = _auth_ids(context)
    return await list_contact_lists(db, organization_id=organization_id)


@router.get(
    "/contact-lists/{list_id}",
    response_model=CrmContactListDetail,
    dependencies=EXPENSIVE_LANE,
)
async def crm_contact_list(
    list_id: int,
    status: str | None = Query(
        default=None,
        pattern=(
            "^(verified_current_owner|probable_current_owner|unit_linked_unverified|"
            "former_owner|unverified_former_owner|conflicting_claim|insufficient_property_data|"
            "registry_not_observed|unmatched)$"
        ),
    ),
    match_colour: list[Literal["green", "amber", "blue", "red", "grey"]] | None = Query(
        default=None,
        description="Keep rows whose property-first match is one of these colours.",
    ),
    match_outcome: list[str] | None = Query(
        default=None,
        description="Keep rows with one of these match outcomes (for example `lender` or `broker`).",
    ),
    search: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Return one curated owner-contact folder and its verification results."""
    _, organization_id = _auth_ids(context)
    return await get_contact_list(
        db,
        list_id=list_id,
        organization_id=organization_id,
        status=status,
        match_colour=match_colour,
        match_outcome=match_outcome,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/owner-registry",
    response_model=CrmOwnerRegistryResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_owner_registry(
    scope: str = Query(
        default="all",
        pattern="^(all|current_owners|rental_ready|registry|prior_owners|needs_review)$",
    ),
    list_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(
        default=None,
        pattern=(
            "^(verified_current_owner|probable_current_owner|unit_linked_unverified|"
            "former_owner|unverified_former_owner|conflicting_claim|insufficient_property_data|"
            "registry_not_observed|unmatched)$"
        ),
    ),
    transaction_match_status: str | None = Query(
        default=None, pattern="^(matched|unmatched|ambiguous|excluded)$"
    ),
    search: str | None = Query(default=None, max_length=160),
    lease_window: str | None = Query(
        default=None,
        pattern="^(expired|expiring_30|expiring_60|expiring_90)$",
    ),
    portfolio_only: bool = Query(default=False),
    min_rent_aed: int | None = Query(default=None, ge=0, le=10_000_000_000),
    max_rent_aed: int | None = Query(default=None, ge=0, le=10_000_000_000),
    min_value_aed: int | None = Query(default=None, ge=0, le=100_000_000_000),
    max_value_aed: int | None = Query(default=None, ge=0, le=100_000_000_000),
    min_properties: int | None = Query(default=None, ge=1, le=10_000),
    next_event_days: int | None = Query(default=None, ge=0, le=3_650),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Return deduplicated owner profiles grouped into actionable CRM folders.

    `min_properties` keeps owners with at least that many units; `next_event_days` keeps owners
    whose next lease ends between today and that many days from now.
    """
    _, organization_id = _auth_ids(context)
    return await get_owner_registry(
        db,
        organization_id=organization_id,
        list_id=list_id,
        scope=scope,
        status=status,
        search=search,
        lease_window=lease_window,
        portfolio_only=portfolio_only,
        min_rent_aed=min_rent_aed,
        max_rent_aed=max_rent_aed,
        min_value_aed=min_value_aed,
        max_value_aed=max_value_aed,
        limit=limit,
        offset=offset,
        min_properties=min_properties,
        next_event_days=next_event_days,
        transaction_match_status=transaction_match_status,
    )


@router.get(
    "/owner-workspaces",
    response_model=list[CrmOwnerWorkspaceSummary],
    dependencies=LIGHT_LANE,
)
async def crm_owner_workspaces(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """List agent state and note summaries for owner profiles."""
    user_id, organization_id = _auth_ids(context)
    return await list_owner_workspaces(
        db,
        user_id=user_id,
        organization_id=organization_id,
    )


@router.patch(
    "/owner-workspaces/bulk",
    response_model=list[CrmOwnerWorkspaceSummary],
    dependencies=LIGHT_LANE,
)
async def crm_bulk_update_owner_workspaces(
    payload: CrmOwnerBulkUpdate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Apply pipeline, highlight, or note updates to selected owner profiles."""
    user_id, organization_id = _auth_ids(context)
    return await bulk_update_owner_workspaces(
        db,
        payload=payload,
        user_id=user_id,
        organization_id=organization_id,
    )


@router.get(
    "/owner-history/summary",
    response_model=CrmOwnerHistorySummary,
    dependencies=EXPENSIVE_LANE,
)
async def crm_owner_history_summary(
    import_id: int | None = Query(default=None, ge=1),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Count source events and scoped owner/property evidence across imports."""
    _, organization_id = _auth_ids(context)
    return await get_owner_history_summary(db, organization_id=organization_id, import_id=import_id)


@router.get(
    "/contact-imports/{import_id}/owner-summary",
    response_model=CrmOwnerHistorySummary,
    dependencies=EXPENSIVE_LANE,
)
async def crm_contact_import_owner_summary(
    import_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Count this file's associations using current evidence from all tenant imports."""
    _, organization_id = _auth_ids(context)
    return await get_owner_history_summary(db, organization_id=organization_id, import_id=import_id)


@router.get(
    "/owners/{owner_key}/history",
    response_model=CrmOwnerHistoryResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_owner_history(
    owner_key: str,
    import_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Page one owner's individual source events across organization imports."""
    _, organization_id = _auth_ids(context)
    return await get_owner_history(
        db,
        organization_id=organization_id,
        owner_key=owner_key,
        import_id=import_id,
        limit=limit,
        offset=offset,
    )


@router.get("/owners/{owner_key}", response_model=CrmOwnerProfile, dependencies=EXPENSIVE_LANE)
async def crm_owner_profile(
    owner_key: str,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Return one owner and every property accumulated across organization imports."""
    _, organization_id = _auth_ids(context)
    return await get_owner_profile(
        db,
        organization_id=organization_id,
        owner_key=owner_key,
    )


@router.get("/dashboard", response_model=CrmDashboardResponse, dependencies=EXPENSIVE_LANE)
async def crm_dashboard(
    request: Request,
    status: str | None = Query(
        default=None, pattern="^(expired|expiring_30|expiring_60|expiring_90)$"
    ),
    priority: str | None = Query(default=None, pattern="^(urgent|high|medium)$"),
    asset_class: str | None = Query(default=None, pattern="^(residential|commercial|other)$"),
    property_type: str | None = Query(default=None, max_length=80),
    area: str | None = Query(default=None, max_length=160),
    project: str | None = Query(default=None, max_length=160),
    building: str | None = Query(default=None, max_length=200),
    search: str | None = Query(default=None, max_length=160),
    breakdown: str = Query(default="area", pattern="^(area|project|building)$"),
    expired_days: int = Query(default=365, ge=30, le=1825),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    as_of: date | None = Query(default=None),
    context: AuthContext = Depends(require_active_subscription),
):
    """Return actionable lease-expiry leads and location summaries."""
    return await _until_disconnect(
        request,
        get_dashboard(
            status=status,
            priority=priority,
            asset_class=asset_class,
            property_type=property_type,
            area=area,
            project=project,
            building=building,
            search=search,
            breakdown=breakdown,
            expired_days=expired_days,
            limit=limit,
            offset=offset,
            as_of=as_of,
        ),
    )


@router.get("/area-preferences", response_model=CrmAreaPreferencesResponse, dependencies=LIGHT_LANE)
async def crm_area_preferences(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the current agent's renewal-lead areas and lease-expiry windows."""
    user_id, organization_id = _auth_ids(context)
    return await get_area_preferences(db, user_id=user_id, organization_id=organization_id)


@router.put("/area-preferences", response_model=CrmAreaPreferencesResponse, dependencies=LIGHT_LANE)
async def crm_update_area_preferences(
    payload: CrmAreaPreferencesUpdate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Replace the current agent's renewal-lead areas and lease-expiry windows."""
    user_id, organization_id = _auth_ids(context)
    return await update_area_preferences(
        db,
        payload=payload,
        user_id=user_id,
        organization_id=organization_id,
    )


async def _until_disconnect(request: Request, work):
    """Answer `work`, or stop its lease queries if the agent abandons the request."""
    result = await until_disconnected(request.is_disconnected, work)
    # 499: the client closed the request; nobody reads this response.
    return Response(status_code=499) if result is None else result


@router.get("/renewals", response_model=CrmRenewalsResponse, dependencies=EXPENSIVE_LANE)
async def crm_renewals(
    request: Request,
    window: str | None = Query(
        default=None, pattern="^(vacant|expired|expiring_30|expiring_60|expiring_90)$"
    ),
    area: str | None = Query(default=None, max_length=160),
    property_type: str | None = Query(default=None, max_length=80),
    project: str | None = Query(default=None, max_length=160),
    building: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    as_of: date | None = Query(default=None),
    owner: Literal["known", "unknown"] = "known",
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Assets › Renewals: agency owners on file, or units whose owner is still unknown."""
    user_id, organization_id = _auth_ids(context)
    return await _until_disconnect(
        request,
        list_owner_renewals(
            db,
            user_id=user_id,
            organization_id=organization_id,
            owner=owner,
            window=window,
            area=area,
            property_type=property_type,
            project=project,
            building=building,
            limit=limit,
            offset=offset,
            as_of=as_of,
        ),
    )


@router.get("/renewal-areas", response_model=list[CrmRenewalArea], dependencies=EXPENSIVE_LANE)
async def crm_renewal_areas(
    request: Request,
    as_of: date | None = Query(default=None),
    context: AuthContext = Depends(require_active_subscription),
):
    """List areas in the lease-expiry dataset with their leases ending in the next 90 days."""
    return await _until_disconnect(request, list_renewal_areas(as_of=as_of))


@router.get("/renewal-leads", response_model=CrmRenewalLeadsResponse, dependencies=EXPENSIVE_LANE)
async def crm_renewal_leads(
    request: Request,
    kind: str | None = Query(default=None, pattern="^(vacant|upcoming|expired)$"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    as_of: date | None = Query(default=None),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Return one page of lease-expiry leads in the current agent's areas and windows.

    No kind: leases still running first (soonest end on top), then ended ones (most recent
    first). kind=upcoming: leases still running. kind=expired: leases that ended inside the
    look-back window. kind=vacant: ended with no later lease registered for the exact unit.
    `total` counts the requested kind across all pages; `counts` covers the whole window.
    """
    user_id, organization_id = _auth_ids(context)
    return await _until_disconnect(
        request,
        list_renewal_leads(
            db,
            kind=kind,
            user_id=user_id,
            organization_id=organization_id,
            limit=limit,
            offset=offset,
            as_of=as_of,
        ),
    )


@router.post(
    "/renewal-leads/{lease_id}/lead",
    response_model=InboundEnquiryResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_open_renewal_lead(
    lease_id: str,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Open a Vitevue lease as the agency's shared lead for its unit (created on first open)."""
    user_id, organization_id = _auth_ids(context)
    return await open_renewal_lead(
        db, lease_id=lease_id, user_id=user_id, organization_id=organization_id
    )


@router.post(
    "/contact-lists/{list_id}/issue",
    response_model=OwnerIssueResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_issue_owner_leads(
    list_id: int,
    payload: OwnerIssueRequest,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Issue owners from a processed owner sheet to agents as outbound leads."""
    user_id, organization_id = _auth_ids(context)
    return await issue_owner_leads(
        db, list_id=list_id, request=payload, user_id=user_id, organization_id=organization_id
    )


@router.post(
    "/renewal-leads/issue",
    response_model=RenewalIssueResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_issue_renewal_leads(
    payload: RenewalIssueRequest,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Issue selected renewal units to agents as outbound leads, routed like a Leads import."""
    user_id, organization_id = _auth_ids(context)
    return await issue_renewal_leads(
        db, request=payload, user_id=user_id, organization_id=organization_id
    )


@router.get("/leads/{lead_id}", response_model=CrmLeadDetailResponse, dependencies=EXPENSIVE_LANE)
async def crm_lead_detail(
    request: Request,
    lead_id: str,
    as_of: date | None = Query(default=None),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the evidence timeline and recommended action for one lead."""
    user_id, organization_id = _auth_ids(context)
    return await _until_disconnect(
        request,
        get_renewal_detail(
            db, lead_id=lead_id, as_of=as_of, user_id=user_id, organization_id=organization_id
        ),
    )


@router.get(
    "/leads/{lead_id}/contacts",
    response_model=list[CrmLeadImportedContact],
    dependencies=EXPENSIVE_LANE,
)
async def crm_lead_contacts(
    lead_id: str,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Return imported contacts linked to one exact lease-opportunity property."""
    _, organization_id = _auth_ids(context)
    return await list_lead_imported_contacts(
        db,
        lead_id=lead_id,
        organization_id=organization_id,
    )


@router.get(
    "/leads/{lead_id}/report",
    response_model=CrmPropertyReportResponse,
    dependencies=EXPENSIVE_LANE,
)
async def crm_property_report(
    request: Request,
    lead_id: str,
    as_of: date | None = Query(default=None),
    context: AuthContext = Depends(require_active_subscription),
):
    """Build a one-year property report with sales, rentals, and indicative analysis."""
    return await _until_disconnect(request, get_property_report(lead_id, as_of=as_of))


@router.get("/workspaces", response_model=CrmWorkspacePage, dependencies=LIGHT_LANE)
async def crm_workspaces(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """One page of the current agent's persisted CRM state, newest first, with the total."""
    user_id, organization_id = _auth_ids(context)
    return await list_lead_workspaces(
        db,
        user_id=user_id,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/workspaces/{lead_id}",
    response_model=CrmWorkspaceResponse,
    dependencies=LIGHT_LANE,
)
async def crm_lead_workspace(
    lead_id: str,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Return status, contact enrichment, follow-up, tags, and notes for one lead."""
    user_id, organization_id = _auth_ids(context)
    return await get_lead_workspace(
        db,
        lead_id=lead_id,
        user_id=user_id,
        organization_id=organization_id,
    )


@router.patch("/workspaces/{lead_id}", response_model=CrmWorkspaceResponse, dependencies=LIGHT_LANE)
async def crm_update_workspace(
    lead_id: str,
    payload: CrmWorkspaceUpdate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Persist the current agent's working state for one lead."""
    user_id, organization_id = _auth_ids(context)
    return await update_lead_workspace(
        db,
        lead_id=lead_id,
        payload=payload,
        user_id=user_id,
        organization_id=organization_id,
    )


@router.post(
    "/workspaces/{lead_id}/notes", response_model=CrmWorkspaceResponse, dependencies=LIGHT_LANE
)
async def crm_add_note(
    lead_id: str,
    payload: CrmNoteCreate,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Add a timestamped agent note and return the refreshed workspace."""
    user_id, organization_id = _auth_ids(context)
    return await add_lead_note(
        db,
        lead_id=lead_id,
        payload=payload,
        user_id=user_id,
        organization_id=organization_id,
    )


@router.delete("/notes/{note_id}", status_code=204, dependencies=LIGHT_LANE)
async def crm_delete_note(
    note_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Delete one note owned by the current user and organization."""
    user_id, organization_id = _auth_ids(context)
    await delete_lead_note(
        db,
        note_id=note_id,
        user_id=user_id,
        organization_id=organization_id,
    )
    return Response(status_code=204)


@router.get(
    "/saved-leads",
    response_model=list[CrmSavedLeadResponse],
    dependencies=LIGHT_LANE,
)
async def crm_saved_leads(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """List saved CRM prospects for the current user and organization."""
    user_id, organization_id = _auth_ids(context)
    return await list_saved_leads(
        db,
        user_id=user_id,
        organization_id=organization_id,
    )


@router.post(
    "/saved-leads/{lead_id}",
    response_model=CrmSavedLeadResponse,
    status_code=201,
    dependencies=EXPENSIVE_LANE,
)
async def crm_save_lead(
    lead_id: str,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Save or refresh a CRM prospect for the current user."""
    user_id, organization_id = _auth_ids(context)
    return await save_lead(
        db,
        lead_id=lead_id,
        user_id=user_id,
        organization_id=organization_id,
    )


@router.delete("/saved-leads/{saved_id}", status_code=204, dependencies=LIGHT_LANE)
async def crm_delete_saved_lead(
    saved_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Remove a prospect from the current user's saved list."""
    user_id, organization_id = _auth_ids(context)
    await delete_saved_lead(
        db,
        saved_id=saved_id,
        user_id=user_id,
        organization_id=organization_id,
    )
    return Response(status_code=204)
