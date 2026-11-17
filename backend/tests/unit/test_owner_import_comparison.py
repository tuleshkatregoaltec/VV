"""Controlled comparisons must preserve the same private source population in both arms."""

import copy
import io
from datetime import date
from unittest.mock import AsyncMock

import openpyxl
import pytest

from app.crm import owner_assessment, owner_queries
from app.crm.identity import ParsedContact
from scripts.crm import compare_owner_import as comparison


def contact(number=2, **changes):
    values = dict(
        source_sheet="PRIVATE_SHEET",
        source_row_number=number,
        contact_name="PRIVATE_PERSON",
        phone_primary="+971501234567",
        phone_alternate=None,
        email_primary="private@example.invalid",
        area_name="Business Bay",
        project_name="Executive Towers",
        building_name="Aspect Tower",
        unit_number="602",
        property_type="Apartment",
        transaction_date=date(2024, 1, 10),
        transaction_price_aed=1000000,
        party_role="Buyer",
        procedure_type="Sale",
        row_fingerprint=str(number),
        evidence={
            "event_family": "sale",
            "source_fields": {"size_sqft": "1000"},
            "nested": {"levels": [{"value": "PRIVATE_NESTED"}]},
        },
    )
    return ParsedContact(**{**values, **changes})


def baseline(*contacts):
    return comparison.freeze(b"original workbook bytes", list(contacts))


def bundle(*sales):
    base_sale = dict(
        transaction_date=date(2024, 1, 10),
        sale_amount_aed=1000000,
        size_sqft=1000,
        sale_key="sale-a",
        unit_number="602",
        building_name="Aspect Tower",
        project_name="Executive Towers",
        area_name="Business Bay",
        property_type="Apartment",
    )
    return comparison.canonical({"aliases": [], "sales": [base_sale, *sales]})


def test_baseline_retains_bytes_and_independent_deep_evidence():
    original = contact()
    frozen = baseline(original)
    first, second = frozen.candidates(), frozen.candidates()
    first[0].evidence["nested"]["levels"][0]["value"] = "changed"
    original.evidence["nested"]["levels"].clear()
    assert second[0].evidence["nested"]["levels"][0]["value"] == "PRIVATE_NESTED"
    assert frozen.original_bytes == b"original workbook bytes"
    assert frozen.candidates()[0].transaction_date == date(2024, 1, 10)


def test_a_cannot_enrich_or_use_cache_repository_or_assessment(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Arm A consulted enriched ownership machinery")

    from app.crm import owner_repository
    from scripts.crm import audit_owner_import

    for module, name in [
        (audit_owner_import, "resolve_candidates"),
        (owner_assessment, "_build"),
        (owner_assessment, "get_owner_assessment"),
        (owner_assessment, "_finish_assessment"),
        (owner_repository, "list_owner_history_rows"),
        (owner_assessment, "capture_owner_evidence"),
    ]:
        monkeypatch.setattr(module, name, forbidden)
    assert comparison.source_arm(baseline(contact()))[0]["status"] == "current_as_of_file_inferred"


def test_b_uses_only_captured_bundle_preserves_v5_scores_and_is_repeatable(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Arm B refetched source/evidence")

    monkeypatch.setattr(owner_queries, "fetch_assessment_sales", forbidden)
    monkeypatch.setattr(owner_queries, "fetch_assessment_building_aliases", forbidden)
    monkeypatch.setattr(owner_assessment, "_fresh_sales", forbidden)
    monkeypatch.setattr(owner_assessment, "_build", forbidden)
    frozen = baseline(contact())
    evidence = bundle()
    before = frozen.candidates_json
    first = comparison.registry_arm(frozen, evidence)
    assert first == comparison.registry_arm(frozen, evidence)
    assert frozen.candidates_json == before
    assert evidence == bundle()
    assert first[0]["status"] == "verified_current_owner"
    assert first[0]["confidence_score"] == 98
    assert first[0]["event_confidence_score"] == 98


def test_source_buyer_seller_pair_preserves_roles_without_calling_seller_current():
    source = baseline(contact(), contact(3, contact_name="PRIVATE_SELLER", party_role="Seller"))
    rows = comparison.source_arm(source)
    assert [row["status"] for row in rows] == [
        "current_as_of_file_inferred",
        "former_source_sale_supported",
    ]
    assert [row["role"] for row in rows] == ["Buyer", "Seller"]


@pytest.mark.parametrize(
    "change,flag,status",
    [
        ({"transaction_date": None}, "missing_date", "uncertain_source_dates"),
        ({"unit_number": ""}, "missing_property_identity", "missing_source_identity"),
    ],
)
def test_missing_source_data_never_invents_current(change, flag, status):
    row = comparison.source_arm(baseline(contact(**change)))[0]
    assert row["status"] == status
    assert flag in row["flags"]


def test_undated_other_sale_prevents_current_inference():
    rows = comparison.source_arm(baseline(contact(), contact(3, transaction_date=None)))
    assert rows[0]["status"] == "uncertain_source_dates"


def test_latest_buyer_ties_and_same_person_conflicting_roles_are_flagged():
    tied = comparison.source_arm(baseline(contact(), contact(3, contact_name="Coowner")))
    assert {row["status"] for row in tied} == {"uncertain_source_parties"}
    assert all("latest_buyer_tie_or_coowners" in row["flags"] for row in tied)
    conflict = comparison.source_arm(baseline(contact(), contact(3, party_role="Seller")))
    assert all(row["status"] == "uncertain_source_parties" for row in conflict)


@pytest.mark.parametrize(
    "family", ["gift", "inheritance", "ownership_transfer", "property_change", "financing"]
)
def test_non_sale_lifecycle_is_retained_and_blocks_current_inference(family):
    transfer = contact(
        3,
        transaction_date=date(2025, 1, 1),
        procedure_type=family,
        evidence={"event_family": family},
    )
    rows = comparison.source_arm(baseline(contact(), transfer))
    assert len(rows) == 2
    assert rows[0]["status"] == "uncertain_source_lifecycle"
    assert rows[1]["status"] == "non_sale_source_event"


def test_duplicate_source_events_are_retained_with_distinct_row_ids():
    rows = comparison.source_arm(baseline(contact(), contact(3)))
    assert len(rows) == 2
    assert len({row["row_id"] for row in rows}) == 2
    assert all("duplicate_source_event" in row["flags"] for row in rows)
    summary = comparison.reconcile(rows, copy.deepcopy(rows))
    assert summary["accepted_row_denominator"] == 2
    assert summary["fixed_source_association_denominator"] == 1
    assert sum(row["count"] for row in summary["matrix"]) == 1


def test_earlier_buyer_is_source_former_and_later_buyer_inferred():
    rows = comparison.source_arm(
        baseline(contact(), contact(3, transaction_date=date(2025, 1, 1), contact_name="New Buyer"))
    )
    assert [row["status"] for row in rows] == [
        "former_source_sale_supported",
        "current_as_of_file_inferred",
    ]


def test_later_registration_has_extent_caveat_even_with_small_amount_or_size():
    later = dict(
        transaction_date=date(2025, 1, 1),
        sale_amount_aed=100,
        size_sqft=1,
        sale_key="later",
        unit_number="602",
        building_name="Aspect Tower",
        project_name="Executive Towers",
        area_name="Business Bay",
        property_type="Apartment",
    )
    row = comparison.registry_arm(baseline(contact()), bundle(later))[0]
    assert row["disposal_extent"] == "extent_unverified"
    disposal = row["later_registrations"][0]
    assert disposal["amount_ratio_to_acquisition"] == 0.0001
    assert disposal["size_ratio_to_acquisition"] == 0.001
    assert disposal["date"] == "2025-01-01"


def test_merges_and_splits_reported_separately_from_fixed_denominator():
    a = comparison.source_arm(baseline(contact(), contact(3), contact(4, contact_name="Other")))
    b = copy.deepcopy(a)
    b[0]["property_id"] = "canonical-a"
    b[1]["property_id"] = "canonical-b"
    b[2]["property_id"] = "canonical-a"
    b[2]["person_id"] = b[0]["person_id"]
    summary = comparison.reconcile(a, b)
    assert summary["fixed_source_association_denominator"] == 2
    assert summary["identity_changes"]["property_id"]["source_identities_split"] == 1
    assert summary["identity_changes"]["person_id"]["canonical_identities_merged"] == 1
    b.pop()
    with pytest.raises(AssertionError, match="lost source rows"):
        comparison.reconcile(a, b)


def test_safe_report_never_emits_contacts_nested_evidence_or_raw_row_references():
    frozen = baseline(contact())
    a = comparison.source_arm(frozen)
    b = comparison.registry_arm(frozen, bundle())
    output = comparison.canonical(comparison.report(frozen, {}, a, b, {}, examples_page=1))
    for private in (
        "PRIVATE_PERSON",
        "PRIVATE_SHEET",
        "PRIVATE_NESTED",
        "private@example.invalid",
        "+971501234567",
    ):
        assert private not in output
    assert '"page_size":10' in output
    assert '"per_category_limit":3' in output


def test_parallel_and_sequential_arm_results_match():
    frozen = baseline(contact())
    parallel = comparison.run_arms(frozen, bundle())
    sequential = comparison.run_arms(frozen, bundle(), execution="sequential")
    assert parallel[0][0] == sequential[0][0]
    assert parallel[1][0] == sequential[1][0]
    assert parallel[0][1]["thread_cpu_seconds"] >= 0


async def test_capture_once_freezes_bundle_and_rejects_unstable_logical_snapshot(monkeypatch):
    frozen = baseline(contact())
    raw_bundle = {"aliases": [], "sales": []}
    capture = AsyncMock(return_value=raw_bundle)
    fingerprint = AsyncMock(return_value={"dxbi": {"rows": 1, "hash": "a"}})
    monkeypatch.setattr(owner_assessment, "capture_owner_evidence", capture)
    monkeypatch.setattr(
        owner_queries, "fetch_assessment_source_fingerprint", fingerprint, raising=False
    )
    evidence, metadata = await comparison.capture_evidence(frozen)
    raw_bundle["sales"].append({"unexpected": "mutation"})
    assert evidence == comparison.canonical({"aliases": [], "sales": []})
    assert metadata["publication_time_known"] is False
    assert metadata["snapshot_semantics"].endswith("not timestamp-atomic")
    capture.assert_awaited_once()
    assert fingerprint.await_count == 2
    fingerprint.side_effect = [{"rows": 1}, {"rows": 2}]
    with pytest.raises(RuntimeError, match="fingerprints changed"):
        await comparison.capture_evidence(frozen)


def test_parse_only_authorized_input_once_and_ignore_unrelated_workbooks(tmp_path, monkeypatch):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Building", "Unit", "Date", "Party Role", "Procedure Name"])
    sheet.append(["PRIVATE_PERSON", "Aspect Tower", "602", "2024-01-10", "Buyer", "Sale"])
    sheet.append([None, "Aspect Tower", "603", "2024-01-10", "Buyer", "Sale"])
    data = io.BytesIO()
    workbook.save(data)
    path = tmp_path / "authorized.xlsx"
    path.write_bytes(data.getvalue())
    unrelated = tmp_path / "unrelated.xlsx"
    unrelated.write_bytes(b"never inspect")
    monkeypatch.setattr(comparison, "AUTHORIZED_WORKBOOK", path)
    inspect, parse = import_spies(monkeypatch)
    frozen = comparison.parse_workbook(path)
    counts = comparison.json.loads(frozen.counts_json)
    assert counts["raw_physical_data_rows"] == 2
    assert counts["nonempty"] == 2
    assert counts["accepted"] == 1
    assert counts["rejected"] == 1
    provenance = comparison.json.loads(frozen.rejected_json)
    assert len(provenance) == 1
    assert provenance[0]["physical_row"] == 3
    assert provenance[0]["reason"] == "no_name"
    assert len(provenance[0]["row_id"]) == 64
    assert "PRIVATE_PERSON" not in frozen.rejected_json
    assert inspect == [path.name]
    assert parse == [path.name]
    with pytest.raises(ValueError, match="authorized workbook"):
        comparison.parse_workbook(unrelated)
    assert inspect == [path.name]


def import_spies(monkeypatch):
    inspected, parsed = [], []
    inspect = comparison.import_parsing._inspect_xlsx
    parse = comparison.import_parsing._parse_xlsx

    def inspect_once(data, filename):
        inspected.append(filename)
        return inspect(data, filename)

    def parse_once(data, filename, profiles, dropped):
        parsed.append(filename)
        return parse(data, filename, profiles, dropped)

    monkeypatch.setattr(comparison.import_parsing, "_inspect_xlsx", inspect_once)
    monkeypatch.setattr(comparison.import_parsing, "_parse_xlsx", parse_once)
    return inspected, parsed


def test_missing_identity_rows_do_not_share_unrelated_party_or_date_flags():
    rows = comparison.source_arm(
        baseline(
            contact(unit_number=""),
            contact(3, unit_number="", transaction_date=None, party_role="Seller"),
        )
    )
    assert all(row["status"] == "missing_source_identity" for row in rows)
    assert "undated_sale_on_property" not in rows[0]["flags"]
    assert "conflicting_party_roles" not in rows[0]["flags"]


def test_source_group_statistics_are_computed_linearly(monkeypatch):
    original = comparison.has_sale_evidence
    calls = 0

    def counted(candidate):
        nonlocal calls
        calls += 1
        return original(candidate)

    monkeypatch.setattr(comparison, "has_sale_evidence", counted)
    count = 200
    rows = comparison.source_arm(baseline(*(contact(number) for number in range(2, count + 2))))
    assert len(rows) == count
    assert calls <= 4 * count


def test_source_and_b_use_same_contactless_person_scope_across_areas():
    frozen = baseline(
        contact(phone_primary=None, email_primary=None),
        contact(3, phone_primary=None, email_primary=None, area_name="Different Area"),
    )
    a = comparison.source_arm(frozen)
    b = comparison.registry_arm(frozen, comparison.canonical({"aliases": [], "sales": []}))
    assert len({row["person_id"] for row in a}) == 2
    assert [row["person_id"] for row in a] == [row["person_id"] for row in b]
    result = comparison.reconcile(a, b)
    assert result["identity_changes"]["person_id"]["source_identities_split"] == 0
    assert result["identity_changes"]["person_id"]["canonical_identities_merged"] == 0


def test_shared_phone_does_not_merge_people_with_different_names():
    rows = comparison.source_arm(baseline(contact(), contact(3, contact_name="Different Person")))
    assert len({row["person_id"] for row in rows}) == 2


@pytest.mark.parametrize(
    "building,unit", [("unknown", "602"), ("Aspect Tower", "unknown"), ("Aspect Tower", "-")]
)
def test_source_reuses_application_property_placeholder_validation(building, unit):
    row = comparison.source_arm(
        baseline(contact(building_name=building, project_name="", unit_number=unit))
    )[0]
    assert row["status"] == "missing_source_identity"
    assert row["property_id"] is None


def test_incompatible_project_scopes_cannot_infer_current_owner():
    rows = comparison.source_arm(baseline(contact(), contact(3, project_name="Different Project")))
    assert all("incompatible_project_scope" in row["flags"] for row in rows)
    assert all(row["status"] == "uncertain_source_parties" for row in rows)


def test_latest_tied_buyer_uncertainty_overrides_older_seller_on_source_relationship():
    frozen = baseline(
        contact(party_role="Seller", transaction_date=date(2023, 1, 1)),
        contact(3),
        contact(4, contact_name="Other Buyer"),
    )
    a = comparison.source_arm(frozen)
    b = comparison.registry_arm(frozen, bundle())
    result = comparison.reconcile(a, b)
    assert a[0]["status"] == "former_source_sale_supported"
    assert a[1]["status"] == "uncertain_source_parties"
    assert not any(row["a"] == "former_source_sale_supported" for row in result["matrix"])
    assert result["a"]["event_categories"]["former_source_sale_supported"] == 1
    assert result["a"]["relationship_categories"] == {"uncertain_source_parties": 2}


def test_ratios_use_exact_matched_sale_key_when_other_registration_shares_date():
    acquisition = dict(
        transaction_date=date(2024, 1, 10),
        sale_amount_aed=1000000,
        size_sqft=1000,
        sale_key="true-acquisition",
        unit_number="602",
        building_name="Aspect Tower",
        project_name="Executive Towers",
        area_name="Business Bay",
        property_type="Apartment",
    )
    unrelated = {
        **acquisition,
        "sale_key": "other-same-date",
        "sale_amount_aed": 3000000,
        "size_sqft": 2000,
    }
    later = {
        **acquisition,
        "sale_key": "later-sale",
        "transaction_date": date(2025, 1, 1),
        "sale_amount_aed": 2000000,
        "size_sqft": 1000,
    }
    evidence = comparison.canonical({"aliases": [], "sales": [unrelated, acquisition, later]})
    result = comparison.registry_arm(baseline(contact()), evidence)[0]
    assert result["matched_sale_id"] == comparison.digest("true-acquisition")
    assert result["matched_sale_amount_aed"] == 1000000
    assert result["later_registrations"][0]["amount_ratio_to_acquisition"] == 2
    assert result["later_registrations"][0]["size_ratio_to_acquisition"] == 1
    assert result["later_registrations"][0]["sale_id"] == comparison.digest("later-sale")
    assert result["disposal_extent"] == "extent_unverified"
    assert comparison._counts([result])["extent_unverified_relationships"] == 1


def test_rematching_unmatched_claim_clears_stale_acquisition_key():
    from app.crm.ownership import _apply_evidence

    candidate = contact(
        evidence={
            "event_family": "sale",
            "matched_sale_key": "stale",
            "matched_sale_date": "2020-01-01",
        }
    )
    _apply_evidence(candidate, sales={}, rentals={})
    assert "matched_sale_key" not in candidate.evidence
    assert "matched_sale_date" not in candidate.evidence


def test_examples_show_properties_and_unique_relationships_without_contact_data():
    frozen = baseline(contact(), contact(3))
    a = comparison.source_arm(frozen)
    b = comparison.registry_arm(frozen, bundle())
    result = comparison.report(frozen, {}, a, b, {}, examples_page=1)
    samples = result["examples"]["rows"]
    assert len(samples) == 1
    assert samples[0]["a"]["property"]["building_name"] == "Aspect Tower"
    assert samples[0]["a"]["property"]["unit_number"] == "602"
    assert samples[0]["a"]["physical_row"] in {2, 3}
    assert samples[0]["b"]["matched_sale_amount_aed"] == 1000000
    assert result["assessment_version"] == owner_assessment.ASSESSMENT_VERSION
    assert "Import identity recovery" in result["b_scope"]


def test_source_person_uses_canonical_name_spelling_rules_consistently_with_b():
    frozen = baseline(contact(), contact(3, contact_name="private person"))
    a = comparison.source_arm(frozen)
    b = comparison.registry_arm(frozen, bundle())
    assert len({row["person_id"] for row in a}) == 1
    assert [row["person_id"] for row in a] == [row["person_id"] for row in b]


def snapshot_contact(number=2, **changes):
    return contact(
        number, procedure_type="", evidence={"event_family": "contact_snapshot"}, **changes
    )


def test_strict_keeps_source_snapshot_semantics_but_exact_registry_can_corroborate_sale():
    frozen = baseline(snapshot_contact())
    source_before = frozen.candidates_json
    assert comparison.source_arm(frozen) == comparison.source_arm(frozen, "strict")
    assert comparison.registry_arm(frozen, bundle()) == comparison.registry_arm(
        frozen, bundle(), "strict"
    )
    assert comparison.source_arm(frozen)[0]["status"] == "non_sale_source_event"
    corroborated = comparison.registry_arm(frozen, bundle())[0]
    assert corroborated["status"] == "verified_current_owner"
    assert corroborated["event_family"] == "contact_snapshot"
    assert corroborated["source_semantics_inference"] is None
    assert (
        comparison.registry_arm(frozen, comparison.canonical({"aliases": [], "sales": []}))[0][
            "status"
        ]
        != "verified_current_owner"
    )
    assert frozen.candidates_json == source_before
    assert frozen.candidates()[0].evidence == {"event_family": "contact_snapshot"}
    assert frozen.candidates()[0].procedure_type == ""


def test_opt_in_policy_uses_same_source_population_and_preserves_parser_provenance():
    frozen = baseline(snapshot_contact())
    original_payload = frozen.candidates_json
    strict_a = comparison.source_arm(frozen)
    strict_b = comparison.registry_arm(frozen, bundle())
    a = comparison.source_arm(frozen, "dated-parties")
    b = comparison.registry_arm(frozen, bundle(), "dated-parties")
    assert a[0]["row_id"] == strict_a[0]["row_id"] == b[0]["row_id"] == strict_b[0]["row_id"]
    assert a[0]["person_id"] == strict_a[0]["person_id"] == b[0]["person_id"]
    assert a[0]["property_id"] == strict_a[0]["property_id"] == b[0]["property_id"]
    assert a[0]["status"] == "current_as_of_file_inferred"
    assert b[0]["status"] == "verified_current_owner"
    assert b[0]["confidence_score"] == 98
    for row in (a[0], b[0]):
        assert row["parsed_event_family"] == "contact_snapshot"
        assert row["event_family"] == "sale"
        assert "source_event_family_inferred" in row["flags"]
        assert row["source_semantics_inference"]["raw_procedure_type"] == ""
        assert row["source_semantics_inference"]["legal_ownership_proof"] is False
    assert a[0]["source_semantics_inference"] == b[0]["source_semantics_inference"]
    assert b[0]["source_evidence_sha256"] == comparison.digest({"event_family": "contact_snapshot"})
    assert frozen.candidates_json == original_payload
    assert frozen.candidates()[0].evidence["event_family"] == "contact_snapshot"
    result = comparison.report(frozen, {}, a, b, {}, source_semantics="dated-parties")
    assert result["source_semantics"]["inferred_rows_a"] == 1
    assert result["source_semantics"]["inferred_rows_b"] == 1
    assert result["source_semantics"]["policy"] == "dated-parties"
    assert result["source_semantics"]["legal_ownership_proof"] is False
    assert result["comparison"]["accepted_row_denominator"] == 1


@pytest.mark.parametrize(
    "family,procedure",
    [
        ("unknown", ""),
        ("unknown", "Ambiguous registration"),
        ("gift", "Gift"),
        ("financing", "Mortgage"),
        ("ownership_transfer", "Ownership transfer"),
        ("inheritance", "Inheritance"),
        ("contact_snapshot", "Mortgage"),
        ("contact_snapshot", "Sale"),
    ],
)
def test_opt_in_never_overrides_explicit_or_unknown_procedure_semantics(family, procedure):
    frozen = baseline(contact(procedure_type=procedure, evidence={"event_family": family}))
    a = comparison.source_arm(frozen, "dated-parties")
    b = comparison.registry_arm(frozen, bundle(), "dated-parties")
    assert a[0]["event_family"] == family
    assert b[0]["event_family"] == family
    assert a[0]["source_semantics_inference"] is None
    assert b[0]["source_semantics_inference"] is None
    assert a[0]["status"] == "non_sale_source_event"
    assert b[0]["status"] != "verified_current_owner"


@pytest.mark.parametrize(
    "changes",
    [
        {"transaction_date": None},
        {"transaction_price_aed": None},
        {"transaction_price_aed": 0},
        {"transaction_price_aed": -1},
        {"party_role": "Unknown"},
        {"transaction_price_aed": float("inf")},
    ],
)
def test_opt_in_requires_valid_date_positive_finite_amount_and_buyer_seller(changes):
    frozen = baseline(snapshot_contact(**changes))
    a = comparison.source_arm(frozen, "dated-parties")
    b = comparison.registry_arm(frozen, bundle(), "dated-parties")
    assert a[0]["event_family"] == b[0]["event_family"] == "contact_snapshot"
    assert a[0]["source_semantics_inference"] is None
    assert b[0]["source_semantics_inference"] is None
    assert a[0]["status"] == "non_sale_source_event"


def test_opt_in_seller_stays_source_former_and_keeps_inference_flag():
    frozen = baseline(snapshot_contact(party_role="Seller"))
    row = comparison.source_arm(frozen, "dated-parties")[0]
    assert row["role"] == "Seller"
    assert row["status"] == "former_source_sale_supported"
    assert row["source_semantics_inference"]["legal_ownership_proof"] is False


def test_opt_in_policy_parallel_and_sequential_results_are_identical():
    frozen = baseline(
        snapshot_contact(), snapshot_contact(3, party_role="Seller", contact_name="Other")
    )
    parallel = comparison.run_arms(frozen, bundle(), source_semantics="dated-parties")
    sequential = comparison.run_arms(
        frozen, bundle(), execution="sequential", source_semantics="dated-parties"
    )
    assert parallel[0][0] == sequential[0][0]
    assert parallel[1][0] == sequential[1][0]


def test_source_counts_distinguish_duplicate_groups_extra_rows_and_complementary_parties():
    frozen = comparison.freeze(
        b"original",
        [contact(), contact(3), contact(4), contact(5, party_role="Seller", contact_name="Seller")],
        counts={"raw_physical_data_rows": 9, "nonempty": 4, "accepted": 4, "rejected": 0},
    )
    a = comparison.source_arm(frozen)
    b = comparison.registry_arm(frozen, bundle())
    result = comparison.report(frozen, {}, a, b, {})
    assert result["source_counts"]["blank_or_formatting_rows"] == 5
    assert result["duplicate_events_retained"] == 3
    assert result["duplicate_groups"] == 1
    assert result["duplicate_extra_rows"] == 2
    assert result["distinct_nonduplicate_event_count"] == 2


@pytest.mark.parametrize("counts", [{"nonempty": 3}, {"raw_physical_data_rows": 1, "nonempty": 3}])
def test_blank_count_is_not_invented_when_physical_accounting_unknown_or_inconsistent(counts):
    frozen = comparison.freeze(b"original", [contact()], counts=counts)
    a = comparison.source_arm(frozen)
    b = comparison.registry_arm(frozen, bundle())
    result = comparison.report(frozen, {}, a, b, {})
    assert "blank_or_formatting_rows" not in result["source_counts"]
