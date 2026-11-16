"""Issuing owners from an owner sheet: one outbound lead per owner, routed like a Leads import."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.crm import owner_issue
from app.crm.inbound_models import OWNER_OUTBOUND_SOURCE
from app.crm.owner_issue import OwnerIssueRequest

ORG = "org-1"
MANAGER = "manager-1"


def _row(claim_id: int, owner: str | None, *, phone: str | None = "+971500000000"):
    return SimpleNamespace(
        id=claim_id,
        owner_key=owner,
        contact_name=f"Owner {claim_id}",
        phone_primary=phone,
        phone_alternate=None,
        email_primary=None,
        area_name="JVC",
        project_name="",
        building_name="Tower A",
        unit_number=str(100 + claim_id),
        property_type="Apartment",
        ownership_status="verified_current_owner",
    )


class FakeDb:
    def __init__(self):
        self.commit = AsyncMock()
        self.flush = AsyncMock(side_effect=self._ids)
        self.pending: list = []
        self._next = 1

    async def _ids(self):
        for item in self.pending:
            if getattr(item, "id", None) is None:
                item.id = self._next
                self._next += 1


@pytest.fixture
def wired(monkeypatch):
    state = SimpleNamespace(rows=[], remaining=0, existing={}, routed=None, saved=[])
    db = FakeDb()

    def save(_db, item):
        db.pending.append(item)
        state.saved.append(item)

    async def owners(db_, list_id, organization_id, request):
        return state.rows, state.remaining

    async def assign(db_, routed, outcome, organization_id, user_id, import_id, pool_team):
        state.routed = routed
        outcome.assigned = sum(1 for _, target, *_ in routed if target)

    monkeypatch.setattr(
        owner_issue.owner_repository,
        "get_contact_list",
        AsyncMock(return_value=SimpleNamespace(id=7, name="Marina owners")),
    )
    monkeypatch.setattr(
        owner_issue.inbound_imports, "_resolve_policy", AsyncMock(return_value=("team-1", []))
    )
    monkeypatch.setattr(owner_issue, "_owners", owners)
    monkeypatch.setattr(owner_issue, "_existing", AsyncMock(side_effect=lambda *a: state.existing))
    monkeypatch.setattr(owner_issue.inbound_repository, "save", MagicMock(side_effect=save))
    monkeypatch.setattr(
        owner_issue.inbound_repository, "get_crm_inbound_contact", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(owner_issue.inbound_imports, "_assign_imported", assign)
    state.db = db
    return state


async def _issue(state, **assignment):
    request = OwnerIssueRequest(assignment=assignment or {"mode": "unassigned"})
    result = await owner_issue.issue_owner_leads(
        state.db, list_id=7, request=request, user_id=MANAGER, organization_id=ORG
    )
    state.db.commit.assert_awaited_once()
    return result


async def test_each_owner_becomes_one_outbound_lead_for_the_agent(wired):
    wired.rows = [_row(1, "owner-a"), _row(2, "owner-a"), _row(3, "owner-b")]
    wired.remaining = 40

    result = await _issue(wired, mode="agent", assignee_user_id="agent-7")

    leads = [enquiry for enquiry, *_ in wired.routed]
    assert [lead.source_lead_id for lead in leads] == ["owner-a", "owner-b"]
    assert {lead.source for lead in leads} == {OWNER_OUTBOUND_SOURCE}
    assert leads[0].campaign == "Marina owners"
    assert leads[0].criteria["locations"] == ["JVC"]
    assert [target for _, target, *_ in wired.routed] == ["agent-7", "agent-7"]
    assert result.issued == 2
    assert result.remaining == 40
    # The next batch starts after the three rows read here.
    assert result.next_offset == 3


async def test_owners_with_no_way_to_contact_are_skipped(wired):
    wired.rows = [_row(1, "owner-a", phone=None), _row(2, "owner-b")]

    result = await _issue(wired)

    assert result.skipped == 1
    assert result.issued == 1


async def test_an_issued_owner_keeps_their_lead_and_a_held_one_is_left_alone(wired):
    free = SimpleNamespace(id=50, contact_id=5, assigned_user_id=None, pool_released_at=None)
    held = SimpleNamespace(id=51, contact_id=6, assigned_user_id="agent-2", pool_released_at=None)
    wired.rows = [_row(1, "owner-a"), _row(2, "owner-b")]
    wired.existing = {"owner-a": free, "owner-b": held}

    result = await _issue(wired, mode="team")

    assert result.already_assigned == 1
    assert [enquiry.id for enquiry, *_ in wired.routed] == [50]
    # No new lead was created for either owner.
    assert not [item for item in wired.saved if type(item).__name__ == "CrmInboundEnquiry"]


async def test_rows_without_an_owner_key_are_keyed_by_their_row(wired):
    wired.rows = [_row(9, None)]

    await _issue(wired)

    assert wired.routed[0][0].source_lead_id == "claim:9"


async def test_an_unknown_sheet_is_refused_before_anything_is_written(wired, monkeypatch):
    monkeypatch.setattr(
        owner_issue.owner_repository, "get_contact_list", AsyncMock(return_value=None)
    )
    with pytest.raises(HTTPException) as error:
        await _issue(wired)
    assert error.value.status_code == 404
    assert wired.saved == []


def test_the_batch_is_bounded():
    with pytest.raises(ValidationError):
        OwnerIssueRequest(
            claim_ids=list(range(owner_issue.MAX_OWNER_ISSUE + 1)),
            assignment={"mode": "unassigned"},
        )
    with pytest.raises(ValidationError):
        OwnerIssueRequest(limit=owner_issue.MAX_OWNER_ISSUE + 1, assignment={"mode": "unassigned"})
