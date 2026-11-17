"""Agent lead analytics: the pure rules behind source kinds, averages and pool claim times."""

from datetime import datetime, timedelta, timezone

from app.crm.agent_analytics import average_minutes, claim_waits, source_kind
from app.crm.inbound_models import SOLD_OWNER_SOURCE

T = datetime(2026, 11, 17, 9, tzinfo=timezone.utc)


def test_source_kind_maps_vitevue_and_own_sources():
    assert source_kind(SOLD_OWNER_SOURCE, {}) == "vitevue_sold"
    assert source_kind("Imported", {"vitevue_lease": {"unit": "1204"}}) == "vitevue_lease"
    assert source_kind("Referral", None) == "own"
    assert source_kind("Manual", {}) == "own"
    assert source_kind("Meta", {}) == "marketing"


def test_average_minutes_rounds_and_is_none_when_empty():
    assert average_minutes([timedelta(minutes=10), timedelta(minutes=15)]) == 13  # 12.5 → 13
    assert average_minutes([]) is None


def test_claim_waits_pairs_each_claim_with_the_latest_release():
    rows = [
        (1, "released", T, "mgr"),
        (1, "claimed", T + timedelta(minutes=9), "omar"),
        (2, "released", T, "mgr"),
        (2, "released", T + timedelta(minutes=20), "mgr"),
        (2, "claimed", T + timedelta(minutes=30), "sara"),
    ]
    assert claim_waits(rows) == {"omar": [timedelta(minutes=9)], "sara": [timedelta(minutes=10)]}


def test_claim_without_release_is_skipped():
    assert claim_waits([(3, "claimed", T, "omar")]) == {}
