"""Builders for CRM Assistant unit tests: leads as the Leads page returns them."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException

from app.crm.assistant.deps import AssistantDeps
from app.crm.inbound_models import (
    CrmInboundEnquiry,
    InboundActivityResponse,
    InboundContactResponse,
    InboundEnquiryListResponse,
    InboundEnquiryResponse,
    InboundNoteResponse,
)

ORG_A = "org-a"
ORG_B = "org-b"
USER = "user-1"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)


def make_lead(
    lead_id: int = 1,
    *,
    name: str = "Ahmed Khan",
    status: str = "contacted",
    intent: str = "buy",
    assigned_user_id: str | None = None,
    next_follow_up: date | None = None,
    phone: str | None = "+971501234567",
    email: str | None = "ahmed@example.com",
    do_not_contact: bool = False,
    consent_status: str = "provided",
    raw_notes: str | None = None,
    notes: list[str] | None = None,
    criteria: dict | None = None,
) -> InboundEnquiryResponse:
    return InboundEnquiryResponse(
        id=lead_id,
        contact=InboundContactResponse(
            id=lead_id,
            full_name=name,
            phone=phone,
            email=email,
            consent_status=consent_status,
            do_not_contact=do_not_contact,
        ),
        record_kind="opportunity",
        intent=intent,
        status=status,
        assigned_user_id=assigned_user_id,
        source="Manual",
        enquiry_date=NOW,
        criteria=criteria
        if criteria is not None
        else {"locations": ["JVC"], "budget_max_aed": 2_000_000, "bedrooms_min": 2},
        strict_fields=[],
        raw_notes=raw_notes,
        observed_data={},
        inferred_data={},
        confirmed_data={},
        qualification={},
        extraction_confidence=1.0,
        review_reasons=[],
        next_follow_up=next_follow_up,
        sla_state="responded",
        qualification_complete=False,
        tags=[],
        notes=[
            InboundNoteResponse(id=i, body=body, user_id=USER, created_at=NOW)
            for i, body in enumerate(notes or [], start=1)
        ],
        activities=[
            InboundActivityResponse(id=1, activity_type="call", user_id=USER, created_at=NOW)
        ],
        created_at=NOW,
        updated_at=NOW,
    )


def make_row(lead_id: int = 1, *, organization_id: str = ORG_A, intent: str = "buy"):
    return CrmInboundEnquiry(
        id=lead_id,
        organization_id=organization_id,
        contact_id=lead_id,
        created_by_user_id=USER,
        intent=intent,
        status="contacted",
        enquiry_date=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def list_response(leads: list[InboundEnquiryResponse]) -> InboundEnquiryListResponse:
    return InboundEnquiryListResponse(enquiries=leads, total=len(leads), summary={})


def make_deps(organization_id: str = ORG_A, user_id: str = USER, db=None) -> AssistantDeps:
    return AssistantDeps(
        db=db,
        user_id=user_id,
        organization_id=organization_id,
        organization_name="Acme Realty",
        role="member",
        organization=SimpleNamespace(id=organization_id, name="Acme Realty"),
    )


def ctx(deps: AssistantDeps):
    # Tools only read ctx.deps; a full RunContext needs a model and is not what is under test.
    return SimpleNamespace(deps=deps)


class FakeLeads:
    """Org-scoped stand-in for the inbound store: rows by id, responses by id."""

    def __init__(self):
        self.lease_items = []
        self.lease_calls = []
        self.rows: dict[int, CrmInboundEnquiry] = {}
        self.responses: dict[int, InboundEnquiryResponse] = {}

    def add(self, response: InboundEnquiryResponse, organization_id: str = ORG_A):
        self.rows[response.id] = make_row(
            response.id, organization_id=organization_id, intent=response.intent
        )
        self.responses[response.id] = response

    async def get_row(self, db, key):
        return self.rows.get(key)

    async def get_response(self, db, enquiry_id, organization_id):
        row = self.rows.get(enquiry_id)
        if not row or row.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Inbound enquiry not found")
        return self.responses[enquiry_id]

    lease_items: list = []
    lease_calls: list = []

    async def lease_leads(self, db, *, user_id, organization_id, limit, offset, **kwargs):
        self.lease_calls.append((user_id, organization_id))
        return SimpleNamespace(items=list(self.lease_items))

    async def list(self, db, *, organization_id, leads_only, limit, **kwargs):
        assert leads_only is True
        items = [
            self.responses[i]
            for i, row in self.rows.items()
            if row.organization_id == organization_id
        ]
        return list_response(items[:limit])


class FakeSession:
    """Records what a tool adds and whether it committed; no database behind it."""

    def __init__(self):
        self.added: list = []
        self.commits = 0

    def add(self, record):
        self.added.append(record)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.added.clear()

    def of_type(self, cls):
        return [item for item in self.added if isinstance(item, cls)]


def lease_item(
    lease_id="L-1",
    *,
    building="Al Khail Heights 10a-10b",
    unit="312",
    area="Al Barsha",
    owner_name=None,
    lead_record_id=None,
):
    """A Vitevue lease lead as /renewal-leads returns it (only the fields the assistant reads)."""
    lead = SimpleNamespace(
        lead_id=lease_id,
        building_name=building,
        project_name="",
        area_name=area,
        unit_number=unit,
        property_type="Unit",
        property_subtype="Apartment",
        bedrooms="2 B/R",
        annual_rent_aed=85_000,
        lease_end=date(2026, 10, 1),
        days_to_expiry=-29,
    )
    owner = SimpleNamespace(name=owner_name) if owner_name else None
    return SimpleNamespace(lead=lead, owner=owner, lead_record_id=lead_record_id)
