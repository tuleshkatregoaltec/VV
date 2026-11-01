"""Source lifecycle hints must not become fabricated sale, rental or agent facts."""

from datetime import date, datetime, timezone

import pytest

from app.crm.identity import ParsedContact
from app.crm.import_events import event_family
from app.crm.owner_assessment import _candidate, _finish_assessment
from app.crm.owner_signals import build_owner_signals
from app.crm.ownership import _apply_evidence
from app.crm.source_lifecycle import annotate_source_lifecycle


def contact(name="Person", year=2020, amount=1000000, role="Buyer", procedure="Sale", **changes):
    values = dict(
        source_sheet="Sheet",
        source_row_number=2,
        contact_name=name,
        phone_primary=None,
        phone_alternate=None,
        email_primary=None,
        area_name="Area",
        project_name="Project",
        building_name="Tower",
        unit_number="101",
        property_type="Apartment",
        transaction_date=date(year, 1, 1),
        transaction_price_aed=amount,
        party_role=role,
        procedure_type=procedure,
        row_fingerprint=f"{name}-{year}",
        evidence={"event_family": event_family(procedure)},
    )
    return ParsedContact(**{**values, **changes})


def registry(candidate, **changes):
    return {
        "transaction_date": candidate.transaction_date,
        "sale_amount_aed": candidate.transaction_price_aed,
        "sale_key": "exact-sale",
        **changes,
    }


def test_bank_name_and_extreme_drop_are_review_hints_not_rental_facts_or_deletion():
    rows = [contact(), contact("Example Bank", 2021, 100000, procedure="")]
    result = annotate_source_lifecycle(rows, policy="dated-parties")
    assert len(result) == len(rows) == 2
    assert {"possible_financial_institution", "amount_anomaly_possible_non_sale"} <= set(
        result[1]["flags"]
    )
    assert all(r["as_of_file"] == "uncertain" for r in result)
    assert result[1]["event_family"] == "contact_snapshot"
    assert result[1]["previous_comparable_amounts_aed"] == [1000000]
    assert result[1]["party_role"] == "Buyer"
    assert "Bank" not in str(result)
    assert "rental" not in result[1]["flags"]


def test_bank_can_be_an_actual_registry_sale_even_with_source_anomaly():
    prior, bank = contact(), contact("Example Bank", 2021, 100000, procedure="")
    annotate_source_lifecycle([prior, bank], policy="dated-parties")
    _apply_evidence(bank, sales={bank.property_key: [registry(bank)]}, rentals={})
    assert bank.ownership_status == "verified_current_owner"
    assert bank.evidence["registry_inferred_sale"]["sale_key"] == "exact-sale"
    assert "Source review" in bank.match_reason


def test_missing_earlier_acquisition_is_not_an_agent_assertion():
    seller = contact("Seller", role="Seller")
    result = annotate_source_lifecycle([seller])[0]
    assert "prior_acquisition_not_observed" in result["flags"]
    assert "incomplete history" in " ".join(result["reasons"])
    profile = build_owner_signals(
        [
            {
                "canonical_owner_key": "one",
                "contact_name": seller.contact_name,
                "source_lifecycle": result,
            }
        ]
    )["one"]
    assert profile["relationship_role"] == "unknown"
    assert profile["role_signals"]


def test_observed_prior_buyer_and_later_reacquisition_beat_old_seller():
    rows = [contact(), contact(year=2021, role="Seller"), contact(year=2022)]
    result = annotate_source_lifecycle(rows)
    assert "prior_acquisition_not_observed" not in result[1]["flags"]
    assert result[1]["as_of_file"] == "historical_source_party"
    assert result[2]["as_of_file"] == "possible_as_of_file"


@pytest.mark.parametrize(
    "procedure,family",
    [
        ("Rental Delayed Sell", "rental"),
        ("Lease Registration Sale", "rental"),
        ("Complete Lease To Own On Delayed Sell", "lease_to_own"),
        ("Mortgage Sale", "financing"),
        ("Gift Sale", "gift"),
        ("Ownership Transfer", "ownership_transfer"),
        ("Inheritance", "inheritance"),
    ],
)
def test_explicit_other_lifecycles_never_infer_acquisition(procedure, family):
    candidate = contact(procedure=procedure)
    assert event_family(procedure) == family
    assert (
        annotate_source_lifecycle([candidate], policy="dated-parties")[0]["as_of_file"]
        != "possible_as_of_file"
    )
    _apply_evidence(candidate, sales={candidate.property_key: [registry(candidate)]}, rentals={})
    assert candidate.ownership_status == "unit_linked_unverified"
    assert "registry_inferred_sale" not in candidate.evidence


def test_same_date_different_buyers_and_amounts_never_choose_input_order():
    rows = [contact("First"), contact("Second", amount=2000000)]
    forward = annotate_source_lifecycle(rows)
    reverse = annotate_source_lifecycle(list(reversed(rows)))
    assert forward == list(reversed(reverse))
    assert all(
        {"latest_buyer_tie", "same_date_amount_conflict"} <= set(r["flags"]) for r in forward
    )
    assert all(r["as_of_file"] == "uncertain" for r in forward)
    assert all("amount_anomaly_possible_non_sale" not in r["flags"] for r in forward)


def test_equal_same_day_amount_coowners_remain_uncertain():
    result = annotate_source_lifecycle([contact("First"), contact("Second")])
    assert all("latest_buyer_tie" in r["flags"] for r in result)


def test_later_unknown_event_blocks_source_current_without_reassigning_owner():
    result = annotate_source_lifecycle(
        [contact(), contact("Other", 2021, procedure="Unknown Registration")]
    )
    assert result[0]["as_of_file"] == "uncertain"
    assert "later_unknown_lifecycle" in result[0]["flags"]
    assert result[1]["as_of_file"] != "possible_as_of_file"


def test_missing_procedure_requires_opt_in_even_with_dated_buyer():
    buyer = contact(procedure="")
    assert annotate_source_lifecycle([buyer])[0]["as_of_file"] != "possible_as_of_file"
    assert (
        annotate_source_lifecycle([buyer], policy="dated-parties")[0]["as_of_file"]
        == "possible_as_of_file"
    )
    assert buyer.evidence["event_family"] == "contact_snapshot"
    _apply_evidence(buyer, sales={}, rentals={})
    assert buyer.ownership_status == "unmatched"


@pytest.mark.parametrize(
    "change",
    [
        {"transaction_date": date(2020, 1, 2)},
        {"sale_amount_aed": 2000000},
        {"sale_amount_aed": 1000001},
        {"size_sqft": 1500},
    ],
)
def test_blank_procedure_requires_exact_date_amount_and_comparable_declared_size(change):
    buyer = contact(
        procedure="",
        evidence={
            "event_family": "contact_snapshot",
            "source_size_unit": "sqft",
            "source_fields": {"size_sqft": "1000"},
        },
    )
    _apply_evidence(
        buyer,
        sales={buyer.property_key: [registry(buyer, size_sqft=1000, **change)]}
        if "size_sqft" not in change
        else {buyer.property_key: [registry(buyer, **change)]},
        rentals={},
    )
    assert buyer.ownership_status == "unit_linked_unverified"
    assert "registry_inferred_sale" not in buyer.evidence


def test_bank_signal_does_not_prevent_exact_sale_and_stale_registry_inference_is_cleared():
    buyer = contact("Example Bank", procedure="")
    _apply_evidence(buyer, sales={buyer.property_key: [registry(buyer)]}, rentals={})
    assert buyer.ownership_status == "verified_current_owner"
    _apply_evidence(buyer, sales={}, rentals={})
    assert buyer.ownership_status == "unmatched"
    assert "registry_inferred_sale" not in buyer.evidence


@pytest.mark.parametrize(
    "evidence",
    [
        {"source_identity_incomplete": True},
        {"source_reference_kind": "cluster"},
        {"unit_number_fallback": {"source_field": "buildingno"}},
    ],
)
def test_cluster_or_incomplete_identity_never_uses_source_chronology(evidence):
    result = annotate_source_lifecycle([contact(evidence=evidence)])[0]
    assert "unresolved_property_identity" in result["flags"]
    assert result["as_of_file"] == "not_assessed"


def test_incompatible_scope_is_not_merged_and_separate_files_do_not_make_a_lifecycle():
    result = annotate_source_lifecycle([contact(), contact("Other", 2021, area_name="Other Area")])
    assert all("unresolved_property_identity" in r["flags"] for r in result)
    first, second = contact(), contact("Other", 2021)
    first.evidence["source_filename"], second.evidence["source_filename"] = "one.csv", "two.csv"
    result = annotate_source_lifecycle([first, second])
    assert all(r["as_of_file"] == "possible_as_of_file" for r in result)


def test_exact_registry_missing_procedure_survives_fresh_projection_and_failure_clears_it():
    buyer = contact(procedure="")

    def assess(available):
        row = {
            **vars(buyer),
            "id": 1,
            "owner_key": "source-owner",
            "import_id": 1,
            "property_key": buyer.property_key,
            "event_family": "contact_snapshot",
            "registry_inferred_sale": True,
        }
        snapshot = _finish_assessment(
            [row],
            [(row, _candidate(row))],
            {buyer.property_key: [registry(buyer)]} if available else {},
            datetime.now(timezone.utc),
            "available" if available else "unavailable",
        )
        return snapshot.rows[0]

    assert assess(True)["assessed_status"] == "verified_current_owner"
    failed = assess(False)
    assert failed["assessed_status"] != "verified_current_owner"
    assert failed["registry_inferred_sale"] is False
    assert failed["source_lifecycle"]["legal_ownership_proof"] is False


def test_registry_alias_uses_equivalent_areas_with_original_alias_keys():
    from app.crm.ownership import _canonical_alias_id

    candidate = contact(
        area_name="JVC",
        evidence={
            "source_fields": {
                "area_name": "JVC",
                "project_name": "Project",
                "building_name": "Source Tower",
            }
        },
    )
    observed = {
        "area_name": "Jumeirah Village Circle",
        "project_name": "Project",
        "building_name": "Registry Tower",
    }
    aliases = {
        ("sourcetower", "jvc", "project"): {"one"},
        ("registrytower", "jumeirahvillagecircle", "project"): {"one"},
    }
    assert _canonical_alias_id(candidate, observed, aliases) == "one"
    assert not _canonical_alias_id(candidate, {**observed, "project_name": "Other"}, aliases)
    assert not _canonical_alias_id(
        candidate, {**observed, "area_name": "Jumeirah Lakes Towers"}, aliases
    )
    aliases[("sourcetower", "jumeirahvillagecircle", "project")] = {"conflicting"}
    assert not _canonical_alias_id(candidate, observed, aliases)


def test_master_project_context_comes_only_from_preserved_source_fields():
    from app.crm.ownership import _area_scope_keys, _canonical_source_location

    candidate = contact(
        area_name="Recovered Area",
        evidence={"source_fields": {"master_project": "JVC", "building_name": "Source Tower"}},
    )
    assert _canonical_source_location(candidate)["area_name"] == "JVC"
    assert {"jvc", "jumeirahvillagecircle"} <= _area_scope_keys("JVC")
    candidate.evidence["source_fields"]["master_project"] = "0"
    assert not _canonical_source_location(candidate).get("area_name")


async def test_sales_alias_lookup_requests_equivalent_source_community_keys(monkeypatch):
    from unittest.mock import AsyncMock

    from app.crm import owner_queries
    from app.crm.ownership import _sales_evidence

    candidate = contact(
        area_name="JVC",
        evidence={
            "source_fields": {
                "master_project": "JVC",
                "project_name": "Project",
                "building_name": "Tower",
            }
        },
    )
    observed = {
        **registry(candidate),
        "area_name": "Jumeirah Village Circle",
        "project_name": "Project",
        "building_name": "Tower",
        "unit_number": "101",
        "unit_key": "101",
        "area_key": "jumeirahvillagecircle",
        "building_key": "tower",
    }
    monkeypatch.setattr(owner_queries, "fetch_unit_sales", AsyncMock(return_value=[observed]))
    lookup = AsyncMock(return_value=[])
    monkeypatch.setattr(owner_queries, "fetch_canonical_building_keys", lookup)
    await _sales_evidence([candidate])
    assert {"jvc", "jumeirahvillagecircle", "jvc/project", "jumeirahvillagecircle/project"} <= set(
        lookup.call_args.args[0]["community_keys"]
    )


def test_fresh_projection_preserves_buyer_seller_roles_and_later_reacquisition():
    buyer, seller = (
        contact("New Buyer", 2021, procedure=""),
        contact("Original Seller", 2021, role="Seller", procedure=""),
    )

    def assess(candidates, events):
        rows = [
            {
                **vars(candidate),
                "id": i,
                "owner_key": str(i),
                "import_id": 1,
                "property_key": candidate.property_key,
                "event_family": candidate.evidence.get("event_family"),
            }
            for i, candidate in enumerate(candidates, 1)
        ]
        return _finish_assessment(
            rows,
            [(row, _candidate(row)) for row in rows],
            {buyer.property_key: events},
            datetime.now(timezone.utc),
            "available",
        )

    snapshot = assess([buyer, seller], [registry(buyer)])
    assert [row["assessed_status"] for row in snapshot.rows] == [
        "verified_current_owner",
        "former_owner",
    ]
    reacquisition = contact("Original Seller", 2022, procedure="")
    result = assess(
        [seller, reacquisition],
        [registry(seller), registry(reacquisition, sale_key="reacquisition")],
    )
    assert all(row["assessed_status"] == "verified_current_owner" for row in result.rows)
    assert result.rows[0]["event_assessed_status"] == "former_owner"


def test_legacy_current_seller_label_is_not_current_ownership_evidence():
    from app.crm.owner_projection import project_owner_history

    seller = contact(role="Seller")
    row = {
        **vars(seller),
        "id": 1,
        "owner_key": "legacy",
        "property_key": seller.property_key,
        "ownership_status": "probable_current_owner",
        "confidence_score": 55,
        "event_family": "sale",
        "sale_anchor_key": "legacy-sale",
        "sale_anchor_date": seller.transaction_date,
    }
    summary, _ = project_owner_history([row], [row])
    assert summary.probable_current_count == 0
    assert summary.verified_current_count == 0


def test_fresh_alias_matching_does_not_reuse_recovered_geography_as_source_proof():
    from app.crm.owner_assessment import match_owner_evidence

    candidate = contact(
        area_name="JVC",
        building_name="Recovered Tower",
        evidence={
            "source_fields": {
                "area_name": "Jumeirah Lakes Towers",
                "project_name": "Project",
                "building_name": "Source Tower",
            }
        },
    )
    observed = {
        **registry(candidate),
        "area_name": "JVC",
        "project_name": "Project",
        "building_name": "Registry Tower",
        "unit_number": "101",
    }
    aliases = [
        {
            "name_key": "sourcetower",
            "community_key": "jumeirahlakestowers",
            "project_key": "project",
            "building_id": "same",
        },
        {
            "name_key": "registrytower",
            "community_key": "jvc",
            "project_key": "project",
            "building_id": "same",
        },
        {
            "name_key": "recoveredtower",
            "community_key": "jvc",
            "project_key": "project",
            "building_id": "same",
        },
    ]
    assert match_owner_evidence([candidate], {"aliases": aliases, "sales": [observed]}) == {}
    assert candidate.evidence["sales_lookup"]["status"] == "unit_not_observed"


def test_blank_procedure_does_not_override_an_explicit_unknown_family():
    candidate = contact(procedure="", evidence={"event_family": "unknown"})
    assert (
        annotate_source_lifecycle([candidate], policy="dated-parties")[0]["as_of_file"]
        != "possible_as_of_file"
    )
    _apply_evidence(candidate, sales={candidate.property_key: [registry(candidate)]}, rentals={})
    assert candidate.ownership_status == "unit_linked_unverified"
    assert "registry_inferred_sale" not in candidate.evidence


def test_rematched_source_audit_rows_resolve_their_import_scope():
    # Rematch rebuilds candidates from stored claims: a source-audited row carries its import only
    # as ``source_import_scope``, and lifecycle annotation must not need a claim's import_id.
    row = contact(
        evidence={
            "event_family": "sale",
            "source_import_scope": "20",
            "source_audit": {"mode": "source_only", "reference_id": "ref-7"},
        }
    )
    annotate_source_lifecycle([row])
    assert "unresolved_property_identity" not in row.evidence["source_lifecycle"]["flags"]
