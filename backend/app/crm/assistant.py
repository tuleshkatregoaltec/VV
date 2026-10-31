from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import assistant_repository
from app.crm.assistant_models import CrmAssistantQuery, CrmAssistantResult


async def query_my_records(
    db: AsyncSession, request: CrmAssistantQuery, *, user_id: str, organization_id: str
) -> CrmAssistantResult:
    if not user_id or not organization_id:
        raise ValueError("CRM assistant requires an authenticated user and organization")
    result = CrmAssistantResult(
        resource=request.resource, limit=request.limit, offset=request.offset
    )
    if request.resource in {"deals", "matches"}:
        result.available = False
        result.limitations = [
            "Deals are not persisted; matching reads may mutate shared records and are unavailable to the assistant."
        ]
        return result
    if not await has_current_access(db, user_id=user_id, organization_id=organization_id):
        raise PermissionError("Current organization access is required")
    (
        result.total,
        result.counts_by_status,
        result.records,
    ) = await assistant_repository.query_records(
        db, request, user_id=user_id, organization_id=organization_id
    )
    if request.resource == "renewals":
        from app.crm.opportunities import get_lead_detail

        for row in result.records:
            source_key = row.pop("source_lead_id", None)
            if request.record_id and source_key:
                try:
                    detail = await get_lead_detail(source_key)
                    row["renewal_evidence"] = detail.lead.model_dump(
                        mode="json",
                        include={
                            "building_name",
                            "project_name",
                            "area_name",
                            "bedrooms",
                            "size_sqft",
                            "annual_rent_aed",
                            "lease_start",
                            "lease_end",
                            "days_to_expiry",
                            "contract_state",
                            "data_complete_through",
                            "lease_evidence_state",
                            "match_confidence",
                            "lead_reason",
                        },
                    )
                except Exception:
                    row["renewal_evidence"] = {
                        "available": False,
                        "reason": "Current lease evidence is unavailable",
                    }
    result.limitations = [
        "Counts cover only your matching records, never the organization's entire CRM.",
        "Records are a paged selection; total and status counts cover all matches.",
    ]
    if request.resource == "renewals":
        result.limitations.append(
            "Only your currently accessible opened renewal leads are included. Use record_id for current lease evidence; no owner enrichment or shared matching refresh is performed."
        )
    if request.resource == "leads":
        result.limitations.append(
            "Visible leads are assigned to you, or unassigned and created by you. "
            "Notes and activities authored by other agents are not included."
        )
    if request.resource == "owner_properties":
        result.limitations.append(
            "These are property-contact claims from your own imports and lists. "
            "The total counts source claims, not distinct owners or verified current properties. "
            "Stored ownership assessments may be stale; they are not reverified by this read."
        )
    if request.resource in {"lead_workspaces", "owner_workspaces"}:
        result.limitations.append(
            "Workspace contact enrichment from shared owner data is not included."
        )
    return result


async def has_current_access(db: AsyncSession, *, user_id: str, organization_id: str) -> bool:
    return await assistant_repository.has_current_access(
        db, user_id=user_id, organization_id=organization_id
    )
