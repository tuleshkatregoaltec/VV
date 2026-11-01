from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

from app.crm.identity import ParsedContact
from app.crm.import_models import CrmPropertyContactClaim
from app.crm.models import CrmLeadWorkspace
from app.crm.owner_assessment import _project
from app.crm.ownership import _apply_evidence
from app.crm.renewal_leads import _owners_by_candidate


def candidate(**changes):
    values = dict(
        source_sheet="Owners",
        source_row_number=2,
        contact_name="Example",
        phone_primary=None,
        phone_alternate=None,
        email_primary=None,
        area_name="Business Bay",
        project_name="Example",
        building_name="Example Tower",
        unit_number="1204",
        property_type="Apartment",
        transaction_date=date(2025, 1, 1),
        transaction_price_aed=1_000_000,
        party_role="Buyer",
        procedure_type="Sale",
        row_fingerprint="example",
    )
    return ParsedContact(**(values | changes))


def sale(key, day=date(2025, 1, 1), price=1_000_000):
    return dict(sale_key=key, transaction_date=day, sale_amount_aed=price)


def test_missing_registry_price_cannot_support_any_current_acquisition():
    row = candidate()
    _apply_evidence(row, sales={row.property_key: [sale("a", price=0)]}, rentals={})
    assert row.ownership_status not in {"verified_current_owner", "probable_current_owner"}


def test_shared_property_key_cannot_transfer_another_property_types_evidence():
    row = candidate(property_type="Villa")
    event = {**sale("a"), "property_type": "Apartment"}
    _apply_evidence(row, sales={row.property_key: [event]}, rentals={})
    assert row.ownership_status == "conflicting_claim"
    assert row.latest_sale_date is None


def test_unresolved_row_cannot_inherit_a_resolved_rows_shared_display_key():
    row = candidate(evidence={"sales_lookup": {"status": "ambiguous_location"}})
    _apply_evidence(row, sales={row.property_key: [sale("other-property")]}, rentals={})
    assert row.ownership_status == "unmatched"
    assert row.latest_sale_date is None


def test_two_independent_sales_with_same_terms_require_review():
    row = candidate()
    _apply_evidence(row, sales={row.property_key: [sale("a"), sale("b")]}, rentals={})
    assert row.ownership_status == "conflicting_claim"


def test_price_match_does_not_order_two_sales_on_the_same_day():
    row = candidate()
    _apply_evidence(
        row, sales={row.property_key: [sale("a"), sale("b", price=2_000_000)]}, rentals={}
    )
    assert row.ownership_status == "conflicting_claim"


def test_exact_date_cannot_hide_competing_nearby_sale_with_same_amount():
    row = candidate()
    _apply_evidence(
        row, sales={row.property_key: [sale("earlier", date(2024, 12, 31)), sale("a")]}, rentals={}
    )
    assert row.ownership_status == "conflicting_claim"


def test_share_marker_cannot_be_treated_as_full_ownership():
    row = candidate(unit_number="1204 (Q 3)")
    _apply_evidence(row, sales={row.property_key: [sale("a")]}, rentals={})
    assert row.ownership_status == "unit_linked_unverified"


def test_verified_owner_cannot_travel_to_same_named_unit_in_another_area():
    row = candidate()
    rental = {
        "event_key": "wrong-lease",
        "unit_candidate_key": "wrong-property",
        "area_name": "Dubai Marina",
    }
    _apply_evidence(
        row, sales={row.property_key: [sale("sale")]}, rentals={row.property_key: rental}
    )
    assert row.ownership_status == "verified_current_owner"
    assert row.lead_id is None


def test_registry_rewrite_cannot_erase_source_share_qualification():
    row = candidate(unit_number="1204Q3", evidence={"source_fields": {"unit_number": "1204 (Q 3)"}})
    _apply_evidence(row, sales={row.property_key: [sale("a")]}, rentals={})
    assert row.ownership_status == "unit_linked_unverified"


def test_old_plot_recovery_cannot_turn_a_different_source_unit_into_a_current_owner():
    row = candidate(
        unit_number="AFRA040",
        property_type="Land",
        evidence={
            "event_family": "sale",
            "source_fields": {"unit_number": "901", "plot_number": "AFRA040"},
            "property_identity_resolution": {
                "method": "unique_transaction_signature",
                "source": {"unit_number": "901"},
                "resolved": {"unit_number": "AFRA040"},
            },
        },
    )
    event = {**sale("plot"), "unit_number": "AFRA040", "property_type": "Plot"}
    _apply_evidence(row, sales={row.property_key: [event]}, rentals={})
    assert row.ownership_status == "conflicting_claim"
    assert row.latest_sale_date is None and row.lead_id is None


def test_matching_original_full_plot_identifier_keeps_its_ownership_evidence():
    row = candidate(
        unit_number="AFRA040",
        property_type="Land",
        evidence={
            "event_family": "sale",
            "source_fields": {"unit_number": "AFRA040", "plot_number": "AFRA040"},
            "property_identity_resolution": {"source": {"unit_number": "AFRA040"}},
        },
    )
    event = {**sale("plot"), "unit_number": "AFRA040", "property_type": "Plot"}
    _apply_evidence(row, sales={row.property_key: [event]}, rentals={})
    assert row.ownership_status == "verified_current_owner"


def test_derived_recovery_metadata_cannot_override_a_different_explicit_source_unit():
    row = candidate(
        unit_number="AFRA040",
        property_type="Land",
        evidence={
            "event_family": "sale",
            "source_fields": {"unit_number": "901", "plot_number": "AFRA040"},
            "property_identity_resolution": {"source": {"unit_number": "AFRA040"}},
        },
    )
    event = {**sale("plot"), "unit_number": "AFRA040", "property_type": "Plot"}
    _apply_evidence(row, sales={row.property_key: [event]}, rentals={})
    assert row.ownership_status == "conflicting_claim"
    assert row.latest_sale_date is None and row.lead_id is None


def test_rematch_retracts_derived_owner_and_rental_when_evidence_disappears():
    row = candidate()
    _apply_evidence(row, sales={row.property_key: [sale("a")]}, rentals={})
    assert row.ownership_status == "verified_current_owner"
    row.lead_id = "old-lease"
    _apply_evidence(row, sales={}, rentals={})
    assert row.ownership_status == "unmatched"
    assert row.latest_sale_date is None and row.lead_id is None
    assert "sales_match" not in row.evidence


def claim(key="person", status="verified_current_owner", day=date(2025, 1, 1)):
    return CrmPropertyContactClaim(
        organization_id="org",
        import_id=1,
        list_id=1,
        source_sheet="Owners",
        source_row_number=2,
        row_fingerprint=key,
        owner_key=key,
        property_key="tower|101",
        building_name="Tower",
        unit_number="101",
        area_name="Business Bay",
        party_role="Buyer",
        procedure_type="Sale",
        phone_primary="+971501234567",
        lead_id="lease",
        contact_name=key,
        unit_candidate_key="unit",
        ownership_status=status,
        transaction_date=day,
        confidence_score=98,
        match_reason="test",
    )


async def resolved(monkeypatch, claims, workspaces=()):
    # The renewal surface receives the same assessed projection as the owner drawer.
    rows = [
        {
            **item.model_dump(),
            "id": index,
            "assessed_status": item.ownership_status,
            "assessed_reason": item.match_reason,
            "assessed_confidence_score": item.confidence_score,
            "event_family": "sale",
        }
        for index, item in enumerate(claims, 1)
    ]
    assessed = _project(rows, datetime.now(timezone.utc), "available")
    monkeypatch.setattr(
        "app.crm.renewal_leads.get_owner_assessment", AsyncMock(return_value=assessed)
    )
    monkeypatch.setattr(
        "app.crm.workspace_repository.list_lead_workspaces_for_candidates",
        AsyncMock(return_value=workspaces),
    )
    return await _owners_by_candidate(
        None, candidate_keys=["unit"], user_id="user", organization_id="org"
    )


async def test_provisional_and_competing_owners_do_not_fill_scalar_owner(monkeypatch):
    assert await resolved(monkeypatch, [claim(status="probable_current_owner")]) == {}
    assert await resolved(monkeypatch, [claim("one"), claim("two")]) == {}


async def test_later_disposal_invalidates_older_verified_claim(monkeypatch):
    assert (
        await resolved(monkeypatch, [claim(), claim(status="former_owner", day=date(2026, 1, 1))])
        == {}
    )


async def test_newer_or_undated_conflict_blocks_older_verified_owner(monkeypatch):
    from app.crm.imports import _group_properties

    for day in (date(2026, 1, 1), date(2025, 1, 1), None):
        claims = [claim(), claim(status="conflicting_claim", day=day)]
        assert await resolved(monkeypatch, claims) == {}
        assert _group_properties(claims)[0].current_owner is None


async def test_manual_override_survives_but_stale_import_snapshot_does_not(monkeypatch):
    workspace = CrmLeadWorkspace(
        user_id="user",
        organization_id="org",
        lead_id="lease",
        unit_candidate_key="unit",
        owner_name="Old owner",
        owner_source="owner_import",
        tags=["Imported owner"],
    )
    assert await resolved(monkeypatch, [], [workspace]) == {}
    workspace.owner_source = "manual"
    result = await resolved(monkeypatch, [claim()], [workspace])
    assert result["unit"].name == "Old owner" and result["unit"].source == "workspace"
    workspace.owner_name = None
    assert await resolved(monkeypatch, [claim()], [workspace]) == {}
    workspace.owner_source = None
    workspace.tags = []
    assert (await resolved(monkeypatch, [claim()], [workspace]))["unit"].source == "owner_import"


async def test_known_schema_does_not_need_model_confirmation(monkeypatch):
    from app.crm.ai import _llm_mapping
    from app.crm.import_parsing import _inspect_csv

    external = AsyncMock(side_effect=AssertionError("known mapping must remain deterministic"))
    monkeypatch.setattr("app.crm.ai.provider_request", external)
    profile = _inspect_csv(
        b"NameEn,Mobile,BuildingNameEn,UnitNumber,ProcedureValue\n"
        b"Example,0501234567,Example Tower,1204,500000\n",
        "owners.csv",
    )[0]
    result = await _llm_mapping(profile)
    assert result.field_map["contact_name"] == "NameEn"
    assert result.mapping_source == "heuristic"
    external.assert_not_awaited()
