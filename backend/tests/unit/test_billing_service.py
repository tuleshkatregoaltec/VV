from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.billing.service import create_checkout_session, sync_after_checkout
from app.organization.models import Organization, OrganizationMembership


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, organization=None, membership=None, execute_results=None):
        self.organization = organization
        self.membership = membership
        self.execute_results = list(execute_results or [])
        self.commit_count = 0
        self.refresh_count = 0
        self.rollback_count = 0

    async def get(self, model, key):
        return self.organization

    async def execute(self, stmt):
        if self.execute_results:
            return FakeScalarResult(self.execute_results.pop(0))
        return FakeScalarResult(self.membership)

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, model):
        self.refresh_count += 1

    async def rollback(self):
        self.rollback_count += 1


def make_org(**overrides):
    organization = Organization(
        id="org-1",
        name="Acme",
        max_users=5,
        subscription_status="none",
        stripe_customer_id=None,
    )
    for key, value in overrides.items():
        setattr(organization, key, value)
    return organization


def make_membership(role="owner"):
    return OrganizationMembership(
        organization_id="org-1",
        user_id="user-1",
        role=role,
    )


@pytest.mark.asyncio
async def test_create_checkout_session_requires_existing_organization():
    with pytest.raises(HTTPException) as exc:
        await create_checkout_session(
            user_id="user-1",
            email="owner@example.com",
            organization_id="missing-org",
            seats=5,
            first_name="Ada",
            last_name="Lovelace",
            price_tier="tier1",
            db=FakeDB(),
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_checkout_session_requires_owner_membership():
    org = make_org()

    with pytest.raises(HTTPException) as exc:
        await create_checkout_session(
            user_id="user-1",
            email="owner@example.com",
            organization_id=org.id,
            seats=5,
            first_name="Ada",
            last_name="Lovelace",
            price_tier="tier1",
            db=FakeDB(organization=org, execute_results=[None]),
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_checkout_session_marks_org_failed_when_price_config_is_invalid(monkeypatch):
    from app.billing import service

    org = make_org(stripe_customer_id="cus_existing")
    db = FakeDB(organization=org, execute_results=[make_membership()])

    monkeypatch.setattr(service.settings, "STRIPE_PRICE_ID_TIER1", "bad-price")
    monkeypatch.setattr(service.settings, "STRIPE_PRICE_ID_TIER2", "price_tier_2")

    with pytest.raises(HTTPException) as exc:
        await create_checkout_session(
            user_id="user-1",
            email="owner@example.com",
            organization_id=org.id,
            seats=7,
            first_name="Ada",
            last_name="Lovelace",
            price_tier="tier1",
            db=db,
        )

    assert exc.value.status_code == 500
    assert org.subscription_status == "failed"
    assert org.max_users == 5


@pytest.mark.asyncio
async def test_create_checkout_session_returns_checkout_session(monkeypatch):
    from app.billing import service

    org = make_org()
    db = FakeDB(organization=org, execute_results=[make_membership()])

    monkeypatch.setattr(service.settings, "STRIPE_PRICE_ID_TIER1", "price_tier_1")
    monkeypatch.setattr(service.settings, "STRIPE_PRICE_ID_TIER2", "price_tier_2")
    monkeypatch.setattr(
        service.stripe_gateway.stripe.Customer,
        "create",
        lambda **kwargs: SimpleNamespace(id="cus_123"),
    )
    monkeypatch.setattr(
        service.stripe_gateway.stripe.checkout.Session,
        "create",
        lambda **kwargs: SimpleNamespace(
            id="cs_test_123", url="https://checkout.stripe.test/session"
        ),
    )

    result = await create_checkout_session(
        user_id="user-1",
        email="owner@example.com",
        organization_id=org.id,
        seats=8,
        first_name="Ada",
        last_name="Lovelace",
        price_tier="tier1",
        db=db,
    )

    assert result["session_id"] == "cs_test_123"
    assert result["organization_id"] == org.id
    assert org.subscription_status == "pending"
    assert org.stripe_customer_id == "cus_123"
    assert org.max_users == 5


@pytest.mark.asyncio
async def test_sync_after_checkout_requires_completed_session(monkeypatch):
    from app.billing import service

    monkeypatch.setattr(
        service.stripe_gateway.stripe.checkout.Session,
        "retrieve",
        lambda session_id: SimpleNamespace(status="open", customer="cus_123"),
    )

    with pytest.raises(HTTPException) as exc:
        await sync_after_checkout("cs_test_123", "user-1", FakeDB())

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_sync_after_checkout_requires_owner(monkeypatch):
    from app.billing import service

    org = make_org(stripe_customer_id="cus_123")
    db = FakeDB(organization=org, execute_results=[org, None])

    monkeypatch.setattr(
        service.stripe_gateway.stripe.checkout.Session,
        "retrieve",
        lambda session_id: SimpleNamespace(status="complete", customer="cus_123"),
    )

    with pytest.raises(HTTPException) as exc:
        await sync_after_checkout("cs_test_123", "user-1", db)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_sync_after_checkout_returns_synced_state(monkeypatch):
    from app.billing import service

    org = make_org(stripe_customer_id="cus_123")
    db = FakeDB(organization=org, execute_results=[org, make_membership()])

    monkeypatch.setattr(
        service.stripe_gateway.stripe.checkout.Session,
        "retrieve",
        lambda session_id: SimpleNamespace(status="complete", customer="cus_123"),
    )

    async def fake_sync(customer_id, db):
        return {
            "status": "active",
            "organization_id": org.id,
            "seats": 8,
        }

    monkeypatch.setattr(service, "sync_stripe_to_postgres", fake_sync)

    result = await sync_after_checkout("cs_test_123", "user-1", db)

    assert result["status"] == "active"
    assert result["organization_id"] == org.id


@pytest.mark.asyncio
async def test_abandoned_checkout_does_not_grant_requested_seats(monkeypatch):
    """Seats are granted only by a Stripe sync, never by opening a checkout."""
    from app.billing import service

    org = make_org(max_users=1)
    db = FakeDB(organization=org, execute_results=[make_membership()])

    monkeypatch.setattr(service.settings, "STRIPE_PRICE_ID_TIER1", "price_tier_1")
    monkeypatch.setattr(
        service.stripe_gateway, "create_customer", lambda **kwargs: SimpleNamespace(id="cus_1")
    )
    sent = {}

    def fake_checkout(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(id="cs_1", url="https://checkout.stripe.test/s")

    monkeypatch.setattr(service.stripe_gateway, "create_checkout", fake_checkout)

    await create_checkout_session(
        user_id="user-1",
        email="owner@example.com",
        organization_id=org.id,
        seats=900,
        first_name="Ada",
        last_name="Lovelace",
        price_tier="tier1",
        db=db,
    )

    assert org.max_users == 1
    assert sent["line_items"][0]["quantity"] == 900


def test_checkout_request_caps_seats():
    from pydantic import ValidationError

    from app.billing.models import CheckoutSessionRequest

    CheckoutSessionRequest(organization_id="o", seats=1000, price_tier="tier1")
    for bad in (0, 1001, 10**9):
        with pytest.raises(ValidationError):
            CheckoutSessionRequest(organization_id="o", seats=bad, price_tier="tier1")


@pytest.mark.asyncio
async def test_stripe_sync_sets_max_users_from_paid_quantity(monkeypatch):
    from app.billing import service

    org = make_org(stripe_customer_id="cus_1", max_users=1)
    db = FakeDB(organization=org)

    async def fake_get_org(db_, customer_id):
        return org

    async def fake_get_sub(db_, stripe_id):
        return None

    monkeypatch.setattr(service.organization_service, "get_organization_by_customer", fake_get_org)
    monkeypatch.setattr(service.repository, "get_by_stripe_id", fake_get_sub)
    monkeypatch.setattr(service.repository, "save", lambda db_, sub: None)
    monkeypatch.setattr(service.settings, "STRIPE_PRICE_ID_TIER1", "price_tier_1")
    monkeypatch.setattr(service.settings, "STRIPE_PRICE_ID_TIER2", "price_tier_2")

    stripe_sub = SimpleNamespace(
        id="sub_1",
        status="active",
        created=1,
        cancel_at_period_end=False,
    )
    items = {
        "items": {
            "data": [
                {
                    "price": {"id": "price_tier_1"},
                    "quantity": 12,
                    "current_period_start": 1_700_000_000,
                    "current_period_end": 1_702_000_000,
                }
            ]
        }
    }
    stripe_sub = type("Sub", (dict,), {})(items)
    stripe_sub.id, stripe_sub.status, stripe_sub.created = "sub_1", "active", 1
    stripe_sub.cancel_at_period_end = False
    monkeypatch.setattr(
        service.stripe_gateway,
        "list_subscriptions",
        lambda **kwargs: SimpleNamespace(data=[stripe_sub]),
    )

    result = await service.sync_stripe_to_postgres("cus_1", db)

    assert org.max_users == 12
    assert result["seats"] == 12


SECRET = 'sk_live_SECRET relation "organizations" connection refused'


@pytest.mark.asyncio
async def test_checkout_errors_do_not_leak_exception_text(monkeypatch):
    from app.billing import service

    monkeypatch.setattr(service.settings, "STRIPE_PRICE_ID_TIER1", "price_tier_1")

    def boom(**kwargs):
        raise RuntimeError(SECRET)

    # customer creation failure
    org = make_org()
    monkeypatch.setattr(service.stripe_gateway, "create_customer", boom)
    with pytest.raises(HTTPException) as exc:
        await create_checkout_session(
            "user-1",
            "o@example.com",
            org.id,
            3,
            "Ada",
            "L",
            "tier1",
            FakeDB(organization=org, execute_results=[make_membership()]),
        )
    assert exc.value.status_code == 500
    assert "SECRET" not in str(exc.value.detail)

    # checkout creation failure
    org = make_org(stripe_customer_id="cus_1")
    monkeypatch.setattr(service.stripe_gateway, "create_checkout", boom)
    with pytest.raises(HTTPException) as exc:
        await create_checkout_session(
            "user-1",
            "o@example.com",
            org.id,
            3,
            "Ada",
            "L",
            "tier1",
            FakeDB(organization=org, execute_results=[make_membership()]),
        )
    assert "SECRET" not in str(exc.value.detail)

    # db commit failure linking the customer
    class FailingCommitDB(FakeDB):
        async def commit(self):
            raise RuntimeError(SECRET)

    org = make_org()
    monkeypatch.setattr(
        service.stripe_gateway, "create_customer", lambda **kwargs: SimpleNamespace(id="cus_2")
    )
    monkeypatch.setattr(service.stripe_gateway, "delete_customer", lambda cid: None)
    db = FailingCommitDB(organization=org, execute_results=[make_membership()])
    with pytest.raises(HTTPException) as exc:
        await create_checkout_session("user-1", "o@example.com", org.id, 3, "Ada", "L", "tier1", db)
    assert "SECRET" not in str(exc.value.detail)


@pytest.mark.asyncio
async def test_sync_after_checkout_invalid_session_does_not_leak(monkeypatch):
    from app.billing import service

    def boom(session_id):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(service.stripe_gateway, "retrieve_checkout", boom)
    with pytest.raises(HTTPException) as exc:
        await sync_after_checkout("cs_bad", "user-1", FakeDB())
    assert exc.value.status_code == 400
    assert "SECRET" not in str(exc.value.detail)
