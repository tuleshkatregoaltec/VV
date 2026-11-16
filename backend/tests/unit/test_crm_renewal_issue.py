"""Issuing renewal units to agents: each unit becomes one lead, routed like a Leads import."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.crm import renewal_issue
from app.crm.renewal_issue import RenewalIssueRequest

ORG = "org-1"
MANAGER = "manager-1"


def _detail(lease_id: str, unit: str | None = "101"):
    return SimpleNamespace(
        lead=SimpleNamespace(
            lead_id=lease_id, unit_number=unit, unit_candidate_key=f"key-{lease_id}"
        )
    )


def _enquiry(enquiry_id: int, *, assigned: str | None = None, pooled: bool = False):
    return SimpleNamespace(
        id=enquiry_id,
        organization_id=ORG,
        contact_id=enquiry_id,
        assigned_user_id=assigned,
        pool_released_at=object() if pooled else None,
    )


@pytest.fixture
def wired(monkeypatch):
    """Replace the warehouse, the lead store and the assignment step; return the fakes."""
    enquiries: dict[int, SimpleNamespace] = {}
    leases: dict[str, SimpleNamespace | None] = {}
    opened_for: dict[str, int] = {}
    assigned: dict = {}

    async def details(lease_ids):
        return [leases.get(lease_id) for lease_id in lease_ids]

    async def open_lead(db, *, detail, owner, user_id, organization_id):
        return SimpleNamespace(id=opened_for[detail.lead.lead_id])

    async def assign(db, routed, outcome, organization_id, user_id, import_id, pool_team):
        assigned["routed"] = routed
        assigned["import_id"] = import_id
        outcome.assigned = sum(1 for _, target, *_ in routed if target)

    monkeypatch.setattr(
        renewal_issue.inbound_imports, "_resolve_policy", AsyncMock(return_value=("team-1", []))
    )
    monkeypatch.setattr(renewal_issue, "_details", details)
    monkeypatch.setattr(renewal_issue, "_owners_by_candidate", AsyncMock(return_value={}))
    monkeypatch.setattr(renewal_issue, "open_lead_from_detail", open_lead)
    monkeypatch.setattr(
        renewal_issue.inbound_repository,
        "get_crm_inbound_enquiry",
        AsyncMock(side_effect=lambda db, key: enquiries.get(key)),
    )
    monkeypatch.setattr(
        renewal_issue.inbound_repository, "get_crm_inbound_contact", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(renewal_issue.inbound_repository, "save", MagicMock())
    monkeypatch.setattr(renewal_issue.inbound_imports, "_assign_imported", assign)
    return SimpleNamespace(
        enquiries=enquiries, leases=leases, opened_for=opened_for, assigned=assigned
    )


def _request(lease_ids, **assignment):
    return RenewalIssueRequest(lease_ids=lease_ids, assignment=assignment or {"mode": "unassigned"})


async def _issue(request):
    db = SimpleNamespace(commit=AsyncMock())
    result = await renewal_issue.issue_renewal_leads(
        db, request=request, user_id=MANAGER, organization_id=ORG
    )
    db.commit.assert_awaited_once()
    return result


async def test_units_go_to_the_chosen_agent(wired):
    for n, lease in enumerate(["a", "b"], start=1):
        wired.leases[lease] = _detail(lease)
        wired.opened_for[lease] = n
        wired.enquiries[n] = _enquiry(n)

    result = await _issue(_request(["a", "b"], mode="agent", assignee_user_id="agent-7"))

    assert result.issued == 2
    assert result.enquiry_ids == [1, 2]
    assert [target for _, target, *_ in wired.assigned["routed"]] == ["agent-7", "agent-7"]
    # Renewal issues are not file imports.
    assert wired.assigned["import_id"] is None


async def test_leads_someone_already_holds_are_left_alone(wired):
    for n, lease in enumerate(["held", "pooled", "free"], start=1):
        wired.leases[lease] = _detail(lease)
        wired.opened_for[lease] = n
    wired.enquiries[1] = _enquiry(1, assigned="agent-2")
    wired.enquiries[2] = _enquiry(2, pooled=True)
    wired.enquiries[3] = _enquiry(3)

    result = await _issue(
        _request(["held", "pooled", "free"], mode="agent", assignee_user_id="agent-7")
    )

    assert result.already_assigned == 2
    assert result.issued == 1
    assert [enquiry.id for enquiry, *_ in wired.assigned["routed"]] == [3]


async def test_units_without_a_lease_or_unit_number_are_skipped(wired):
    wired.leases["gone"] = None
    wired.leases["no-unit"] = _detail("no-unit", unit=None)
    wired.leases["ok"] = _detail("ok")
    wired.opened_for["ok"] = 5
    wired.enquiries[5] = _enquiry(5)

    result = await _issue(_request(["gone", "no-unit", "ok", "ok"]))

    assert result.requested == 3  # the repeated id counts once
    assert result.skipped == 2
    assert result.issued == 1


async def test_two_leases_of_one_unit_route_its_lead_once(wired):
    wired.leases["old"] = _detail("old")
    wired.leases["new"] = _detail("new")
    wired.opened_for.update(old=9, new=9)
    wired.enquiries[9] = _enquiry(9)

    result = await _issue(_request(["old", "new"], mode="team"))

    assert result.issued == 1
    assert len(wired.assigned["routed"]) == 1


async def test_a_refused_policy_creates_no_leads(wired, monkeypatch):
    wired.leases["a"] = _detail("a")
    monkeypatch.setattr(
        renewal_issue.inbound_imports,
        "_resolve_policy",
        AsyncMock(side_effect=HTTPException(status_code=403, detail="Only managers can assign")),
    )
    opened = AsyncMock()
    monkeypatch.setattr(renewal_issue, "open_lead_from_detail", opened)

    with pytest.raises(HTTPException):
        await _issue(_request(["a"], mode="team"))
    opened.assert_not_awaited()


def test_the_batch_is_bounded():
    with pytest.raises(ValidationError):
        RenewalIssueRequest(
            lease_ids=[str(n) for n in range(renewal_issue.MAX_RENEWAL_ISSUE + 1)],
            assignment={"mode": "unassigned"},
        )
    with pytest.raises(ValidationError):
        RenewalIssueRequest(lease_ids=[], assignment={"mode": "unassigned"})
