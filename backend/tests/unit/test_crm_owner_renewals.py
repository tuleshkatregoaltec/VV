"""Assets › Renewals (client, 3 Nov 2026): the lease list, but only for units whose
current owner is in the agency's owner imports, so every row is someone the agent can call."""

import asyncio
from datetime import date

from app.crm import opportunity_queries, renewal_leads, renewal_repository
from app.crm.models import CrmRenewalOwner

AS_OF = date(2026, 11, 3)


def _capture_queries(monkeypatch):
    calls = []

    async def query(sql, params):
        calls.append((sql, params))
        return []

    monkeypatch.setattr(opportunity_queries, "query", query)
    return calls


def test_owner_units_narrow_the_lease_query_before_ranking(monkeypatch):
    calls = _capture_queries(monkeypatch)
    asyncio.run(
        opportunity_queries.fetch_renewals(
            AS_OF,
            status=None,
            unlet_only=False,
            expired_days=365,
            area=None,
            property_type=None,
            project=None,
            building=None,
            limit=50,
            offset=0,
            unit_keys=["u1", "u2"],
        )
    )
    assert len(calls) == 2  # the page and its filter options
    for sql, params in calls:
        assert "unit_candidate_key IN {unit_keys:Array(String)}" in sql
        assert params["unit_keys"] == ["u1", "u2"]


def test_plain_renewals_are_not_narrowed(monkeypatch):
    calls = _capture_queries(monkeypatch)
    asyncio.run(
        opportunity_queries.fetch_renewals(
            AS_OF,
            status=None,
            unlet_only=False,
            expired_days=365,
            area=None,
            property_type=None,
            project=None,
            building=None,
            limit=50,
            offset=0,
        )
    )
    assert all("unit_keys" not in sql for sql, _ in calls)


def _lead(key: str) -> dict:
    return {"unit_candidate_key": key}


def _owner_renewals(monkeypatch, keys, leads, owners=None):
    seen = {}

    async def owner_keys(db, organization_id):
        seen["organization_id"] = organization_id
        return keys

    async def tables_exist():
        return True

    async def fetch(anchor, **kwargs):
        seen["unit_keys"] = kwargs.get("unit_keys")
        return leads, len(leads), {}

    async def attach(db, *, candidate_keys, user_id, organization_id):
        seen["owner_lookup"] = candidate_keys
        return owners or {}

    monkeypatch.setattr(renewal_repository, "list_current_owner_unit_keys", owner_keys)
    monkeypatch.setattr(opportunity_queries, "_tables_exist", tables_exist)
    monkeypatch.setattr(opportunity_queries, "fetch_renewals", fetch)
    monkeypatch.setattr(renewal_leads, "_lead_from_row", lambda row: type("L", (), row)())
    monkeypatch.setattr(renewal_leads, "_owners_by_candidate", attach)
    res = asyncio.run(
        renewal_leads.list_owner_renewals(
            object(),
            user_id="user",
            organization_id="org",
            window=None,
            area=None,
            property_type=None,
            project=None,
            building=None,
            limit=50,
            offset=0,
            as_of=AS_OF,
        )
    )
    return res, seen


def test_only_this_agencys_current_owner_units_are_listed(monkeypatch):
    owner = CrmRenewalOwner(name="Maya Example", phone="+971500000002", source="owner_import")
    res, seen = _owner_renewals(monkeypatch, ["u1", "u2"], [_lead("u1")], {"u1": owner})
    assert seen["organization_id"] == "org"
    assert seen["unit_keys"] == ["u1", "u2"]
    assert seen["owner_lookup"] == ["u1"]
    assert res.owners == {"u1": owner}
    assert res.total == 1


def test_no_owner_imports_means_an_empty_list_without_querying_leases(monkeypatch):
    # Without the filter, the lease query would return every lease in Dubai.
    res, seen = _owner_renewals(monkeypatch, [], [_lead("u9")])
    assert res.total == 0
    assert res.leads == []
    assert "unit_keys" not in seen
