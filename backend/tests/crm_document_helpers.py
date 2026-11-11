"""Shared builders for listing-document tests."""

from datetime import datetime, timezone

from app.crm.models import CrmCompanyListingDetail


def listing(key: str = "123", *, managed: bool = True, title: str = "Marina Gate 2BR"):
    return CrmCompanyListingDetail(
        reference=f"PF-{key}",
        agent_name="Big Firm · Navi",
        agent_phone=None,
        mode="sale",
        title=title,
        property_type="Apartment",
        bedrooms=2,
        size_sqft=1200,
        price_aed=2500000,
        area_name="Dubai Marina",
        building_name="Marina Gate",
        unit_number=None,
        status="active",
        listed_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        listing_key=key,
        broker_id="B1",
        broker_name="Big Firm",
        managed=managed,
    )
