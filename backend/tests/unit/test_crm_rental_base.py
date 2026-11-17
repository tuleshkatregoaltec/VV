"""A fast base is usable only if *every* input and the published schema still agree."""

import json
from copy import deepcopy

import pytest
from crm_rental_sql import (
    AREA_LEAD_CTE,
    BASE_TABLE,
    DEPENDENCIES,
    LIVE_LEAD_CTE,
    PUBLICATION_POLICY,
    TRANSFORM_REVISION,
    VIEW_DEPENDENCIES,
    base_lead_cte,
    dependency_revision,
    schema_revision,
)

from app.crm import opportunity_queries, rental_base


def _sources():
    return [
        {
            "name": name,
            "engine": "View" if name in VIEW_DEPENDENCIES else "ReplacingMergeTree",
            "uuid": name,
            "ddl": name,
            "parts": "[]",
            "pending": 0,
        }
        for name in DEPENDENCIES
    ]


COLUMNS = [{"name": "event_key", "type": "String", "position": 1}]


def _metadata(sources):
    return {
        "engine": "MergeTree",
        "total_rows": 3,
        "comment": json.dumps(
            {
                "kind": PUBLICATION_POLICY,
                "source": dependency_revision(sources),
                "schema": schema_revision(COLUMNS),
                "transform": TRANSFORM_REVISION,
                "rows": 3,
            }
        ),
    }


async def test_disabled_base_has_no_probe_cost(monkeypatch):
    monkeypatch.setattr(rental_base.settings, "CRM_RENTAL_BASE_ENABLED", False)

    async def query(sql):
        pytest.fail("Disabled base must not probe metadata or source rows")

    assert await rental_base.lead_cte(query) == LIVE_LEAD_CTE
    assert await rental_base.lead_cte(query, areas=True) == AREA_LEAD_CTE


@pytest.mark.parametrize("areas", [False, True])
async def test_valid_base_uses_only_metadata_to_check_readiness(monkeypatch, areas):
    monkeypatch.setattr(rental_base.settings, "CRM_RENTAL_BASE_ENABLED", True)
    sources = _sources()

    async def query(sql):
        assert "system." in sql
        assert " FINAL" not in sql
        if "system.columns" in sql:
            return COLUMNS
        if "system.parts" in sql:
            return sources
        return [_metadata(sources)]

    cte = await rental_base.lead_cte(query, areas=areas)
    assert cte == base_lead_cte(areas=areas)
    assert "PREWHERE area_name IN {areas:Array(String)}" in cte if areas else True


@pytest.mark.parametrize("changed", DEPENDENCIES)
async def test_any_source_or_view_change_invalidates_base(monkeypatch, changed):
    monkeypatch.setattr(rental_base.settings, "CRM_RENTAL_BASE_ENABLED", True)
    sources = _sources()
    changed_sources = deepcopy(sources)
    next(row for row in changed_sources if row["name"] == changed)["ddl"] += " updated"

    async def query(sql):
        if "system.columns" in sql:
            return COLUMNS
        if "system.parts" in sql:
            return changed_sources
        return [_metadata(sources)]

    assert await rental_base.lead_cte(query) == LIVE_LEAD_CTE


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "empty",
        "schema",
        "legacy",
        "bad_marker",
        "probe_error",
        "transform",
        "prior_policy",
    ],
)
async def test_unusable_or_unpublished_base_falls_back(monkeypatch, failure):
    monkeypatch.setattr(rental_base.settings, "CRM_RENTAL_BASE_ENABLED", True)
    sources = _sources()
    metadata = _metadata(sources)
    if failure == "empty":
        metadata["total_rows"] = 0
    if failure == "legacy":
        metadata["comment"] = "{}"
    if failure == "bad_marker":
        metadata["comment"] = "unfinished"
    if failure == "prior_policy":
        marker = json.loads(metadata["comment"])
        marker["kind"] = "crm-rental-ranked-base/v1"
        metadata["comment"] = json.dumps(marker)
    if failure == "transform":
        marker = json.loads(metadata["comment"])
        marker["transform"] = "previous-transform"
        metadata["comment"] = json.dumps(marker)

    async def query(sql):
        if failure == "probe_error":
            raise RuntimeError("permission denied")
        if "system.columns" in sql:
            return [] if failure == "schema" else COLUMNS
        if "system.parts" in sql:
            return sources
        return [] if failure == "missing" else [metadata]

    assert await rental_base.lead_cte(query, areas=True) == AREA_LEAD_CTE


def test_pending_mutation_and_missing_input_are_not_stable_releases():
    rows = _sources()
    rows[0]["pending"] = 1
    with pytest.raises(ValueError, match="mutation"):
        dependency_revision(rows)
    with pytest.raises(ValueError, match="seven"):
        dependency_revision(_sources()[:-1])


async def test_saved_aliases_and_detail_stay_live_even_when_base_is_enabled(monkeypatch):
    monkeypatch.setattr(rental_base.settings, "CRM_RENTAL_BASE_ENABLED", True)
    calls = []

    async def query(sql, params):
        calls.append(sql)
        return [{"saved_candidate_key": "old-candidate", "event_key": "latest-event"}]

    monkeypatch.setattr(opportunity_queries, "query", query)
    await opportunity_queries.fetch_saved_leads({"candidate_keys": ["old-candidate"]})
    await opportunity_queries.fetch_lead({"lead_id": "latest-event"})
    assert all(BASE_TABLE not in sql for sql in calls)
    assert "FROM identified_unit AS i" in calls[0]
    # Live ranking over the leases that can share the requested units (never the base table).
    assert all("FROM dxbi_rental_unit_candidates AS c2 FINAL" in sql for sql in calls)


async def test_saved_join_qualification_preserves_the_lead_projection(monkeypatch):
    async def query(sql, params):
        return [
            {
                "saved_candidate_key": "old",
                "l.event_key": "latest",
                "l.unit_candidate_key": "current",
                "l.area_name": "JVC",
            }
        ]

    monkeypatch.setattr(opportunity_queries, "query", query)
    rows = await opportunity_queries.fetch_saved_leads({"candidate_keys": ["old"]})
    assert rows == [
        {
            "saved_candidate_key": "old",
            "event_key": "latest",
            "unit_candidate_key": "current",
            "area_name": "JVC",
        }
    ]
