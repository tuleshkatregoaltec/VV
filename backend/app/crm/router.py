import json
from datetime import date
from typing import Literal
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.dependencies import AuthContext, require_active_owner, require_active_subscription
from app.crm.company_listings import (
    clear_company_source,
    list_company_listings,
    select_company_source,
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
    CrmWorkspaceResponse,
    CrmWorkspaceSummary,
    CrmWorkspaceUpdate,
)
from app.crm.opportunities import get_dashboard
from app.crm.owner_history import get_owner_history, get_owner_history_summary
from app.crm.owners import (
    get_contact_list,
    get_owner_profile,
    get_owner_registry,
    list_contact_lists,
    list_lead_imported_contacts,
)
from app.crm.recently_sold import approve_recent_seller
from app.crm.renewal_leads import (
    get_area_preferences,
    get_renewal_detail,
    list_renewal_areas,
    list_renewal_leads,
    list_renewals,
    open_renewal_lead,
    until_disconnected,
    update_area_preferences,
)
from app.crm.reports import get_property_report
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
    _, organization_id = _auth_ids(context)
    return await list_inbound_enquiries(
        db,
        organization_id=organization_id,
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
    _, organization_id = _auth_ids(context)
    return await get_inbound_enquiry(db, enquiry_id, organization_id)


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
    _, organization_id = _auth_ids(context)
    return await get_inbound_matches(db, enquiry_id, organization_id)


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
    _, organization_id = _auth_ids(context)
    return await refresh_inbound_matches(
        db,
        enquiry_id=enquiry_id,
        organization_id=organization_id,
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
    _, organization_id = _auth_ids(context)
    return await update_inbound_match_state(
        db, match_id=match_id, organization_id=organization_id, state=payload.state
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
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Normalize a campaign or CRM lead export into actionable enquiries."""
    user_id, organization_id = _auth_ids(context)
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
    )


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
    _, organization_id = _auth_ids(context)
    return await list_inbound_imports(db, organization_id)


@router.delete("/inbound/imports/{import_id}", status_code=204, dependencies=EXPENSIVE_LANE)
async def crm_delete_inbound_import(
    import_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    _, organization_id = _auth_ids(context)
    await delete_inbound_import(db, import_id, organization_id)
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
    """Upload, normalize, verify, and publish an owner-contact workbook."""
    user_id, organization_id = _auth_ids(context)
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
    context: AuthContext = Depends(require_active_subscription),
):
    """Assets › Renewals: every lease in the dataset, narrowed by the tab's filters."""
    return await _until_disconnect(
        request,
        list_renewals(
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
    kind: str | None = Query(default=None, pattern="^(vacant|upcoming)$"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    as_of: date | None = Query(default=None),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Return lease-expiry leads in the current agent's areas and windows.

    kind=vacant: units whose lease ended with no later lease registered (Leads › Vacant units).
    kind=upcoming: leases still running (the Inbox).
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


@router.get("/workspaces", response_model=list[CrmWorkspaceSummary], dependencies=LIGHT_LANE)
async def crm_workspaces(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """List the current agent's persisted CRM state for queue decoration."""
    user_id, organization_id = _auth_ids(context)
    return await list_lead_workspaces(
        db,
        user_id=user_id,
        organization_id=organization_id,
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
