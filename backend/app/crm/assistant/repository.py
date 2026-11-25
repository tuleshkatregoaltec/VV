"""Private assistant reads. Model input never selects the user or organization."""

from sqlalchemy import and_, case, exists, func, literal_column, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.assistant_actions.models import AssistantListingDraft, AssistantReminder, AssistantViewing
from app.crm import deals
from app.crm.assignment import AssignmentScope, visible_clause
from app.crm.assistant.models import HANDLED_RESOURCES, CrmAssistantQuery
from app.crm.deal_models import CrmDeal
from app.crm.import_models import (
    CrmContactImport,
    CrmContactList,
    CrmOwnerNote,
    CrmOwnerWorkspace,
    CrmPropertyContactClaim,
)
from app.crm.inbound_models import (
    VITEVUE_LEASE_SOURCE,
    CrmInboundActivity,
    CrmInboundContact,
    CrmInboundEnquiry,
    CrmInboundNote,
)
from app.crm.models import CrmLeadNote, CrmLeadWorkspace, CrmSavedLead


def _location_matches(search: str):
    """A lead's stored criteria.locations (a list of names, or one name) contains `search`.

    Only that key is read, never the rest of the criteria, notes or other JSON. Other shapes
    (missing, null, objects) match nothing rather than raising.
    """
    locations = CrmInboundEnquiry.criteria["locations"]
    kind = func.json_typeof(locations)
    names = func.json_array_elements_text(
        case((kind == "array", locations), else_=literal_column("'[]'::json"))
    ).table_valued("value")
    in_list = exists(
        select(1).select_from(names).where(names.c.value.icontains(search, autoescape=True))
    )
    single = and_(kind == "string", locations.as_string().icontains(search, autoescape=True))
    return or_(in_list, single)


def _records(
    request: CrmAssistantQuery,
    scope: AssignmentScope,
    *,
    handler_ids: frozenset[str] | None = None,
    team_ids: frozenset[str] | None = None,
):
    """`handler_ids`/`team_ids` are the server's resolution of the handled_by/team names; they
    only ever narrow the role's own visibility clause."""
    user_id, organization_id = scope.user_id, scope.organization_id
    resource = request.resource
    if resource in {"reminders", "viewings", "listing_drafts"}:
        model = {
            "reminders": AssistantReminder,
            "viewings": AssistantViewing,
            "listing_drafts": AssistantListingDraft,
        }[resource]
        columns = [model.id, model.title, model.updated_at]
        if resource == "reminders":
            columns += [model.lead_id, model.due_at]
        elif resource == "viewings":
            columns += [model.lead_id, model.starts_at, model.ends_at, model.location]
        else:
            columns += [model.description, model.price_aed, model.location]
        statement = select(*columns).where(model.user_id == user_id)
        if resource != "listing_drafts":
            accessible = (
                select(CrmInboundEnquiry.id)
                .join(CrmInboundContact, CrmInboundContact.id == CrmInboundEnquiry.contact_id)
                .where(
                    CrmInboundEnquiry.organization_id == organization_id,
                    CrmInboundContact.organization_id == organization_id,
                    visible_clause(scope),
                )
            )
            statement = statement.where(or_(model.lead_id.is_(None), model.lead_id.in_(accessible)))
        search_columns = [model.title]
        status = None
    elif resource in {"lead_notes", "lead_activities"}:
        model = CrmInboundNote if resource == "lead_notes" else CrmInboundActivity
        # Every author's entries on a visible lead, as on the CRM lead page.
        columns = [model.id, model.enquiry_id, model.user_id, model.body, model.created_at]
        if resource == "lead_activities":
            columns.append(model.activity_type)
        statement = (
            select(*columns)
            .join(CrmInboundEnquiry, CrmInboundEnquiry.id == model.enquiry_id)
            .join(CrmInboundContact, CrmInboundContact.id == CrmInboundEnquiry.contact_id)
            .where(
                CrmInboundEnquiry.organization_id == organization_id,
                CrmInboundContact.organization_id == organization_id,
                visible_clause(scope),
            )
        )
        search_columns = [model.body]
        status = None
    elif resource in {"workspace_notes", "owner_notes"}:
        model = CrmLeadNote if resource == "workspace_notes" else CrmOwnerNote
        parent = CrmLeadWorkspace if resource == "workspace_notes" else CrmOwnerWorkspace
        statement = (
            select(model.id, model.workspace_id, model.body, model.created_at)
            .join(parent, parent.id == model.workspace_id)
            .where(
                model.user_id == user_id,
                parent.user_id == user_id,
                parent.organization_id == organization_id,
            )
        )
        search_columns = [model.body]
        status = None
    elif resource in {"leads", "renewals"}:
        model = CrmInboundEnquiry
        columns = [
            model.id,
            model.status,
            model.intent,
            model.record_kind,
            model.source,
            model.criteria,
            model.next_follow_up,
            model.updated_at,
            model.assigned_user_id,
            model.team_id,
            model.pool_released_at,
            CrmInboundContact.full_name.label("contact_name"),
        ]
        if resource == "renewals":
            columns.append(model.source_lead_id)
        if request.include_contact_details:
            columns += [CrmInboundContact.phone, CrmInboundContact.email]
        statement = (
            select(*columns)
            .join(CrmInboundContact, CrmInboundContact.id == model.contact_id)
            .where(
                CrmInboundContact.organization_id == organization_id,
                visible_clause(scope),
            )
        )
        if resource == "renewals":
            statement = statement.where(
                model.source == VITEVUE_LEASE_SOURCE, model.source_lead_id.is_not(None)
            )
        search_columns = [CrmInboundContact.full_name, model.source]
        status = model.status
    elif resource == "deals":
        model = CrmDeal
        # The CRM's own deal visibility (crm/deals.py): own deals, supervised teams', or all.
        statement = select(
            model.id,
            model.deal_type,
            model.unit,
            model.client,
            model.value_aed,
            model.due_date,
            model.stage_index,
            model.status,
            model.lead_id,
            model.assigned_user_id,
            model.team_id,
            model.updated_at,
        ).where(deals.visible_clause(scope))
        search_columns = [model.unit, model.client]
        status = model.status
    elif resource == "owner_properties":
        model = CrmPropertyContactClaim
        columns = [
            model.id,
            model.contact_name,
            model.area_name,
            model.project_name,
            model.building_name,
            model.unit_number,
            model.property_type,
            model.ownership_status.label("status"),
            model.confidence_score,
            model.updated_at,
        ]
        if request.include_contact_details:
            columns += [model.phone_primary.label("phone"), model.email_primary.label("email")]
        statement = (
            select(*columns)
            .join(CrmContactImport, CrmContactImport.id == model.import_id)
            .join(CrmContactList, CrmContactList.id == model.list_id)
            .where(
                CrmContactImport.organization_id == organization_id,
                CrmContactImport.created_by_user_id == user_id,
                CrmContactList.organization_id == organization_id,
                CrmContactList.created_by_user_id == user_id,
                CrmContactList.source_import_id == CrmContactImport.id,
            )
        )
        search_columns = [
            model.contact_name,
            model.area_name,
            model.project_name,
            model.building_name,
        ]
        status = model.ownership_status
    elif resource in {"lead_workspaces", "owner_workspaces"}:
        model = CrmLeadWorkspace if resource == "lead_workspaces" else CrmOwnerWorkspace
        key = model.lead_id if resource == "lead_workspaces" else model.owner_key
        statement = select(
            model.id,
            key,
            model.pipeline_status.label("status"),
            model.next_follow_up,
            model.tags,
            model.updated_at,
        ).where(model.user_id == user_id)
        search_columns = [key]
        status = model.pipeline_status
    elif resource == "saved_leads":
        model = CrmSavedLead
        statement = select(model.id, model.lead_id, model.created_at, model.updated_at).where(
            model.user_id == user_id
        )
        search_columns = [model.lead_id]
        status = None
    else:
        raise ValueError("Resource has no persisted assistant records")

    statement = statement.where(model.organization_id == organization_id)
    if resource in HANDLED_RESOURCES:
        if request.assignment == "mine":
            statement = statement.where(model.assigned_user_id == user_id)
        elif request.assignment == "colleagues":
            statement = statement.where(
                model.assigned_user_id.is_not(None), model.assigned_user_id != user_id
            )
        elif request.assignment == "unassigned":
            statement = statement.where(model.assigned_user_id.is_(None))
        if handler_ids is not None:
            statement = statement.where(model.assigned_user_id.in_(sorted(handler_ids)))
        if team_ids is not None:
            statement = statement.where(model.team_id.in_(sorted(team_ids)))
    if request.record_id is not None:
        statement = statement.where(model.id == request.record_id)
    if request.search:
        matches = [column.icontains(request.search, autoescape=True) for column in search_columns]
        if resource in {"leads", "renewals"}:
            matches.append(_location_matches(request.search))
        statement = statement.where(or_(*matches))
    if request.status:
        statement = statement.where(status == request.status)
    if request.follow_up_before:
        statement = statement.where(model.next_follow_up <= request.follow_up_before)
    return statement, model, status is not None


async def query_records(
    db: AsyncSession, request: CrmAssistantQuery, *, scope: AssignmentScope, **narrowing
) -> tuple[int, dict[str, int], list[dict]]:
    """Leads and deals follow the caller's CRM role; other resources stay the caller's own."""
    statement, model, has_status = _records(request, scope, **narrowing)
    scoped = statement.subquery()
    total = (await db.exec(select(func.count()).select_from(scoped))).one()
    counts = {}
    if has_status:
        grouped = await db.execute(select(scoped.c.status, func.count()).group_by(scoped.c.status))
        counts = {str(status): int(count) for status, count in grouped}
    rows = []
    if not request.summary_only:
        result = await db.execute(
            statement.order_by(
                (
                    getattr(model, "updated_at", None)
                    if hasattr(model, "updated_at")
                    else model.created_at
                ).desc(),
                model.id,
            )
            .limit(request.limit)
            .offset(request.offset)
        )
        rows = [dict(row) for row in result.mappings()]
    return int(total), counts, rows


async def lead_breakdowns(
    db: AsyncSession, request: CrmAssistantQuery, *, scope: AssignmentScope, **narrowing
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Counts by record kind, intent and assignment over exactly the matches `query_records`
    totals. Assignment buckets use the same conditions as the `assignment` filter."""
    if request.resource not in {"leads", "renewals"}:
        raise ValueError("Only leads and renewals store a record kind, intent and assignee")
    scoped = _records(request, scope, **narrowing)[0].subquery()
    holder = scoped.c.assigned_user_id
    assignment = case(
        (holder.is_(None), "unassigned"),
        (holder == scope.user_id, "mine"),
        else_="colleagues",
    )
    counts = []
    for column in (scoped.c.record_kind, scoped.c.intent, assignment):
        grouped = await db.execute(select(column, func.count()).group_by(column))
        counts.append({str(value): int(count) for value, count in grouped})
    return counts[0], counts[1], counts[2]


async def holder_breakdowns(
    db: AsyncSession, request: CrmAssistantQuery, *, scope: AssignmentScope, **narrowing
) -> tuple[dict[str | None, int], dict[str | None, int]]:
    """Counts by owning team id and by handler id over exactly the matches `query_records`
    totals (None: no team / unassigned). The caller turns ids into names."""
    if request.resource not in HANDLED_RESOURCES:
        raise ValueError("Only leads, renewals and deals have a handler and team")
    scoped = _records(request, scope, **narrowing)[0].subquery()
    counts = []
    for column in (scoped.c.team_id, scoped.c.assigned_user_id):
        grouped = await db.execute(select(column, func.count()).group_by(column))
        counts.append({value: int(count) for value, count in grouped})
    return counts[0], counts[1]


async def has_current_access(db: AsyncSession, *, user_id: str, organization_id: str) -> bool:
    """Scalar read bypasses stale ORM identity-map membership/subscription objects."""
    from app.organization.models import Organization, OrganizationMembership

    result = await db.exec(
        select(OrganizationMembership.id)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == organization_id,
            Organization.subscription_status.in_(("active", "trialing")),
        )
    )
    return result.first() is not None
