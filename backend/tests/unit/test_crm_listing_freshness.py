"""Buyer and tenant matches never suggest listings from a stale portal snapshot.

Live, inbound matching suggested listings from the 2026-05-27 snapshot (listing_fresh=false)
with no gate; the only hint was a reason line. Listings an agent already saved or contacted
stay visible, the rest of the lane waits for a fresh catalog.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.crm import matching


def _item(target_type, state, key):
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=1,
        target_type=target_type,
        target_key=key,
        state=state,
        fit="exact",
        title=key,
        subtitle="",
        score=90,
        reasons=[],
        breakdown={},
        snapshot={},
        created_at=now,
        updated_at=now,
        generated_at=now,
    )


ITEMS = [
    _item("listing", "suggested", "stale-suggestion"),
    _item("listing", "saved", "agent-saved"),
    _item("listing", "contacted", "agent-contacted"),
    _item("company", "suggested", "own-listing"),
    _item("listing", "dismissed", "dismissed"),
]


@pytest.fixture(autouse=True)
def plain_responses(monkeypatch):
    monkeypatch.setattr(matching, "_match_response", lambda item: item)


def test_a_stale_catalog_keeps_only_listings_the_agent_acted_on():
    lanes = matching._visible_lanes(ITEMS, listing_fresh=False)
    assert [m.target_key for m in lanes["listings"]] == ["agent-saved", "agent-contacted"]
    assert [m.target_key for m in lanes["company"]] == ["own-listing"]


def test_a_fresh_catalog_shows_its_suggestions():
    lanes = matching._visible_lanes(ITEMS, listing_fresh=True)
    assert [m.target_key for m in lanes["listings"]] == [
        "stale-suggestion",
        "agent-saved",
        "agent-contacted",
    ]
