"""Source-audit workbooks read through the stored assessment, never the warehouse."""

import copy
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from owner_store_support import install_rows

from app.crm import owner_assessment, owner_rows, owners

_spec = importlib.util.spec_from_file_location(
    "unit_source_audit_fixtures", Path(__file__).parents[2] / "unit" / "test_crm_source_audit.py"
)
fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures)
history_rows = fixtures.history_rows
matched_history_rows = fixtures.matched_history_rows


async def test_source_only_reads_never_request_warehouse_or_profile_enrichment(
    pg_session, monkeypatch
):
    rows = history_rows()
    snapshot = owner_assessment._source_snapshot(rows, datetime.now(timezone.utc))
    await install_rows(pg_session, monkeypatch, snapshot.rows, organization_id="tenant")
    warehouse = AsyncMock(side_effect=AssertionError("Source-only mode must never query warehouse"))
    monkeypatch.setattr(owners, "_enrich_owner_profile_registry", warehouse)
    profile = await owners.get_owner_profile(
        pg_session, organization_id="tenant", owner_key=rows[0]["owner_key"]
    )
    assert profile.highest_ownership_status == "probable_current_owner"
    response = await owners.get_owner_registry(
        pg_session,
        organization_id="tenant",
        list_id=None,
        scope="all",
        status=None,
        search=None,
        lease_window=None,
        portfolio_only=False,
        min_rent_aed=None,
        max_rent_aed=None,
        min_value_aed=None,
        max_value_aed=None,
        limit=50,
        offset=0,
    )
    assert response.total == 1
    assert response.source_audit.source_row_count == 3
    warehouse.assert_not_called()


@pytest.mark.parametrize(
    "scope,status", [("current_owners", "probable_current_owner"), ("prior_owners", "former_owner")]
)
async def test_owner_category_filter_scopes_properties_of_a_person_with_both_histories(
    pg_session, monkeypatch, scope, status
):
    snapshot = owner_assessment._source_snapshot(matched_history_rows(), datetime.now(timezone.utc))
    await install_rows(pg_session, monkeypatch, snapshot.rows, organization_id="tenant")
    response = await owners.get_owner_registry(
        pg_session,
        organization_id="tenant",
        list_id=None,
        scope=scope,
        status=None,
        search=None,
        lease_window=None,
        portfolio_only=False,
        min_rent_aed=None,
        max_rent_aed=None,
        min_value_aed=None,
        max_value_aed=None,
        limit=10,
        offset=0,
    )
    assert response.total == 1
    assert response.owners[0].property_count == 1
    assert [item.ownership_status for item in response.owners[0].properties] == [status]


async def test_transaction_match_filter_preserves_unverified_roles_before_paging(
    pg_session, monkeypatch
):
    rows = matched_history_rows()
    rows[0]["evidence"]["source_audit"]["transaction_match"]["acquisition_sale_keys"] = ["sale:1"]
    rows[1]["evidence"]["source_audit"]["transaction_match"].update(
        status="unmatched", property_key=None, latest_sale_date=None, later_sale_date=None
    )
    extra = copy.deepcopy(rows[0])
    extra["id"] = 5
    extra["evidence"]["source_audit"]["reference_id"] = "plot:5"
    extra["evidence"]["source_audit"]["transaction_match"].update(
        status="unmatched",
        property_key=None,
        canonical_owner_key="another-owner",
        acquisition_sale_keys=[],
    )
    rows.append(extra)
    snapshot = owner_assessment._source_snapshot(rows, datetime.now(timezone.utc))
    await install_rows(pg_session, monkeypatch, snapshot.rows, organization_id="tenant")
    response = await owners.get_owner_registry(
        pg_session,
        organization_id="tenant",
        list_id=None,
        scope="all",
        status=None,
        search=None,
        lease_window=None,
        portfolio_only=False,
        min_rent_aed=None,
        max_rent_aed=None,
        min_value_aed=None,
        max_value_aed=None,
        limit=1,
        offset=0,
        transaction_match_status="unmatched",
    )
    assert response.total == 2  # Count all eligible owners before taking this page.
    assert len(response.owners) == 1
    assert response.owners[0].property_count == 1
    assert all(
        p.source_reference.transaction_match_status == "unmatched"
        for p in response.owners[0].properties
    )
    assert response.source_audit.reference_count == 5  # The file denominator is not filtered.
    profiles = owner_rows.assessed_profiles(snapshot.rows, snapshot=snapshot)
    refs = {
        p.source_reference.reference_id: p.source_reference
        for owner in profiles
        for p in owner.properties
    }
    assert refs["plot:1"].ownership_evidence_basis == "transaction_supported"
    assert refs["plot:2"].ownership_evidence_basis == "workbook_only"
    assert refs["plot:2"].transaction_match_status == "unmatched"
    assert any(
        p.ownership_status == "former_owner"
        for o in profiles
        for p in o.properties
        if p.source_reference.reference_id == "plot:2"
    )
