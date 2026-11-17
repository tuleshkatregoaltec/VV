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


def test_owner_units_are_filtered_by_property_identity_after_ranking(monkeypatch):
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
    assert len(calls) == 1  # current VV combines the empty page and its filter options
    for sql, params in calls:
        assert "unit_keys" not in sql[: sql.index("ranked_unit AS")]
        assert "property_identity_key IN (" in sql[sql.index("FROM leads") :]
        assert "unit_candidate_key IN {unit_keys:Array(String)}" in sql
        assert params["unit_keys"] == ["u1", "u2"]


def test_unknown_owner_leases_leave_out_the_owner_units(monkeypatch):
    # Owner unknown: every lease except those on units with an owner on file.
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
            exclude_units=True,
        )
    )
    assert len(calls) == 1
    for sql, params in calls:
        assert "NOT (property_identity_key IN (" in sql
        assert "unit_keys" not in sql[: sql.index("ranked_unit AS")]
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


def _owner_renewals(monkeypatch, keys, leads, owners=None, owner="known"):
    seen = {}

    async def owner_keys(db, organization_id):
        seen["organization_id"] = organization_id
        return keys

    async def tables_exist():
        return True

    async def fetch(anchor, **kwargs):
        seen["unit_keys"] = kwargs.get("unit_keys")
        seen["exclude_units"] = kwargs.get("exclude_units")
        return leads, len(leads), {}

    async def attach(db, *, candidate_keys, user_id, organization_id):
        seen["owner_lookup"] = candidate_keys
        available = (
            owners
            if owners is not None
            else {key: CrmRenewalOwner(name="Known Example", source="owner_import") for key in keys}
        )
        return {key: value for key, value in available.items() if key in candidate_keys}

    async def uncached(namespace, params, model, compute):
        return await compute()

    monkeypatch.setattr(renewal_leads.lead_cache, "cached", uncached)
    monkeypatch.setattr(renewal_repository, "list_imported_unit_keys", owner_keys)
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
            owner=owner,
        )
    )
    return res, seen


def test_only_this_agencys_current_owner_units_are_listed(monkeypatch):
    owner = CrmRenewalOwner(name="Maya Example", phone="+971500000002", source="owner_import")
    res, seen = _owner_renewals(monkeypatch, ["u1", "u2"], [_lead("u1")], {"u1": owner})
    assert seen["organization_id"] == "org"
    assert seen["unit_keys"] == ["u1"]
    assert seen["owner_lookup"] == ["u1", "u2"]
    assert res.owners == {"u1": owner}
    assert res.total == 1


def test_no_owner_imports_means_an_empty_list_without_querying_leases(monkeypatch):
    # Without the filter, the lease query would return every lease in Dubai.
    res, seen = _owner_renewals(monkeypatch, [], [_lead("u9")])
    assert res.total == 0
    assert res.leads == []
    assert "unit_keys" not in seen


def test_unknown_owner_leases_exclude_this_agencys_owner_units_and_show_no_owner(monkeypatch):
    owner = CrmRenewalOwner(name="Maya Example", source="workspace")
    res, seen = _owner_renewals(monkeypatch, ["u1"], [_lead("u7")], {"u1": owner}, owner="unknown")
    assert seen["unit_keys"] == ["u1"]
    assert seen["exclude_units"] is True
    assert seen["owner_lookup"] == ["u1"]
    assert res.owners == {}
    assert res.total == 1


def test_unknown_owner_without_owner_imports_is_every_lease(monkeypatch):
    res, seen = _owner_renewals(monkeypatch, [], [_lead("u7")], owner="unknown")
    assert not seen["unit_keys"]
    assert res.total == 1


def test_new_contract_under_another_key_blocks_an_old_known_owner_vacancy():
    import re
    import sqlite3

    db = sqlite3.connect(":memory:")
    db.create_function("if", 3, lambda condition, yes, no: yes if condition else no)
    db.create_function("lowerUTF8", 1, str.lower)
    db.create_function("upperUTF8", 1, str.upper)
    db.create_function("concat", -1, lambda *parts: "".join(parts))
    db.create_function(
        "replaceRegexpAll", 3, lambda value, pattern, repl: re.sub(pattern, repl, value)
    )
    # Execute the production identity and ranking SQL. Keys differ because lease attributes drift.
    cte = opportunity_queries._LEAD_CTE
    ranking = cte[cte.index("identified_unit AS (") : cte.index("lead_evidence AS (")].rstrip(",\n")
    prefix = """WITH latest_unit AS (
        SELECT 'old' AS unit_candidate_key, 'unique' AS unit_match_status,
               '101' AS unit_number, 'Tower' AS building_name, '' AS project_name,
               '' AS location_name, 'Marina' AS area_name, '2025-01-01' AS lease_start,
               '2026-01-01' AS lease_end, '2026-11-01' AS last_scraped_at, 'a' AS event_key
        UNION ALL
        SELECT 'new', 'unique', '101', 'Tower', '', '', 'Marina',
               '2026-01-01', '2027-01-01', '2026-11-02', 'b'
    ), """
    owner = (
        "property_identity_key IN (SELECT property_identity_key FROM identified_unit "
        "WHERE unit_candidate_key IN ('old'))"
    )
    try:
        sql = (
            prefix + ranking + " SELECT unit_candidate_key FROM ranked_unit WHERE identity_rank = 1"
        )
        assert db.execute(sql + " AND lease_end < '2026-11-03' AND " + owner).fetchall() == []
        # The current lease belongs to the same known property, never the unknown-owner lane.
        assert db.execute(sql + " AND " + owner).fetchall() == [("new",)]
        assert db.execute(sql + " AND NOT (" + owner + ")").fetchall() == []
    finally:
        db.close()


def test_changed_lease_key_keeps_the_known_owners_contact(monkeypatch):
    owner = CrmRenewalOwner(name="Maya Example", phone="+971500000002", source="owner_import")

    async def aliases(candidate_keys, owner_keys):
        assert candidate_keys == ["new"] and owner_keys == ["old"]
        return [{"candidate_key": "new", "owner_candidate_key": "old"}]

    monkeypatch.setattr(opportunity_queries, "fetch_owner_unit_aliases", aliases)
    res, seen = _owner_renewals(monkeypatch, ["old"], [_lead("new")], {"old": owner})
    assert seen["owner_lookup"] == ["old"]
    assert res.owners == {"new": owner}


async def test_known_owner_filter_and_direction_are_part_of_the_shared_cache_key(monkeypatch):
    from unittest.mock import AsyncMock

    class Cache:
        def __init__(self):
            self.rows = {}

        async def get(self, key):
            return self.rows.get(key)

        async def set(self, key, value, expire=None):
            self.rows[key] = value

    cache = Cache()
    monkeypatch.setattr(renewal_leads.lead_cache, "_cache_client", lambda: cache)
    monkeypatch.setattr(
        renewal_leads.lead_cache, "lead_data_revision", AsyncMock(return_value="same-release")
    )
    monkeypatch.setattr(renewal_leads.lead_cache, "_inflight", {})
    calls = []

    async def compute(**params):
        calls.append(params)
        return renewal_leads.CrmRenewalsResponse(
            leads=[], total=len(calls), limit=50, offset=0, as_of=AS_OF
        )

    monkeypatch.setattr(renewal_leads, "_compute_renewals", compute)
    params = dict(
        window=None,
        area=None,
        property_type=None,
        project=None,
        building=None,
        limit=50,
        offset=0,
        as_of=AS_OF,
    )
    totals = []
    for keys, excluded in [
        (["tenant-a-unit"], False),
        (["tenant-b-unit"], False),
        (["tenant-a-unit"], True),
        (["tenant-a-unit"], False),
    ]:
        totals.append(
            (
                await renewal_leads.list_renewals(**params, unit_keys=keys, exclude_units=excluded)
            ).total
        )
    assert totals == [1, 2, 3, 1]
    assert len(calls) == 3
