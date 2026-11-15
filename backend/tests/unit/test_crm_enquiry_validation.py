"""An enquiry can only be assigned to a member of its organization, and its free-form briefs
are bounded.

Live, create and patch stored any assigned_user_id (another tenant's user, or junk), and
criteria, confirmed_data and qualification were unbounded dicts.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.crm import inbound
from app.crm.inbound_models import InboundEnquiryCreate, InboundEnquiryUpdate


@pytest.mark.parametrize("field", ["criteria", "confirmed_data", "qualification"])
def test_a_brief_larger_than_the_bound_is_rejected(field):
    huge = {f"k{i}": "x" * 200 for i in range(200)}
    with pytest.raises(ValidationError):
        InboundEnquiryUpdate(**{field: huge})


def test_a_deeply_nested_brief_is_rejected():
    deep: dict = {}
    node = deep
    for _ in range(12):
        node["n"] = {}
        node = node["n"]
    with pytest.raises(ValidationError):
        InboundEnquiryCreate(full_name="A", criteria=deep)


def test_an_ordinary_brief_is_accepted():
    brief = {"locations": ["JVC", "Al Barsha"], "bedrooms_min": 2, "budget_max_aed": 1_500_000}
    assert InboundEnquiryCreate(full_name="A", criteria=brief).criteria == brief


async def test_assigning_a_user_outside_the_organization_is_refused(monkeypatch):
    monkeypatch.setattr(inbound, "get_membership_in_org", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as caught:
        await inbound._require_member(None, "org-1", "someone-else")
    assert caught.value.status_code == 422


async def test_assigning_a_member_is_allowed(monkeypatch):
    lookup = AsyncMock(return_value=SimpleNamespace(user_id="u-2"))
    monkeypatch.setattr(inbound, "get_membership_in_org", lookup)
    await inbound._require_member(None, "org-1", "u-2")
    lookup.assert_awaited_once_with(None, "org-1", "u-2")


async def test_create_checks_the_assignee(monkeypatch):
    check = AsyncMock(side_effect=HTTPException(status_code=422, detail="nope"))
    monkeypatch.setattr(inbound, "_require_member", check)
    with pytest.raises(HTTPException):
        await inbound.create_inbound_enquiry(
            None,
            payload=InboundEnquiryCreate(full_name="A", assigned_user_id="other"),
            user_id="u-1",
            organization_id="org-1",
        )
    check.assert_awaited_once_with(None, "org-1", "other")


async def test_update_checks_the_assignee(monkeypatch):
    enquiry = SimpleNamespace(organization_id="org-1")
    monkeypatch.setattr(
        inbound.inbound_repository, "get_crm_inbound_enquiry", AsyncMock(return_value=enquiry)
    )
    check = AsyncMock(side_effect=HTTPException(status_code=422, detail="nope"))
    monkeypatch.setattr(inbound, "_require_member", check)
    with pytest.raises(HTTPException):
        await inbound.update_inbound_enquiry(
            None,
            enquiry_id=1,
            organization_id="org-1",
            user_id="u-1",
            payload=InboundEnquiryUpdate(assigned_user_id="other"),
        )
    check.assert_awaited_once_with(None, "org-1", "other")
