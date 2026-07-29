from datetime import date

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.dependencies import AuthContext, require_active_subscription
from app.crm.import_models import (
    CrmContactImportResponse,
    CrmContactListDetail,
    CrmContactListSummary,
    CrmLeadImportedContact,
    CrmOwnerProfile,
    CrmOwnerRegistryResponse,
)
from app.crm.import_service import (
    get_contact_list,
    get_owner_profile,
    get_owner_registry,
    list_contact_imports,
    list_contact_lists,
    list_lead_imported_contacts,
    process_contact_import,
)
from app.crm.models import (
    CrmDashboardResponse,
    CrmLeadDetailResponse,
    CrmNoteCreate,
    CrmPropertyReportResponse,
    CrmSavedLeadResponse,
    CrmWorkspaceResponse,
    CrmWorkspaceSummary,
    CrmWorkspaceUpdate,
)
from app.crm.service import (
    add_lead_note,
    delete_lead_note,
    delete_saved_lead,
    get_dashboard,
    get_lead_detail,
    get_lead_workspace,
    get_property_report,
    list_lead_workspaces,
    list_saved_leads,
    save_lead,
    update_lead_workspace,
)
from app.postgres import get_db_session

router = APIRouter(prefix="/api/v1/crm", tags=["crm"])


def _auth_ids(auth: AuthContext) -> tuple[str, str]:
    return str(auth.user.id), str(auth.organization.id)


@router.post(
    "/contact-imports",
    response_model=CrmContactImportResponse,
    status_code=201,
)
async def crm_contact_import(
    file: UploadFile = File(...),
    name: str = Form(default="", max_length=200),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Upload, normalize, verify, and publish an owner-contact workbook."""
    user_id, organization_id = _auth_ids(context)
    return await process_contact_import(
        db,
        upload=file,
        name=name,
        user_id=user_id,
        organization_id=organization_id,
    )


@router.get(
    "/contact-imports",
    response_model=list[CrmContactImportResponse],
)
async def crm_contact_imports(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """List contact imports for the signed-in organization."""
    _, organization_id = _auth_ids(context)
    return await list_contact_imports(db, organization_id=organization_id)


@router.get(
    "/contact-lists",
    response_model=list[CrmContactListSummary],
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
)
async def crm_contact_list(
    list_id: int,
    status: str | None = Query(
        default=None,
        pattern=(
            "^(verified_current_owner|probable_current_owner|unit_linked_unverified|"
            "former_owner|conflicting_claim|unmatched)$"
        ),
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
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/owner-registry",
    response_model=CrmOwnerRegistryResponse,
)
async def crm_owner_registry(
    scope: str = Query(default="all", pattern="^(all|rental_ready|registry)$"),
    status: str | None = Query(
        default=None,
        pattern=(
            "^(verified_current_owner|probable_current_owner|unit_linked_unverified|"
            "former_owner|conflicting_claim|unmatched)$"
        ),
    ),
    search: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Return deduplicated owner profiles grouped into actionable CRM folders."""
    _, organization_id = _auth_ids(context)
    return await get_owner_registry(
        db,
        organization_id=organization_id,
        scope=scope,
        status=status,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/owners/{owner_key}",
    response_model=CrmOwnerProfile,
)
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


@router.get("/dashboard", response_model=CrmDashboardResponse)
async def crm_dashboard(
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
    return await get_dashboard(
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
    )


@router.get("/leads/{lead_id}", response_model=CrmLeadDetailResponse)
async def crm_lead_detail(
    lead_id: str,
    as_of: date | None = Query(default=None),
    context: AuthContext = Depends(require_active_subscription),
):
    """Return the evidence timeline and recommended action for one lead."""
    return await get_lead_detail(lead_id, as_of=as_of)


@router.get(
    "/leads/{lead_id}/contacts",
    response_model=list[CrmLeadImportedContact],
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


@router.get("/leads/{lead_id}/report", response_model=CrmPropertyReportResponse)
async def crm_property_report(
    lead_id: str,
    as_of: date | None = Query(default=None),
    context: AuthContext = Depends(require_active_subscription),
):
    """Build a one-year property report with sales, rentals, and indicative analysis."""
    return await get_property_report(lead_id, as_of=as_of)


@router.get("/workspaces", response_model=list[CrmWorkspaceSummary])
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


@router.get("/workspaces/{lead_id}", response_model=CrmWorkspaceResponse)
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


@router.patch("/workspaces/{lead_id}", response_model=CrmWorkspaceResponse)
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


@router.post("/workspaces/{lead_id}/notes", response_model=CrmWorkspaceResponse)
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


@router.delete("/notes/{note_id}", status_code=204)
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


@router.get("/saved-leads", response_model=list[CrmSavedLeadResponse])
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


@router.delete("/saved-leads/{saved_id}", status_code=204)
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
