"""A page that needs the owners of N units must not assess the organization's whole claim table.

Regression: GET /crm/workspaces resolved owners for ~4.7k workspace units through a
whole-organization assessment, which loaded every claim (311k for one account) into
Python and grew a uvicorn worker past 13 GB.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.crm import owner_assessment, renewal_leads, workspaces


def _install_metadata(monkeypatch, *, loader):
    from app.crm import owner_queries

    monkeypatch.setattr(owner_assessment, "_recent", None)
    monkeypatch.setattr(owner_assessment, "_source_revision", AsyncMock(return_value="rev"))
    monkeypatch.setattr(
        owner_assessment.owner_repository, "owner_sources_only", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(owner_assessment.owner_repository, "list_owner_history_rows", loader)

    def no_cache():
        raise AssertionError("a scoped assessment must not read or write the whole-org cache")

    monkeypatch.setattr(owner_assessment, "_cache_client", no_cache)
    monkeypatch.setattr(
        owner_queries, "fetch_assessment_source_fingerprint", AsyncMock(return_value="wh")
    )


async def test_scoped_assessment_loads_only_the_requested_units(monkeypatch):
    loader = AsyncMock(return_value=[])
    _install_metadata(monkeypatch, loader=loader)
    snapshot = await owner_assessment.get_owner_assessment(
        None, organization_id="org", unit_candidate_keys=["unit-a", "unit-b"]
    )
    assert snapshot.rows == []
    assert loader.await_count == 1
    assert loader.await_args.kwargs["unit_candidate_keys"] == ["unit-a", "unit-b"]
    assert owner_assessment._recent is None


async def test_owners_by_candidate_asks_for_its_own_units_only(monkeypatch):
    assessed = owner_assessment._project([], datetime.now(timezone.utc), "available")
    assess = AsyncMock(return_value=assessed)
    monkeypatch.setattr(renewal_leads, "get_owner_assessment", assess)
    monkeypatch.setattr(
        "app.crm.workspace_repository.list_lead_workspaces_for_candidates",
        AsyncMock(return_value=[]),
    )
    await renewal_leads._owners_by_candidate(
        None, candidate_keys=["unit-b", "unit-a"], user_id="u", organization_id="org"
    )
    assert assess.await_args.kwargs["unit_candidate_keys"] == ["unit-a", "unit-b"]


async def test_workspace_list_does_not_assess_the_whole_organization(monkeypatch):
    workspace = SimpleNamespace(id=1, unit_candidate_key="unit-a")
    monkeypatch.setattr(
        workspaces.workspace_repository, "list_lead_workspaces", AsyncMock(return_value=[workspace])
    )
    monkeypatch.setattr(
        workspaces.workspace_repository, "list_lead_notes", AsyncMock(return_value=[])
    )
    captured = {}

    async def owners(db, *, candidate_keys, user_id, organization_id):
        captured["keys"] = candidate_keys
        return {}

    monkeypatch.setattr(renewal_leads, "_owners_by_candidate", owners)
    monkeypatch.setattr(workspaces, "_workspace_summary", lambda *a, **k: "summary")
    result = await workspaces.list_lead_workspaces(None, user_id="u", organization_id="org")
    assert result == ["summary"]
    assert captured["keys"] == ["unit-a"]


async def test_scoped_assessment_is_reused_until_the_inputs_change(monkeypatch):
    revision = {"value": "one"}
    loader = AsyncMock(return_value=[])
    _install_metadata(monkeypatch, loader=loader)
    monkeypatch.setattr(owner_assessment, "_scoped_recent", {})
    monkeypatch.setattr(
        owner_assessment, "_source_revision", AsyncMock(side_effect=lambda *a: revision["value"])
    )
    keys = ["unit-b", "unit-a"]
    first = await owner_assessment.get_owner_assessment(
        None, organization_id="org", unit_candidate_keys=keys
    )
    second = await owner_assessment.get_owner_assessment(
        None, organization_id="org", unit_candidate_keys=list(reversed(keys))
    )
    assert first is second
    assert loader.await_count == 1
    await owner_assessment.get_owner_assessment(
        None, organization_id="org", unit_candidate_keys=["unit-a"]
    )
    assert loader.await_count == 2
    revision["value"] = "two"
    await owner_assessment.get_owner_assessment(
        None, organization_id="org", unit_candidate_keys=["unit-a"]
    )
    assert loader.await_count == 3


async def test_scoped_assessments_never_exceed_a_small_number_of_cached_scopes(monkeypatch):
    loader = AsyncMock(return_value=[])
    _install_metadata(monkeypatch, loader=loader)
    monkeypatch.setattr(owner_assessment, "_scoped_recent", {})
    for index in range(owner_assessment.SCOPED_CACHE_ENTRIES + 5):
        await owner_assessment.get_owner_assessment(
            None, organization_id=f"org-{index}", unit_candidate_keys=["unit"]
        )
    assert len(owner_assessment._scoped_recent) == owner_assessment.SCOPED_CACHE_ENTRIES
