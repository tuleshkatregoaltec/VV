from types import SimpleNamespace

import pytest

from app.organization import service
from app.organization.models import (
    Organization,
    OrganizationMembership,
    OwnerOrganizationCreateRequest,
)


class FakeDB:
    async def commit(self):
        pass

    async def refresh(self, model):
        pass

    async def rollback(self):
        pass


@pytest.mark.asyncio
async def test_owner_create_retry_cannot_raise_paid_seat_limit(monkeypatch):
    """Re-calling /organization/create must not rewrite max_users after payment."""
    org = Organization(id="org-1", name="Acme", max_users=3, subscription_status="active")
    membership = OrganizationMembership(organization_id="org-1", user_id="u1", role="owner")

    async def fake_membership(db, user_id):
        return membership

    async def fake_get_org(db, org_id):
        return org

    monkeypatch.setattr(service, "get_membership_for_user", fake_membership)
    monkeypatch.setattr(service.repository, "get_organization_by_id", fake_get_org)
    monkeypatch.setattr(service.repository, "save_organization", lambda db, o: None)

    result = await service.create_owner_organization(
        OwnerOrganizationCreateRequest(name="Acme 2", max_users=1000),
        SimpleNamespace(id="u1"),
        FakeDB(),
    )

    assert org.max_users == 3
    assert result.max_users == 3
    assert org.name == "Acme 2"


@pytest.mark.asyncio
async def test_owner_create_new_org_does_not_grant_requested_seats(monkeypatch):
    saved = []

    async def no_membership(db, user_id):
        return None

    monkeypatch.setattr(service, "get_membership_for_user", no_membership)
    monkeypatch.setattr(service.repository, "save_organization", lambda db, o: saved.append(o))
    monkeypatch.setattr(service.repository, "save_membership", lambda db, m: None)

    result = await service.create_owner_organization(
        OwnerOrganizationCreateRequest(name="Acme", max_users=1000),
        SimpleNamespace(id="u1"),
        FakeDB(),
    )

    assert saved[0].max_users == 1
    assert result.max_users == 1
