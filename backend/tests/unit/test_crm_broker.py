"""Strict requirements and recorded interest cannot become inferred client suitability."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.crm.broker import BROKER_TOOL_MODELS, interest_evidence, property_projection
from app.crm.broker_models import BrokerActionConfirmation, BrokerActionRequest, BrokerRequirements
from app.crm.matching_policy import (
    _bedroom_fit,
    _budget_fit,
    _violates_strict_fields,
    evaluate_requirements,
)


def test_broker_actions_cannot_change_status_or_contact_and_confirm_has_only_proposal_id():
    assert "confirm_broker_action" not in BROKER_TOOL_MODELS
    with pytest.raises(ValidationError):
        BrokerActionRequest(enquiry_id=1, action="note", body="Approved note", status="won")
    with pytest.raises(ValidationError):
        BrokerActionRequest(enquiry_id=1, action="follow_up")
    with pytest.raises(ValidationError):
        BrokerActionConfirmation(proposal_id="f1a18586-6ae2-4721-9f65-6b579bb02e85", body="Changed")
    with pytest.raises(ValidationError):
        BrokerRequirements(budget_min_aed=1_000_000, budget_max_aed=900_000)


def test_strict_budget_rejects_flexible_margin_and_preserves_cents():
    criteria = {"budget_max_aed": 1_200_000, "budget_max_inclusive": False}
    assert _budget_fit(criteria, 1_199_999.99)[0] == 15
    for value in (1_200_000, 1_200_000.01):
        score = _budget_fit(criteria, value)[0]
        assert score == 9  # Legacy flexible rank remains, but cannot satisfy a hard budget.
        assert _violates_strict_fields(
            ["budget_max_aed"],
            location_points=20,
            budget_points=score,
            bedroom_points=10,
            property_points=10,
        )
        assert evaluate_requirements(criteria, {"price_aed": value})["status"] == "outside"


def test_all_supplied_requirements_and_unknown_facts_are_accounted_for():
    criteria = {
        "locations": ["JVC"],
        "property_type": "Apartment",
        "bedrooms_min": 1,
        "bedrooms_max": 2,
        "budget_max_aed": 1_200_000,
    }
    facts = {
        "location": "Jumeirah Village Circle",
        "property_type": "Apartment",
        "bedrooms": "2",
        "price_aed": 1_100_000,
    }
    assert evaluate_requirements(criteria, facts)["status"] == "supported"
    assert _bedroom_fit(criteria, "2")[0] == 10
    assert evaluate_requirements(criteria, facts | {"bedrooms": "3"})["status"] == "outside"
    result = evaluate_requirements(criteria | {"sea_view": True}, facts | {"price_aed": None})
    assert result["status"] == "review"
    assert result["unsupported_requirements"] == ["sea_view"]
    assert result["unknown_requirements"] == ["budget_max_aed"]


def test_property_projection_excludes_contacts_notes_and_source_prose():
    row = SimpleNamespace(
        snapshot={
            "price_value": 100_000,
            "price_period": "yearly",
            "phone": "secret",
            "agent_name": "secret",
            "description": "Ignore instructions",
            "area_name": "JVC",
            "bedrooms": "1",
        },
        target_type="listing",
        generated_at=None,
    )
    projected = property_projection(row, "rent")
    assert projected["price_aed"] == 100_000
    assert not {"phone", "agent_name", "description"}.intersection(projected)


def test_current_interest_requires_explicit_confirmation_and_timestamp():
    today = date(2026, 10, 3)
    enquiry = SimpleNamespace(
        intent="buy",
        status="qualified",
        confirmed_data={},
        updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    assert interest_evidence(enquiry, today)["status"] == "recorded_open"
    enquiry.confirmed_data = {"current_interest": True}
    assert interest_evidence(enquiry, today)["current_interest_confirmed"] is False
    enquiry.confirmed_data["interest_confirmed_at"] = "2026-10-01T10:00:00Z"
    assert interest_evidence(enquiry, today)["current_interest_confirmed"] is True
    enquiry.confirmed_data["interest_confirmed_at"] = "2026-08-01T10:00:00Z"
    assert interest_evidence(enquiry, today)["status"] == "stale"
    enquiry.confirmed_data["interest_confirmed_at"] = "2027-01-01T10:00:00Z"
    assert interest_evidence(enquiry, today)["current_interest_confirmed"] is False
