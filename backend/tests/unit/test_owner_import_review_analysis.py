"""Review diagnostics preserve missing evidence, contradictions, and raw-row intent."""

import pytest

from scripts.crm import analyze_owner_import_review as review


def diagnostic(**changes):
    values = {
        "any_original_identifier": True,
        "amount_present": True,
        "sale_price_pool_events": 100,
        "original_role_disagreement_events": 0,
        "qualified_before_raw": 0,
        "qualified_candidates": 0,
        "id_compatible_events": 10,
        "scoped_events": 5,
        "id_scoped_events": 0,
        "id_scope_type_events": 0,
        "precise_location_labels": ["testtower"],
        "catalog_named_label_found": True,
        "selection_status": "no_supported_candidates",
    }
    return {**values, **changes}


def test_original_contradiction_cannot_be_overruled_by_amount_size_or_date():
    values = diagnostic(
        raw_address_conflict=True,
        normalized_projection_conflict=True,
        selection_status="selected",
    )
    assert review.primary_cause(values) == "original_address_codes_contradict"
    values["raw_address_conflict"] = False
    assert review.primary_cause(values) == "normalized_identifier_disagrees_original"


def test_missing_original_id_is_distinct_from_no_matching_sale():
    assert review.primary_cause(diagnostic(any_original_identifier=False)) == (
        "no_original_role_correct_full_identifier"
    )
    assert review.primary_cause(diagnostic(sale_price_pool_events=0)) == (
        "no_captured_sale_within_2_aed"
    )


def test_identified_property_without_sale_is_not_a_property_identity_failure():
    assert (
        review.primary_cause(
            diagnostic(supported_property=True, identified_property_sale_price_events=0)
        )
        == "identified_property_no_sale_within_2_aed"
    )
    assert (
        review.primary_cause(
            diagnostic(supported_property=True, identified_property_sale_price_events=1)
        )
        != "identified_property_no_sale_within_2_aed"
    )


@pytest.mark.parametrize(
    ("status", "cause"),
    [
        ("unknown_target_size_prevents_mandatory_size_validation", "target_size_missing"),
        ("size_disagrees_all_supported_candidates", "source_size_disagrees_all_candidates"),
        ("multiple_properties_no_independent_size", "multiple_physical_properties"),
        ("unresolved_multiple_events", "multiple_sale_registrations"),
    ],
)
def test_actual_supported_candidate_failure_survives_unrelated_pool_failures(status, cause):
    # Broad-pool ID/location failures do not explain why a qualified pool failed.
    values = diagnostic(selection_status=status, qualified_candidates=3)
    assert review.primary_cause(values) == cause


def test_parent_building_role_hypothesis_does_not_become_confirmed_identity():
    values = diagnostic(original_role_disagreement_events=2)
    assert review.primary_cause(values) == "original_building_unit_roles_disagree"
    assert "original_building_unit_role_reinterpretation_unverified" in review.make_flags(values)


def test_multiple_observed_problems_remain_overlapping_secondary_flags():
    values = diagnostic(
        raw_address_conflict=True,
        source_property_conflict=True,
        source_size_unit_unknown=True,
    )
    assert review.primary_cause(values) == "original_address_codes_contradict"
    assert {"raw_address_conflict", "source_property_conflict", "source_size_unit_unknown"} <= set(
        review.make_flags(values)
    )


def test_unexplained_frozen_selection_exclusion_is_not_silently_reported_as_solved():
    assert review.primary_cause(diagnostic(selection_status="selected")) == (
        "unexplained_final_profile_exclusion"
    )


def test_contact_and_owner_values_cannot_escape_property_evidence_allowlist():
    row = {
        "unit_number": "A-101",
        "building_name": "Example Tower",
        "owner_name": "PRIVATE_OWNER",
        "phone": "PRIVATE_PHONE",
        "email": "PRIVATE_EMAIL",
        "parties": [{"name": "PRIVATE_PARTY"}],
        "evidence": {"name": "PRIVATE_NESTED"},
    }
    assert review.property_only(row) == {"unit_number": "A-101", "building_name": "Example Tower"}
    assert "PRIVATE" not in str(review.property_only(row))


@pytest.mark.parametrize("text", ["=1+1", "+123", "-1+2", "@SUM(A1)"])
def test_spreadsheet_examples_cannot_execute_source_cells(text):
    assert review.excel_value(text) == "'" + text


def test_diagnostic_tree_groups_duplicate_properties_and_files_before_holdout():
    pytest.importorskip("numpy")
    records = []
    for group in range(5):
        for event in range(90):
            # Two files in one group share a property and must stay in one split.
            files = [f"property-{group}.xlsx"]
            if group == 0:
                files.append("duplicate-property-0.xlsx")
            features = [0] * 13
            features[0] = int(event >= 45)
            records.append(
                {
                    "source_event_id": f"{group}-{event}",
                    "source_unit_id": f"unit-{group}-{event}",
                    "filenames": files,
                    "model_property_groups": [["scope", f"building-{group}", str(event)]],
                    "model_features": features,
                    "raw_row_count": 2,
                    "primary_cause": "missing_id" if event < 45 else "size_conflict",
                }
            )
    result = review.diagnostic_model(records)
    assert result["status"] == "fit"
    assert result["split"]["all_file_property_unit_event_components_disjoint"]
    assert result["test_rule_label_agreement"] == 1
    assert result["test_training_majority_baseline_agreement"] == 0.5
    assert result["new_qualified_owner_evidence"] == 0
    assert result["tree"]["feature"] == "original_unit_present"
    train = set(result["split"]["train_files"])
    assert ("property-0.xlsx" in train) == ("duplicate-property-0.xlsx" in train)


@pytest.mark.parametrize("blocked_by", ["uncertain", "existing_property_conflict"])
def test_ineligible_reference_cannot_create_a_hypothetical_reverse_competitor(tmp_path, blocked_by):
    from collections import defaultdict
    from types import SimpleNamespace

    rules_file = tmp_path / "frozen_rules.py"
    rules_file.write_text("""
def raw_authority(eid, row):
    return True, []
def select(event, candidates, mode):
    return ({"row": candidates[0]["row"]}, "selected")
def idv(source, field):
    return str(source.get(field) or "")
def child_plot_villa(source, target):
    return False
def reuse_conflicts(proposed):
    by_key = {}
    for eid, row in proposed.items():
        by_key.setdefault(row["event_key"], set()).add(events[eid]["uid"])
    return {key for key, units in by_key.items() if len(units) > 1}
""")
    events = {
        "good": {"uid": "unit-good", "source": {"property_type": "villa"}},
        "blocked": {"uid": "unit-blocked", "source": {"property_type": "villa"}},
    }
    units = {
        "unit-good": {"identity": ["villa_reference"], "uncertain": False},
        "unit-blocked": {"identity": ["villa_reference"], "uncertain": blocked_by == "uncertain"},
    }
    captured = defaultdict(set)
    if blocked_by == "existing_property_conflict":
        captured["unit-blocked"] = {("area", "tower-one", "101"), ("area", "tower-two", "101")}
    rules = {
        "events": events,
        "frozen_function_source": rules_file,
        "frozen_function_names": {
            "raw_authority",
            "select",
            "idv",
            "child_plot_villa",
            "reuse_conflicts",
        },
    }
    matcher = SimpleNamespace(
        _kind=lambda value: value, property_identity=lambda row: ("area", "tower", "101")
    )
    cache = {
        eid: [{"row": {"event_key": "same-event", "property_type": "villa"}}] for eid in events
    }
    accepted, reasons, _, _ = review.replay_prior_selection(
        events, units, captured, cache, rules, matcher
    )
    assert accepted == {"good": "same-event"}
    expected_reason = (
        "uncertain_villa_reference"
        if blocked_by == "uncertain"
        else "existing_source_reference_property_conflict"
    )
    assert reasons["blocked"] == expected_reason
