from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.analytics.models import MarketMetricsResponse
from app.whatsapp import customer_access as access
from app.whatsapp.customer_evidence import (
    ListingSearch,
    MarketSummary,
    listing_evidence,
    market_evidence,
)
from app.whatsapp.customer_models import (
    PublishedListingCreate,
    WhatsAppConnection,
    WhatsAppPublishedListing,
)
from app.whatsapp.models import utcnow


def publication(**changes):
    return WhatsAppPublishedListing(
        id="public",
        connection_id="connection",
        title="Two bedroom home",
        location="Dubai Marina",
        property_type="apartment",
        transaction="sale",
        bedrooms=2,
        price_aed=2_000_000,
        availability="available",
        expires_at=utcnow() + timedelta(hours=1),
        **changes,
    )


def connection(**changes):
    return WhatsAppConnection(
        id="connection",
        user_id="broker",
        organization_id="org",
        phone_number_id="number",
        account_id="account",
        display_name="Broker",
        enabled=True,
        **changes,
    )


def market(count=20, coverage="partial", **changes):
    return MarketMetricsResponse(
        dataset="sales",
        period={
            "start": date(2026, 10, 1),
            "end": date(2026, 10, 31),
            "label": "October 2026",
            "type": "previous_month",
            "reference_date": date(2026, 11, 4),
            "timezone": "Asia/Dubai",
        },
        coverage={"status": coverage, "note": "Missing load evidence."},
        filters={},
        eligibility="Eligible canonical sales only.",
        definitions=[],
        total={"count": count, "values": {"median_aed": 2_000_000}},
        release_id="release-1",
        release_built_at="2026-11-03",
        limitations=["Area-level records are excluded."],
        **changes,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"approved_for_customer": False},
        {"expires_at": utcnow() - timedelta(seconds=1)},
        {"expires_at": utcnow() + timedelta(days=31)},
        {"expires_at": "2026-11-05T00:00:00"},
        {"owner_phone": "+971500000000"},
        {"user_id": "other"},
        {"price_aed": float("nan")},
    ],
)
def test_publication_requires_explicit_finite_approval_and_safe_fields(changes):
    data = publication().model_dump(
        exclude={"id", "connection_id", "revision", "revoked_at", "created_at", "updated_at"}
    )
    data.update(approved_for_customer=True)
    data.update(changes)
    with pytest.raises(ValidationError):
        PublishedListingCreate.model_validate(data)


@pytest.mark.parametrize(
    "extra",
    [
        {"user_id": "other"},
        {"sql": "select secret"},
        {"building": "unit 1"},
        {"period": "rolling_days"},
        {"limit": 1000},
    ],
)
def test_market_plan_has_no_identity_sql_unit_or_unbounded_query(extra):
    with pytest.raises(ValidationError):
        MarketSummary.model_validate({"operation": "market_summary", "dataset": "sales", **extra})


async def test_market_default_off_never_reaches_warehouse(monkeypatch):
    monkeypatch.setattr(access.repository, "connection", AsyncMock(return_value=connection()))
    warehouse = AsyncMock()
    monkeypatch.setattr(access, "get_market_metrics", warehouse)
    assert (
        await access.retrieve(
            "db",
            MarketSummary(operation="market_summary", dataset="sales"),
            connection_id="connection",
            user_id="broker",
            organization_id="org",
        )
        == []
    )
    warehouse.assert_not_called()


async def test_customer_market_uses_canonical_bounded_aggregates(monkeypatch):
    monkeypatch.setattr(
        access.repository,
        "connection",
        AsyncMock(return_value=connection(market_data_enabled=True)),
    )
    warehouse = AsyncMock(return_value=market())
    monkeypatch.setattr(access, "get_market_metrics", warehouse)
    items = await access.retrieve(
        "db",
        MarketSummary(
            operation="market_summary",
            dataset="sales",
            location="Dubai Marina",
            period="previous_quarter",
        ),
        connection_id="connection",
        user_id="broker",
        organization_id="org",
    )
    request = warehouse.call_args.args[0]
    assert request.period.type == "previous_quarter"
    assert request.metrics == ["count", "median_aed"]
    assert request.building is None and request.project is None and request.group_by is None
    assert request.reference_date is None
    assert len(items) == 1
    assert "2026-10-01 to 2026-10-31 (Asia/Dubai)" in items[0].text
    assert "Coverage: partial" in items[0].text and "Missing load evidence" in items[0].text
    assert "Area-level records are excluded" in items[0].text
    assert items[0].release_id == "release-1"
    assert "release-1" not in items[0].text
    assert "Source: served canonical DLD/DXBI market records." in items[0].text
    assert "Data updated: 2026-11-03." in items[0].text


@pytest.mark.parametrize(
    "count,coverage", [(9, "complete"), (0, "unavailable"), (None, "unverified")]
)
def test_small_or_missing_market_evidence_is_not_presented(count, coverage):
    assert (
        market_evidence(
            market(count, coverage), expires_at=utcnow() + timedelta(minutes=15), location=None
        )
        is None
    )


@pytest.mark.parametrize(
    "change", ["revoked", "expired", "changed_price", "changed_availability", "missing"]
)
async def test_changed_publication_cannot_send_stale_evidence(monkeypatch, change):
    row = publication()
    item = listing_evidence(row)
    if change == "revoked":
        row.revoked_at = utcnow()
    elif change == "expired":
        row.expires_at = utcnow() - timedelta(seconds=1)
    elif change == "changed_price":
        row.price_aed += 1
    elif change == "changed_availability":
        row.availability = "unavailable"
    monkeypatch.setattr(
        access.repository,
        "published_listing",
        AsyncMock(return_value=None if change == "missing" else row),
    )
    assert not await access.valid_evidence(
        "db", connection(), [item.id], [item.model_dump(mode="json")], item.text
    )


async def test_live_publication_requires_exact_grounded_text_and_owner_scope(monkeypatch):
    row = publication()
    item = listing_evidence(row)
    lookup = AsyncMock(return_value=row)
    monkeypatch.setattr(access.repository, "published_listing", lookup)
    assert await access.valid_evidence(
        "db", connection(), [item.id], [item.model_dump(mode="json")], item.text
    )
    assert lookup.call_args.args == ("db", row.id, "connection", "broker", "org")
    assert not await access.valid_evidence(
        "db",
        connection(),
        [item.id],
        [item.model_dump(mode="json")],
        item.text + " Guaranteed discount.",
    )
    assert not await access.valid_evidence(
        "db", connection(), [], [item.model_dump(mode="json")], item.text
    )


async def test_market_revocation_and_expiry_are_rechecked_before_send():
    item = market_evidence(market(), expires_at=utcnow() + timedelta(minutes=15), location=None)
    snapshots = [item.model_dump(mode="json")]
    assert await access.valid_evidence(
        "db", connection(market_data_enabled=True), [item.id], snapshots, item.text
    )
    assert not await access.valid_evidence("db", connection(), [item.id], snapshots, item.text)
    item.expires_at = utcnow() - timedelta(seconds=1)
    assert not await access.valid_evidence(
        "db",
        connection(market_data_enabled=True),
        [item.id],
        [item.model_dump(mode="json")],
        item.text,
    )


async def test_listing_lookup_is_capped_and_never_crosses_connection(monkeypatch):
    monkeypatch.setattr(access.repository, "connection", AsyncMock(return_value=connection()))
    lookup = AsyncMock(return_value=[publication()])
    monkeypatch.setattr(access.repository, "published_listings", lookup)
    result = await access.retrieve(
        "db",
        ListingSearch(operation="published_listings"),
        connection_id="connection",
        user_id="broker",
        organization_id="org",
    )
    assert len(result) == 1
    assert lookup.call_args.args == ("db", "connection", "broker", "org")
    assert lookup.call_args.kwargs["limit"] == 5


# The draft is re-screened under the connection lock before it is saved and sent. The agent's
# own introduction must pass there too, or an accepted draft is cancelled without notice.
async def test_agents_own_introduction_survives_the_recheck_before_send():
    reply = "Hi, it's me Sara from X Realty. Is this to buy or to rent?"
    named = connection()
    named.display_name = "Sara Khan"
    assert await access.valid_evidence("db", named, [], [], reply)
    assert await access.valid_evidence(
        "db", connection(reply_voice={"agent_name": "Sara"}), [], [], reply
    )
    assert not await access.valid_evidence("db", connection(), [], [], reply)
