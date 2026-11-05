"""The owner-folder value filter uses today's estimate, falling back to the last sale price.

Filtering on the old purchase price would hide owners whose homes are now worth the amount an
agent is searching for.
"""

from app.crm.owner_repository import _owner_filter_sql
from app.crm.owners import _sql_owner_property


def test_min_value_filter_uses_estimate_then_last_sale():
    sql, parameters = _owner_filter_sql(
        scope="all", status=None, search=None, min_value_aed=2_000_000
    )
    assert "coalesce(p.estimated_value_aed, p.latest_sale_price_aed) >= :owner_min_value" in sql
    assert parameters["owner_min_value"] == 2_000_000


def test_max_value_filter_uses_estimate_then_last_sale():
    sql, _ = _owner_filter_sql(scope="all", status=None, search=None, max_value_aed=3_000_000)
    assert "coalesce(p.estimated_value_aed, p.latest_sale_price_aed) <= :owner_max_value" in sql


def _row(**extra):
    row = {
        "property_key_sql": "p-1",
        "area_name": "Town Square",
        "project_name": "",
        "building_name": "Reem Townhouses",
        "unit_number": "187",
        "property_type": "Villa",
        "ownership_status": "verified_current_owner",
        "confidence_score": 95,
        "match_reason": "",
        "lead_id": None,
        "unit_candidate_key": None,
        "transaction_date": None,
        "transaction_price_aed": None,
        "party_role": "",
        "latest_sale_date": None,
        "latest_sale_price_aed": 2_365_000,
        "later_sale_date": None,
        "lease_end": None,
        "annual_rent_aed": None,
        "duplicate_count": 1,
        "source_lists": [],
        "source_rows": [],
    }
    row.update(extra)
    return row


def test_owner_property_carries_the_estimate():
    prop = _sql_owner_property(
        _row(
            estimated_value_aed=2_687_000,
            estimated_value_low_aed=2_576_000,
            estimated_value_high_aed=2_901_000,
            valuation_confidence="high",
            valued_at="2026-11-05",
        )
    )
    assert (
        prop.estimated_value_aed,
        prop.estimated_value_low_aed,
        prop.estimated_value_high_aed,
    ) == (
        2_687_000,
        2_576_000,
        2_901_000,
    )
    assert prop.valuation_confidence == "high"
    assert str(prop.valued_at) == "2026-11-05"


def test_owner_property_without_estimate():
    prop = _sql_owner_property(_row())
    assert prop.estimated_value_aed is None and prop.valued_at is None
