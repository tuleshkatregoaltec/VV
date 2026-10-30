#!/usr/bin/env python3
"""Offline SAME9 review diagnostics; no CRM writes, network, or contact exports.

Replay the exact frozen experimental eligibility/selection functions, rather than
using their previous first-failure labels. Inputs are explicit CLI paths. Run with
backend's existing Python environment; outputs contain property evidence only.
"""

from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import importlib.util
import json
import math
import re
import sqlite3
import sys
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from typing import Any

SQM = 10.76391041671
FIELDS = ("building_name", "project_name", "area_name")
PROPERTY_FIELDS = (
    *FIELDS,
    "unit_number",
    "building_number",
    "plot_number",
    "property_number",
    "property_type",
    "amount_aed",
    "transaction_date",
    "size_sqft",
    "size_unknown",
)
CATEGORY_DESCRIPTIONS = {
    "owner_buyer_seller_same_last_day": "Same source name/property association has both buyer and seller roles on its own last observed day.",
    "owner_latest_registration_not_unique": "Matched property has several distinct latest-day sale registrations; ownership timeline is not unique.",
    "original_address_codes_contradict": "Original full R3 address codes or explicit child numbers disagree; normalized projection cannot settle them.",
    "normalized_identifier_disagrees_original": "Original complete R3 building address supports a different number than the normalized source unit; repair remains review only.",
    "no_original_role_correct_full_identifier": "No original supported identifier for the observed physical role; a derived field, parent plot, or unrelated number cannot supply it.",
    "source_sale_amount_missing": "Source sale amount is absent/nonpositive, preventing a sale consideration comparison.",
    "identified_property_no_sale_within_2_aed": "Independent supported property identity exists, but its captured sale history has no consideration within +/-2 AED.",
    "no_captured_sale_within_2_aed": "Entire captured sale-family pool has no event within +/-2 AED; rental matches do not replace sales.",
    "original_building_unit_roles_disagree": "An original explicit child UnitNo matches a qualified villa candidate, but original BuildingNo vetoes it; a parent-role reinterpretation is unverified.",
    "source_reference_maps_multiple_properties": "A single source property reference retains conflicting physical property identities across source events or earlier captured matches.",
    "incompatible_reverse_event_reuse": "Different source references with incompatible full IDs/building qualifiers compete for the same registry sale event.",
    "source_reference_identity_uncertain": "A candidate exists but frozen source-reference grouping remains uncertain and has no permitted plot/child exception.",
    "target_size_missing": "A learned source size unit applies, but at least one supported target has unknown size; unknown targets cannot be dropped to force uniqueness.",
    "source_size_disagrees_all_candidates": "Source size with independently inferred units disagrees with every original-ID/location/type-supported candidate.",
    "multiple_physical_properties": "Several physical properties remain; without independent size corroboration exact date alone cannot select a property.",
    "multiple_sale_registrations": "Several eligible sale event keys remain after permitted size and exact-date checks, including nearby competitor registrations.",
    "named_location_broad_or_unqualified": "Source has only broad/generic location evidence and no candidate satisfies the qualified location gate.",
    "named_location_label_absent_catalog": "No source precise building/project label has an exact vetted-normalized entry in the captured place catalog, and no qualified sale candidate exists. An alias is possible, unproven.",
    "named_location_mismatch_or_unvetted_alias": "Full-ID candidates exist, but source named scope/geography fails qualified matching; no approved alias bridges the difference.",
    "full_identifier_not_in_same_price_scoped_sales": "Same-price sales exist in the named scope, but no original full identifier jointly agrees.",
    "full_identifier_not_in_same_price_sales": "Original full identifier is supplied but no same-price sale has compatible full identifiers; other missing gates remain secondary flags.",
    "physical_type_or_land_child_conflict": "ID/location candidates fail physical-type or explicit plot-to-villa child-identity requirements.",
    "target_metadata_or_location_review": "Candidates retain missing property identity, geography, or generic-building review requirements.",
    "unexplained_final_profile_exclusion": "Selection replay found an otherwise eligible event missing from the frozen final index; verification must fail until explained.",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def digest(value: Any) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
    path.chmod(0o600)


def property_only(row: dict) -> dict:
    return {key: row.get(key) for key in PROPERTY_FIELDS if row.get(key) is not None}


def excel_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def primary_cause(diagnostic: dict) -> str:
    """Deterministic primary attribution; all other observed failures stay flags.

    Contradictory original evidence, absent original role authority, and missing
    amount precede candidate comparisons. Supported candidate selection failures
    take precedence over unrelated broad-pool failures. Location/identifier/type
    categories describe joint observed evidence, never a guessed true property.
    """
    d = diagnostic
    if d.get("owner_cause"):
        return d["owner_cause"]
    if d.get("raw_address_conflict"):
        return "original_address_codes_contradict"
    if d.get("normalized_projection_conflict"):
        return "normalized_identifier_disagrees_original"
    if not d["any_original_identifier"]:
        return "no_original_role_correct_full_identifier"
    if not d["amount_present"]:
        return "source_sale_amount_missing"
    status = d.get("selection_status")
    if status == "unknown_target_size_prevents_mandatory_size_validation":
        return "target_size_missing"
    if status == "size_disagrees_all_supported_candidates":
        return "source_size_disagrees_all_candidates"
    if status == "multiple_properties_no_independent_size":
        return "multiple_physical_properties"
    if status == "unresolved_multiple_events":
        return "multiple_sale_registrations"
    if status == "selected":
        if d.get("source_reference_uncertainty_blocks_selection"):
            return "source_reference_identity_uncertain"
        if d.get("reverse_reuse_conflict"):
            return "incompatible_reverse_event_reuse"
        if d.get("source_property_conflict_blocks_selection", d.get("source_property_conflict")):
            return "source_reference_maps_multiple_properties"
        return "unexplained_final_profile_exclusion"
    if d.get("supported_property") and not d.get("identified_property_sale_price_events"):
        return "identified_property_no_sale_within_2_aed"
    if not d["sale_price_pool_events"]:
        return "no_captured_sale_within_2_aed"
    if d["original_role_disagreement_events"]:
        return "original_building_unit_roles_disagree"
    if d["qualified_before_raw"] and not d["qualified_candidates"]:
        return "no_original_role_correct_full_identifier"
    if d["id_scoped_events"] and not d["id_scope_type_events"]:
        return "physical_type_or_land_child_conflict"
    if d["id_scope_type_events"]:
        return "target_metadata_or_location_review"
    if not d["precise_location_labels"]:
        return "named_location_broad_or_unqualified"
    if not d["catalog_named_label_found"] and not d["scoped_events"]:
        return "named_location_label_absent_catalog"
    if d["id_compatible_events"]:
        return "named_location_mismatch_or_unvetted_alias"
    if d["scoped_events"]:
        return "full_identifier_not_in_same_price_scoped_sales"
    return "full_identifier_not_in_same_price_sales"


def make_flags(d: dict) -> list[str]:
    flags = []
    for key in (
        "raw_address_conflict",
        "normalized_projection_conflict",
        "source_property_conflict",
        "reverse_reuse_conflict",
        "source_reference_uncertain",
        "source_size_unit_unknown",
        "explicit_source_size_missing",
        "raw_original_unit_absent",
        "raw_original_building_absent",
        "supported_property",
        "owner_buyer_seller_both_roles",
        "owner_latest_multiple_events",
    ):
        if d.get(key):
            flags.append(key)
    for key in ("amount_present", "any_original_identifier", "catalog_named_label_found"):
        if not d.get(key, True):
            flags.append("missing_" + key)
    for key in (
        "sale_price_pool_events",
        "id_compatible_events",
        "scoped_events",
        "id_scoped_events",
        "id_scope_type_events",
        "qualified_candidates",
    ):
        if key in d and not d[key]:
            flags.append("zero_" + key)
    if d.get("original_role_disagreement_events"):
        flags.append("original_building_unit_role_reinterpretation_unverified")
    if d.get("source_size_unit_unknown"):
        flags.append("size_inference_abstained_not_evidence_of_size_agreement")
    if d.get("same_price_rental_events"):
        flags.append("same_price_rental_not_sale_evidence")
    if d.get("qualified_physical_properties", 0) > 1:
        flags.append("multiple_supported_physical_properties_before_size")
    if d.get("selection_status"):
        flags.append("selection_" + d["selection_status"])
    return sorted(set(flags))


def load_frozen_rules(args, events: dict, raw_mask: dict):
    # Import only the captured app tree; concurrent app implementation is excluded.
    baseline = args.backend_baseline.resolve()
    if not (baseline / "app/crm/transaction_matching.py").is_file():
        raise ValueError("--backend-baseline must contain the captured app tree")
    sys.path.insert(0, str(baseline))
    from app.crm import transaction_matching as tm
    from app.crm.registry_locations import _area_key, _place_key

    if not Path(tm.__file__).resolve().is_relative_to(baseline):
        raise ValueError("transaction matcher was imported from outside --backend-baseline")
    spec = importlib.util.spec_from_file_location(
        "owner_review_frozen_r3", args.experiments / "namespace-experiment/r3_namespace.py"
    )
    namespace = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(namespace)

    class MatcherProxy:
        property_identity = staticmethod(namespace.canonical_identity)

        def __getattr__(self, name):
            return getattr(tm, name)

    places = load(args.corpus / "places-snapshot.json")
    ns = {
        "tm": MatcherProxy(),
        "re": re,
        "_place_key": _place_key,
        "_area_key": _area_key,
        "FIELDS": FIELDS,
        "SQM": SQM,
        "events": events,
        "raw_mask": raw_mask,
        "defaultdict": collections.defaultdict,
        "combinations": combinations,
        "place_exact": {
            (
                _place_key(p.get("building_label")),
                _place_key(p.get("project_label")),
                _area_key(p.get("area_label")),
            )
            for p in places
        },
    }
    functions = {
        "idv",
        "raw_authority",
        "child_plot_villa",
        "ids_fit",
        "generic_marker",
        "hierarchy",
        "candidate",
        "infer",
        "select",
        "reuse_conflicts",
    }
    source = args.experiments / "experiment/run.py"
    found = set()
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in functions:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), ns)
            found.add(node.name)
    assert found == functions
    anchors = collections.defaultdict(lambda: collections.defaultdict(set))
    for row in load(args.experiments / "experiment/size-anchor-pairs.json"):
        for fs in row["file_sheets"]:
            anchors[tuple(fs)][row["unit_vote"]].add(row["source_unit_id"])
    ns["anchor_totals"] = {fs: set().union(*votes.values()) for fs, votes in anchors.items()}
    ns["anchor_exclusive"] = {
        fs: {
            label: ids
            - set().union(*(other for other_label, other in votes.items() if other_label != label))
            for label, ids in votes.items()
        }
        for fs, votes in anchors.items()
    }
    ns["frozen_function_source"] = source
    ns["frozen_function_names"] = functions
    return tm, namespace, ns, places, _place_key, _area_key


def replay_prior_selection(events, units, captured_links, cache, rules, matcher):
    """Rebuild every old proposal before reverse-use/cross-event vetoes.

    Uncertain references and pre-existing conflicts must be removed BEFORE
    computing competing proposals, exactly as the frozen learned_units profile.
    """
    old = {**rules, "tm": matcher}
    source = rules["frozen_function_source"]
    names = rules["frozen_function_names"]
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), old)
    proposed = {}
    rejection = {}
    selection_statuses = {}
    for eid, event in events.items():
        candidates = [c for c in cache[eid] if old["raw_authority"](eid, c["row"])[0]]
        picked, status = old["select"](event, candidates, "learned_units")
        selection_statuses[eid] = status
        if not picked:
            rejection[eid] = status
            continue
        row = picked["row"]
        source = event["source"]
        unit = units[event["uid"]]
        uncertain_exception = unit["identity"][0] == "plot_reference" and (
            (
                matcher._kind(row.get("property_type")) == "plot"
                and old["idv"](source, "plot_number") == old["idv"](row, "unit_number")
            )
            or old["child_plot_villa"](source, row)
        )
        if unit["uncertain"] and not uncertain_exception:
            rejection[eid] = "uncertain_" + unit["identity"][0]
            continue
        if len(captured_links[event["uid"]]) > 1:
            rejection[eid] = "existing_source_reference_property_conflict"
            continue
        proposed[eid] = row
    reverse_bad = old["reuse_conflicts"](proposed)
    properties = collections.defaultdict(set)
    for eid, row in proposed.items():
        properties[events[eid]["uid"]].add(matcher.property_identity(row))
    for uid, identities in captured_links.items():
        properties[uid] |= identities
    accepted = {}
    for eid, row in proposed.items():
        if row["event_key"] in reverse_bad:
            rejection[eid] = "incompatible_reverse_event_reuse"
        elif len(properties[events[eid]["uid"]]) > 1:
            rejection[eid] = "source_reference_property_conflict"
        else:
            accepted[eid] = row["event_key"]
    return accepted, rejection, selection_statuses, properties


def diagnostic_model(records: list[dict]) -> dict:
    """Small CART classifier of diagnostic labels from source-only predictors.

    Entire connected file/property components are held out. Neither candidate
    counts, gate flags, source IDs, file names nor labels are predictor features.
    Test agreement measures imitation of deterministic diagnostics, not truth.
    """
    import numpy as np

    parent = {}

    def find(item):
        parent.setdefault(item, item)
        if parent[item] != item:
            parent[item] = find(parent[item])
        return parent[item]

    def union(a, b):
        left, right = find(a), find(b)
        if left != right:
            parent[max(left, right)] = min(left, right)

    for record in records:
        root = "u:" + record["source_unit_id"]
        for filename in record["filenames"]:
            union(root, "f:" + filename)
        for identity in record.get("model_property_groups", []):
            union(root, "p:" + digest(tuple(identity)))
    components = {r["source_event_id"]: find("u:" + r["source_unit_id"]) for r in records}
    groups = sorted(set(components.values()), key=digest)
    common = {
        "purpose": "Describe which SOURCE structural features predict rule-derived review labels; zero owner promotions.",
        "labels": "Deterministic gate diagnostics, not human-verified causes or ownership truth.",
        "features": [
            "original_unit_present",
            "original_building_present",
            "original_plot_present",
            "original_property_present",
            "source_unit_alphanumeric",
            "source_building_alphanumeric",
            "source_size_unknown_present",
            "source_explicit_sqft_present",
            "source_amount_log",
            "source_type_flat",
            "source_type_villa",
            "source_type_plot",
            "precise_named_location_count",
        ],
        "component_count": len(groups),
        "limitations": [
            "Agreement evaluates rule-label imitation; it cannot establish causal explanation, ownership accuracy, or missing evidence.",
            "Only nine deliberately selected files; component/file holdout is small and can have severe category/domain shift.",
            "No threshold or feature selection uses the test set. Fixed depth=3 and minimum leaf=30.",
            "Owner names, contacts, file names, IDs, candidate counts and failure flags are excluded from predictor features.",
        ],
        "new_qualified_owner_evidence": 0,
    }
    if len(groups) < 3:
        return {**common, "status": "not_fit_insufficient_disjoint_file_property_components"}
    train_groups = set(groups[: max(1, min(len(groups) - 1, round(len(groups) * 0.7)))])
    train = [r for r in records if components[r["source_event_id"]] in train_groups]
    test = [r for r in records if components[r["source_event_id"]] not in train_groups]
    train_files = {f for r in train for f in r["filenames"]}
    test_files = {f for r in test for f in r["filenames"]}
    assert not train_files & test_files
    for key in ("source_unit_id", "source_event_id"):
        assert not {r[key] for r in train} & {r[key] for r in test}
    assert not {tuple(p) for r in train for p in r.get("model_property_groups", [])} & {
        tuple(p) for r in test for p in r.get("model_property_groups", [])
    }
    labels = sorted({r["primary_cause"] for r in records})
    index = {label: n for n, label in enumerate(labels)}
    x = np.asarray([r["model_features"] for r in train], dtype=float)
    y = np.asarray([index[r["primary_cause"]] for r in train])
    nclass = len(labels)
    importance = collections.Counter()

    def build(indices, depth):
        counts = np.bincount(y[indices], minlength=nclass)
        majority = int(np.argmax(counts))
        node = {
            "count": int(len(indices)),
            "prediction": labels[majority],
            "label_counts": {labels[i]: int(v) for i, v in enumerate(counts) if v},
        }
        if depth >= 3 or len(indices) < 60 or counts[majority] == len(indices):
            return node
        base = len(indices) - float(counts @ counts) / len(indices)
        best = None
        for col in range(x.shape[1]):
            values = np.unique(x[indices, col])
            thresholds = (values[:-1] + values[1:]) / 2
            if len(thresholds) > 20:
                thresholds = np.unique(np.quantile(thresholds, np.linspace(0, 1, 20)))
            for threshold in thresholds:
                left = indices[x[indices, col] <= threshold]
                right = indices[x[indices, col] > threshold]
                if min(len(left), len(right)) < 30:
                    continue
                a = np.bincount(y[left], minlength=nclass)
                b = np.bincount(y[right], minlength=nclass)
                impurity = (
                    len(left) - float(a @ a) / len(left) + len(right) - float(b @ b) / len(right)
                )
                gain = base - impurity
                if gain > 1e-9 and (best is None or gain > best[0]):
                    best = (gain, col, float(threshold), left, right)
        if best:
            gain, col, threshold, left, right = best
            feature = common["features"][col]
            importance[feature] += gain
            node.update(
                feature=feature,
                feature_index=col,
                threshold=threshold,
                left=build(left, depth + 1),
                right=build(right, depth + 1),
            )
        return node

    tree = build(np.arange(len(train)), 0)

    def predict(record):
        node = tree
        while "feature_index" in node:
            node = node[
                "left"
                if record["model_features"][node["feature_index"]] <= node["threshold"]
                else "right"
            ]
        return node["prediction"]

    predictions = [predict(r) for r in test]
    majority = collections.Counter(r["primary_cause"] for r in train).most_common(1)[0][0]
    confusion = collections.Counter(
        (r["primary_cause"], p) for r, p in zip(test, predictions, strict=True)
    )
    return {
        **common,
        "status": "fit",
        "algorithm": "CART classification tree, Gini decrease, depth 3, >=30 events per leaf; NumPy only",
        "split": {
            "train_files": sorted(train_files),
            "held_out_files": sorted(test_files),
            "train_source_event_groups": len(train),
            "test_source_event_groups": len(test),
            "train_original_review_rows": sum(r["raw_row_count"] for r in train),
            "test_original_review_rows": sum(r["raw_row_count"] for r in test),
            "all_file_property_unit_event_components_disjoint": True,
        },
        "test_rule_label_agreement": sum(
            r["primary_cause"] == p for r, p in zip(test, predictions, strict=True)
        )
        / len(test),
        "test_training_majority_baseline_agreement": sum(
            r["primary_cause"] == majority for r in test
        )
        / len(test),
        "training_majority_label": majority,
        "test_unseen_training_labels": sorted(
            {r["primary_cause"] for r in test} - {r["primary_cause"] for r in train}
        ),
        "feature_gini_decrease": dict(importance),
        "tree": tree,
        "test_confusion": [
            {"actual_rule_label": a, "predicted_rule_label": b, "source_event_groups": n}
            for (a, b), n in sorted(confusion.items())
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", type=Path, default=Path("/tmp/vv-owner-corpus-2026-10-28/unit-guarded")
    )
    parser.add_argument(
        "--experiments", type=Path, default=Path("/tmp/vv-owner-best-rules-2026-10-28")
    )
    parser.add_argument(
        "--reconciliation", type=Path, default=Path("/tmp/vv-owner-ui-reconciliation-2026-10-29")
    )
    parser.add_argument(
        "--raw-authority", type=Path, default=Path("/tmp/vv-best-rules-verifier-all-raw.json")
    )
    parser.add_argument(
        "--backend-baseline",
        type=Path,
        default=Path("/tmp/vv-owner-integration-baseline-2026-10-29/backend"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("/tmp/vv-owner-review-root-causes-2026-10-29")
    )
    parser.add_argument("--workbook", type=Path)
    parser.add_argument(
        "--reuse-gate-diagnostics",
        type=Path,
        help="Reuse contact-free event-diagnostics.jsonl from the same immutable inputs; companion root-cause-metrics.json required. Only post-selection/report code may differ.",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.output.chmod(0o700)
    if args.workbook is None:
        args.workbook = args.output / "Root-Cause-Analysis.xlsx"
    args.workbook.parent.mkdir(parents=True, exist_ok=True)
    inputs = [
        Path(__file__),
        args.corpus / "events.jsonl",
        args.corpus / "units.jsonl",
        args.corpus / "places-snapshot.json",
        args.corpus / "snapshot.sqlite",
        args.reconciliation / "row-ledger.jsonl",
        args.reconciliation / "reconciliation-counts.json",
        args.raw_authority,
        args.experiments / "experiment/run.py",
        args.experiments / "experiment/size-anchor-pairs.json",
        args.experiments / "experiment/supported-candidate-cache.json",
        args.experiments / "experiment/learned_units-pair-index.json",
        args.experiments / "namespace-experiment/r3_namespace.py",
        args.experiments / "namespace-experiment/selected-pair-index.json",
        args.experiments / "namespace-experiment/selected-pairs.json",
        args.experiments / "namespace-experiment/property-alias-crosswalk.json",
        args.experiments / "property-reference-results.json",
        args.experiments / "ranker/report.json",
    ] + sorted((args.backend_baseline / "app").rglob("*.py"))
    before = {str(path): sha(path) for path in inputs}
    reconciliation = load(args.reconciliation / "reconciliation-counts.json")
    assert reconciliation["check"] == "PASS"
    filenames = [row["filename"] for row in reconciliation["files"]]
    assert len(filenames) == len(set(filenames)) == 9
    ledger = [json.loads(line) for line in (args.reconciliation / "row-ledger.jsonl").open()]
    provenance = [(r["filename"], r["sheet"], r["row"]) for r in ledger]
    assert len(ledger) == len(set(provenance)) == 110866
    review_rows = [r for r in ledger if r["category"] in {"unresolved_sale", "ambiguous"}]
    assert collections.Counter(r["category"] for r in review_rows) == {
        "unresolved_sale": 41150,
        "ambiguous": 316,
    }
    rows_by_event = collections.defaultdict(list)
    ambiguous_provenance = set()
    for row in review_rows:
        rows_by_event[row["source_event_id"]].append(row)
        if row["category"] == "ambiguous":
            ambiguous_provenance.add((row["filename"], row["sheet"], row["row"]))
    selected_index = load(args.experiments / "namespace-experiment/selected-pair-index.json")
    selected = {
        r["source_event_id"]: r
        for r in load(args.experiments / "namespace-experiment/selected-pairs.json")
    }
    assert (
        len(selected) == 16268
        and {k: r["target_event_key"] for k, r in selected.items()} == selected_index
    )
    events = {}
    captured_links = collections.defaultdict(set)
    ambiguous_private_keys = {}
    associations = collections.defaultdict(list)
    # Names are used only for exact replay of the frozen ambiguous association;
    # neither their text nor a digest is exported or used by ML.
    for line in (args.corpus / "events.jsonl").open():
        raw = json.loads(line)
        prov = [tuple(p) for p in raw["provenance"] if p[0] in filenames]
        if not prov:
            continue
        uid, eid = raw["source_unit_id"], raw["source_event_id"]
        for link in (raw["result"], raw.get("property_result", {})):
            if link.get("status") == "matched":
                captured_links[uid].add(tuple(link["property_identity"]))
        if raw["source"]["event_family"] != "sale":
            continue
        events[eid] = {
            "source": raw["source"],
            "uid": uid,
            "prov": sorted({(digest(p[0]), digest(p[1])) for p in prov}),
            "files": sorted({p[0] for p in prov}),
        }
        if eid not in selected:
            continue
        identity = tuple(selected[eid]["canonical_property_identity"])
        for party in raw["parties"]:
            p = tuple(party["provenance"])
            if p[0] not in filenames:
                continue
            name = re.sub(r"\s+", " ", str(party.get("name") or "").strip().casefold())
            role = str(party.get("role") or "").casefold()
            if role not in {"buyer", "seller"}:
                continue
            key = (identity, name)
            associations[key].append((str(selected[eid]["target_transaction_date"]), role))
            if p in ambiguous_provenance:
                ambiguous_private_keys[p] = (key, role)
    assert len(events) == 42290 and set(rows_by_event) <= events.keys()
    assert set(ambiguous_private_keys) == ambiguous_provenance
    units = {}
    for line in (args.corpus / "units.jsonl").open():
        unit = json.loads(line)
        if any(p[0] in filenames for p in unit["provenance"]):
            units[unit["source_unit_id"]] = {
                k: unit[k] for k in ("identity", "uncertain", "property_conflict")
            }
    raw_mask = load(args.raw_authority)["events"]
    assert raw_mask.keys() == events.keys()
    tm, namespace, ns, places, place_key, area_key = load_frozen_rules(args, events, raw_mask)
    raw_rows = collections.defaultdict(list)
    for line in (args.experiments / "cadastral-experiment/raw-row-metadata.jsonl").open():
        row = json.loads(line)
        if row["source_event_id"] in rows_by_event:
            raw_rows[row["source_event_id"]].append(row["raw_fields"])
    assert set(raw_rows) == set(rows_by_event)
    inputs.append(args.experiments / "cadastral-experiment/raw-row-metadata.jsonl")
    before[str(inputs[-1])] = sha(inputs[-1])
    canonical_aliases = {
        tuple(r["canonical_property_identity"]): [
            tuple(p) for p in r["observed_property_identities"]
        ]
        for r in load(args.experiments / "namespace-experiment/property-alias-crosswalk.json")
    }
    alias_to_canonical = {p: c for c, aliases in canonical_aliases.items() for p in aliases}

    def canonical(identity):
        return alias_to_canonical.get(tuple(identity), tuple(identity))

    cache = load(args.experiments / "experiment/supported-candidate-cache.json")["supported"]
    property_links = {
        r["source_unit_id"]: tuple(r["canonical_property_identity"])
        for r in load(args.experiments / "property-reference-results.json")
        if r["status"] == "SUPPORTED PROPERTY LINK"
    }
    named_catalog = {
        place_key(p.get(field))
        for p in places
        for field in ("building_label", "project_label")
        if place_key(p.get(field))
    }
    db = sqlite3.connect(
        f"file:{args.corpus.resolve()}/snapshot.sqlite?mode=ro&immutable=1", uri=True
    )
    db.execute("PRAGMA query_only=ON")
    snapshot_families = dict(db.execute("SELECT family, COUNT(*) FROM event GROUP BY family"))

    @lru_cache(maxsize=8)
    def pool(amount):
        records = {}
        other = collections.Counter()
        a = tm.positive_decimal(amount)
        for family, payload in db.execute(
            "SELECT family, payload FROM event WHERE amount BETWEEN ? AND ?",
            (float(a) - 2, float(a) + 2),
        ):
            target = json.loads(payload)
            if not any(abs(v - a) <= 2 for _, v in tm._amounts(target)):
                continue
            other[family] += 1
            if family == "sale":
                records[(target["event_key"], namespace.canonical_identity(target))] = target
        return list(records.values()), dict(other)

    @lru_cache(maxsize=10000)
    def property_history(identity):
        identities = canonical_aliases.get(tuple(identity), [tuple(identity)])
        counts = collections.Counter()
        dates = []
        for alias in identities:
            key = json.dumps(list(alias), separators=(",", ":"))
            for family, amount, event_date in db.execute(
                "SELECT family, amount, event_date FROM event WHERE identity=?", (key,)
            ):
                counts[family] += 1
                if family == "sale":
                    dates.append((amount, event_date))
        return counts, dates

    @lru_cache(maxsize=10000)
    def timeline(identity):
        identities = canonical_aliases.get(identity, [identity])
        latest = ""
        keys = set()
        for alias in identities:
            key = json.dumps(list(alias), separators=(",", ":"))
            day = db.execute(
                "SELECT MAX(event_date) FROM event WHERE identity=? AND family='sale'", (key,)
            ).fetchone()[0]
            if not day or day < latest:
                continue
            if day > latest:
                latest, keys = day, set()
            for (payload,) in db.execute(
                "SELECT payload FROM event WHERE identity=? AND family='sale' AND event_date=?",
                (key, day),
            ):
                keys.add(json.loads(payload)["event_key"])
        return latest, len(keys)

    diagnostics = {}
    proposed = {}
    disagreements = []
    if args.reuse_gate_diagnostics:
        cache_report = load(args.reuse_gate_diagnostics.parent / "root-cause-metrics.json")
        old_hashes = cache_report["input_sha256"]
        assert cache_report["checks"]["fresh_base_cache_eligibility_agrees"]
        for path, fingerprint in old_hashes.items():
            if Path(path).resolve() != Path(__file__).resolve():
                assert sha(Path(path)) == fingerprint, "Gate reuse input changed: " + path
        diagnostics = {
            row["source_event_id"]: row
            for line in args.reuse_gate_diagnostics.open()
            if (row := json.loads(line))
        }
        assert all(
            row["source_property"] == property_only(events[eid]["source"])
            for eid, row in diagnostics.items()
        )
        print(
            json.dumps(
                {
                    "checkpoint": "verified_fresh_pool_gate_cache_reused",
                    "source_event_groups": len(diagnostics),
                }
            ),
            flush=True,
        )
    unresolved_ids = [
        eid for eid, rows in rows_by_event.items() if rows[0]["category"] == "unresolved_sale"
    ]
    assert len(unresolved_ids) == 26022
    for n, eid in enumerate(
        []
        if args.reuse_gate_diagnostics
        else sorted(
            unresolved_ids, key=lambda value: float(events[value]["source"].get("amount_aed") or 0)
        ),
        1,
    ):
        e, s = events[eid], events[eid]["source"]
        fields = raw_mask[eid]["fields"]

        def supports(field):
            return bool(fields.get(field, {}).get("all_raw_support") and ns["idv"](s, field))

        original = {
            field: supports(field)
            for field in ("unit_number", "building_number", "plot_number", "property_number")
        }
        raw_codes = {
            namespace.parse_r3(row.get(f))
            for row in raw_rows[eid]
            for f in ("building_number", "building_name", "unit_number")
            if namespace.parse_r3(row.get(f))
        }
        raw_conflict = len(raw_codes) > 1
        patterns = {namespace.parse_r3(row.get("building_number")) for row in raw_rows[eid]}
        for row in raw_rows[eid]:
            parsed = namespace.parse_r3(row.get("building_number"))
            if parsed:
                number = ns["idv"](row, "building_name")
                rawunit = ns["idv"](row, "unit_number")
                raw_conflict |= bool(number.isdigit() and number != parsed[1])
                raw_conflict |= bool(
                    rawunit
                    and rawunit != parsed[1]
                    and namespace.parse_r3(row.get("unit_number")) != parsed
                )
        normalized_conflict = False
        if len(patterns) == 1 and None not in patterns:
            community, number = next(iter(patterns))
            unit = ns["idv"](s, "unit_number")
            normalized_conflict = bool(
                unit
                and unit != number
                and namespace.parse_r3(s.get("unit_number")) != (community, number)
            )
        precise = []
        for field in ("building_name", "project_name"):
            value = place_key(s.get(field))
            if (
                value
                and value not in {"0", "null", place_key(s.get("area_name"))}
                and not value.isdigit()
                and not tm.generic_building(str(s.get(field) or ""))
            ):
                precise.append(value)
        amount = tm.positive_decimal(s.get("amount_aed"))
        rows, family_counts = pool(str(amount)) if amount else ([], {})
        d = {
            "source_event_id": eid,
            "source_unit_id": e["uid"],
            "filenames": e["files"],
            "source_property": property_only(s),
            "raw_original_property_fields": sorted(
                {json.dumps(property_only(row), sort_keys=True) for row in raw_rows[eid]}
            ),
            "raw_original_authority": original,
            "any_original_identifier": any(original.values()),
            "raw_original_unit_absent": not original["unit_number"],
            "raw_original_building_absent": not original["building_number"],
            "raw_address_conflict": raw_conflict,
            "normalized_projection_conflict": normalized_conflict,
            "amount_present": bool(amount),
            "sale_price_pool_events": len(rows),
            "same_price_event_families": family_counts,
            "same_price_rental_events": family_counts.get("rental", 0),
            "precise_location_labels": sorted(set(precise)),
            "catalog_named_label_found": any(value in named_catalog for value in precise),
            "id_compatible_events": 0,
            "scoped_events": 0,
            "id_scoped_events": 0,
            "id_scope_type_events": 0,
            "qualified_before_raw": 0,
            "qualified_candidates": 0,
            "original_role_disagreement_events": 0,
            "explicit_source_size_missing": not bool(tm.positive_decimal(s.get("size_sqft"))),
        }
        qualified = {}
        before_raw = set()
        base_eligible = set()
        examples = {}
        # Every same-price sale is inspected; price, date and size never invent an ID.
        for target in rows:
            ident = ns["ids_fit"](s, target)
            score, conflict = tm._scope(s, target)
            hierarchy = ns["hierarchy"](s, target)
            scoped = bool((score and not conflict) or hierarchy)
            physical = not tm.physical_types_conflict(
                s.get("property_type"), target.get("property_type")
            )
            sk, rk = tm._kind(s.get("property_type")), tm._kind(target.get("property_type"))
            if sk == "plot" and rk == "villa" and not ns["child_plot_villa"](s, target):
                physical = False
            if sk in {"flat", "villa"} and rk in {"flat", "villa"} and sk != rk:
                physical = False
            d["id_compatible_events"] += ident
            d["scoped_events"] += scoped
            d["id_scoped_events"] += ident and scoped
            d["id_scope_type_events"] += ident and scoped and physical
            if ident and "id_agrees_location_fails" not in examples and not scoped:
                examples["id_agrees_location_fails"] = property_only(target)
            if scoped and not ident and "location_agrees_id_fails" not in examples:
                examples["location_agrees_id_fails"] = property_only(target)
            if (
                original["unit_number"]
                and rk == "villa"
                and ns["idv"](s, "unit_number") == ns["idv"](target, "unit_number")
                and ns["idv"](s, "building_number")
                and ns["idv"](s, "building_number") != ns["idv"](target, "unit_number")
            ):
                projected = {**s, "building_number": s.get("unit_number")}
                if sk == "plot":
                    projected["property_type"] = "Villa"
                if ns["candidate"](projected, target):
                    d["original_role_disagreement_events"] += 1
                    examples.setdefault(
                        "original_building_unit_roles_disagree", property_only(target)
                    )
            candidate = ns["candidate"](s, target)
            key = (target["event_key"], namespace.canonical_identity(target))
            if candidate:
                base_eligible.add(key)
                before_raw.add(key)
                good, flags = ns["raw_authority"](eid, target)
                if good:
                    candidate["flags"] += flags
                    qualified[key] = candidate
            keys = (
                [namespace.namespace_key(s, raw, target) for raw in raw_rows[eid]]
                if raw_codes
                else []
            )
            if keys and None not in keys and len(set(keys)) == 1:
                flags = set(tm._review_flags({**s, "size_sqft": None}, target, 300, {"amount_aed"}))
                flags.discard("type_mismatch_review_required")
                if not flags - {"date_conflict"}:
                    before_raw.add(key)
                    qualified[key] = {
                        "row": target,
                        "flags": sorted(flags | {"raw_full_building_R3_namespace_authority"}),
                        "date_conflict": "date_conflict" in flags,
                    }
        # Compare fresh base eligibility against the frozen cache, independently of old blocker labels.
        cached = {
            (c["row"]["event_key"], namespace.canonical_identity(c["row"])) for c in cache[eid]
        }
        fresh_base = base_eligible
        if fresh_base != cached:
            disagreements.append(
                {"source_event_id": eid, "cached": len(cached), "fresh_retained": len(fresh_base)}
            )
        candidates = list(qualified.values())
        d["qualified_before_raw"] = len(before_raw)
        d["qualified_candidates"] = len(candidates)
        d["qualified_physical_properties"] = len(
            {namespace.canonical_identity(c["row"]) for c in candidates}
        )
        unit, inference = ns["infer"](e)
        d["inferred_size_unit"] = unit
        d["size_unit_evidence"] = inference
        d["source_size_unit_unknown"] = bool(
            tm.positive_decimal(s.get("size_unknown")) and not unit
        )
        picked, status = ns["select"](e, candidates, "learned_units")
        d["selection_status"] = status
        d["candidate_property_examples"] = [property_only(c["row"]) for c in candidates[:3]]
        d["gate_failure_examples"] = examples
        if picked:
            target = picked["row"]
            proposed[eid] = target
            d["proposed_event_key"] = target["event_key"]
            d["proposed_property_identity"] = list(namespace.canonical_identity(target))
        u = units[e["uid"]]
        uncertain_exception = bool(
            picked
            and u["identity"][0] == "plot_reference"
            and (
                (
                    tm._kind(picked["row"].get("property_type")) == "plot"
                    and ns["idv"](s, "plot_number") == ns["idv"](picked["row"], "unit_number")
                )
                or ns["child_plot_villa"](s, picked["row"])
            )
        )
        d["source_reference_uncertain"] = bool(u["uncertain"] and not uncertain_exception)
        d["source_reference_kind"] = u["identity"][0]
        link = property_links.get(e["uid"])
        d["supported_property"] = bool(link)
        d["supported_property_identity"] = list(link) if link else None
        if link:
            history_counts, prices = property_history(link)
            d["identified_property_history_families"] = dict(history_counts)
            d["identified_property_sale_price_events"] = sum(
                abs(float(price) - float(amount)) <= 2
                for price, _ in prices
                if price is not None and amount
            )
        props = {canonical(p) for p in captured_links[e["uid"]]}
        d["source_property_conflict"] = len(props) > 1 or bool(u["property_conflict"])
        d["captured_source_property_identities"] = sorted(props)
        d["model_property_groups"] = [
            list(p) for p in sorted({namespace.canonical_identity(c["row"]) for c in candidates})
        ]
        d["model_features"] = (
            [
                int(original[f])
                for f in ("unit_number", "building_number", "plot_number", "property_number")
            ]
            + [
                int(bool(re.search("[a-z]", ns["idv"](s, f))))
                for f in ("unit_number", "building_number")
            ]
            + [
                int(bool(tm.positive_decimal(s.get("size_unknown")))),
                int(bool(tm.positive_decimal(s.get("size_sqft")))),
                math.log1p(float(amount or 0)),
                int(tm._kind(s.get("property_type")) == "flat"),
                int(tm._kind(s.get("property_type")) == "villa"),
                int(tm._kind(s.get("property_type")) == "plot"),
                len(set(precise)),
            ]
        )
        diagnostics[eid] = d
        if n % 2500 == 0:
            print(
                json.dumps(
                    {
                        "checkpoint": "fresh_complete_pool_diagnostics",
                        "unresolved_source_events": n,
                        "cache_disagreements": len(disagreements),
                    }
                ),
                flush=True,
            )
    assert set(diagnostics) == set(unresolved_ids)
    old_index, old_rejections, old_statuses, old_properties = replay_prior_selection(
        events, units, captured_links, cache, ns, tm
    )
    expected_old_index = load(args.experiments / "experiment/learned_units-pair-index.json")
    assert old_index == expected_old_index and len(old_index) == 16042
    print(
        json.dumps(
            {
                "checkpoint": "exact_full_prior_selection_replayed",
                "source_events": len(events),
                "selected": len(old_index),
            }
        ),
        flush=True,
    )
    for eid, d in diagnostics.items():
        e, s = events[eid], events[eid]["source"]
        namespace_cohort = any(
            namespace.parse_r3(row.get("building_number")) for row in raw_rows[eid]
        )
        reason = old_rejections.get(eid) if not namespace_cohort else None
        d["frozen_prior_selection_status"] = old_statuses[eid]
        d["frozen_prior_rejection_reason"] = old_rejections.get(eid)
        d["final_namespace_cohort"] = namespace_cohort
        d["source_reference_uncertainty_blocks_selection"] = bool(
            reason and reason.startswith("uncertain_")
        )
        d["source_property_conflict_blocks_selection"] = reason in {
            "existing_source_reference_property_conflict",
            "source_reference_property_conflict",
        }
        d["reverse_reuse_conflict"] = reason == "incompatible_reverse_event_reuse"
        d["source_property_conflict"] = len({canonical(p) for p in old_properties[e["uid"]]}) > 1
        d["competing_property_identities"] = [
            list(p) for p in sorted({canonical(p) for p in old_properties[e["uid"]]})
        ]
        if args.reuse_gate_diagnostics:
            original = d["raw_original_authority"]
            amount = tm.positive_decimal(s.get("amount_aed"))
            d["model_features"] = (
                [
                    int(original[f])
                    for f in ("unit_number", "building_number", "plot_number", "property_number")
                ]
                + [
                    int(bool(re.search("[a-z]", ns["idv"](s, f))))
                    for f in ("unit_number", "building_number")
                ]
                + [
                    int(bool(tm.positive_decimal(s.get("size_unknown")))),
                    int(bool(tm.positive_decimal(s.get("size_sqft")))),
                    math.log1p(float(amount or 0)),
                    int(tm._kind(s.get("property_type")) == "flat"),
                    int(tm._kind(s.get("property_type")) == "villa"),
                    int(tm._kind(s.get("property_type")) == "plot"),
                    len(d["precise_location_labels"]),
                ]
            )
            properties = {
                namespace.canonical_identity(c["row"])
                for c in cache[eid]
                if ns["raw_authority"](eid, c["row"])[0]
            }
            properties |= {
                namespace.canonical_identity(c) for c in d["candidate_property_examples"]
            }
            assert len(properties) == d["qualified_physical_properties"], (
                "Incomplete reusable model property grouping"
            )
            d["model_property_groups"] = [list(p) for p in sorted(properties)]
        d["primary_cause"] = primary_cause(d)
        d["secondary_flags"] = make_flags(d)
        d["raw_row_count"] = len(rows_by_event[eid])
    # Recompute the two owner-association ambiguities from source roles and full timelines.
    row_diagnostics = {}
    for row in review_rows:
        p = (row["filename"], row["sheet"], row["row"])
        eid = row["source_event_id"]
        if row["category"] == "unresolved_sale":
            d = diagnostics[eid]
            record = {
                **row,
                "primary_cause": d["primary_cause"],
                "secondary_flags": d["secondary_flags"],
            }
        else:
            key, role = ambiguous_private_keys[p]
            own_last = max(date for date, _ in associations[key])
            roles = {r for date, r in associations[key] if date == own_last}
            latest, count = timeline(key[0])
            both = roles == {"buyer", "seller"}
            assert both or count != 1
            owner_cause = (
                "owner_buyer_seller_same_last_day"
                if both
                else "owner_latest_registration_not_unique"
            )
            s, e = events[eid]["source"], events[eid]
            d = {
                "source_event_id": eid,
                "source_unit_id": e["uid"],
                "filenames": e["files"],
                "source_property": property_only(s),
                "owner_cause": owner_cause,
                "owner_buyer_seller_both_roles": both,
                "owner_latest_multiple_events": count != 1,
                "association_last_source_day": own_last,
                "association_last_day_roles": sorted(roles),
                "latest_captured_property_sale_day": latest,
                "latest_day_distinct_sale_events": count,
                "primary_cause": owner_cause,
                "supported_property_identity": list(key[0]),
            }
            d["secondary_flags"] = make_flags(d)
            record = {
                **row,
                "party_role": role,
                "primary_cause": owner_cause,
                "secondary_flags": d["secondary_flags"],
                "ambiguity_evidence": {
                    k: d[k]
                    for k in (
                        "association_last_source_day",
                        "association_last_day_roles",
                        "latest_captured_property_sale_day",
                        "latest_day_distinct_sale_events",
                    )
                },
            }
        row_diagnostics[p] = (record, d)
    assert len(row_diagnostics) == 41466
    counts = collections.Counter(record["primary_cause"] for record, _ in row_diagnostics.values())
    per_file = {}
    flags = collections.Counter()
    for filename in filenames:
        records = [
            record for record, _ in row_diagnostics.values() if record["filename"] == filename
        ]
        source_counts = next(f for f in reconciliation["files"] if f["filename"] == filename)
        causes = collections.Counter(r["primary_cause"] for r in records)
        assert (
            len(records)
            == sum(causes.values())
            == source_counts["unresolved_sale"] + source_counts["ambiguous"]
        )
        per_file[filename] = {
            "unresolved_sale": source_counts["unresolved_sale"],
            "ambiguous_owner": source_counts["ambiguous"],
            "original_review_rows": len(records),
            "primary_counts": dict(causes),
            "secondary_flags": dict(
                collections.Counter(flag for r in records for flag in r["secondary_flags"])
            ),
        }
        flags.update(flag for r in records for flag in r["secondary_flags"])
    examples = []
    example_counts = collections.Counter()
    for record, d in row_diagnostics.values():
        key = (record["filename"], record["primary_cause"])
        if example_counts[key] >= 2:
            continue
        example_counts[key] += 1
        examples.append(
            {
                "filename": record["filename"],
                "sheet": record["sheet"],
                "row": record["row"],
                "source_event_id": record["source_event_id"],
                "primary_cause": record["primary_cause"],
                "secondary_flags": record["secondary_flags"],
                "property_evidence": {
                    k: v
                    for k, v in d.items()
                    if k
                    not in {
                        "model_features",
                        "filenames",
                        "model_property_groups",
                        "source_event_id",
                        "source_unit_id",
                        "primary_cause",
                        "secondary_flags",
                        "raw_row_count",
                    }
                },
            }
        )
    model = diagnostic_model(list(diagnostics.values()))
    prior_ranker = load(args.experiments / "ranker/report.json")
    model["previous_property_ranker"] = {
        "new_qualified_owner_evidence_from_ml": prior_ranker[
            "new_qualified_owner_evidence_from_ml"
        ],
        "test_selected_property_mapping_identical_to_ml": prior_ranker["simple_hint_baseline"][
            "test_selected_property_mapping_identical_to_ml"
        ],
        "test_selected_group_overlap": prior_ranker["simple_hint_baseline"][
            "test_selected_group_overlap"
        ],
        "meaning": "Previous weak-label candidate ranker reproduced the simple heuristic's selected held-out properties; no demonstrated additional supported owners.",
    }
    with (args.output / "review-row-ledger.jsonl").open("w") as stream:
        for record, _ in row_diagnostics.values():
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    (args.output / "review-row-ledger.jsonl").chmod(0o600)
    with (args.output / "event-diagnostics.jsonl").open("w") as stream:
        for d in diagnostics.values():
            stream.write(
                json.dumps(
                    {
                        k: v
                        for k, v in d.items()
                        if k not in {"model_features", "model_property_groups"}
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    (args.output / "event-diagnostics.jsonl").chmod(0o600)
    write_json(args.output / "contact-free-examples.json", examples)
    write_json(args.output / "diagnostic-model.json", model)
    checks = {
        "every_review_raw_row_once": len(row_diagnostics) == 41466,
        "all_nine_per_file_partitions": len(per_file) == 9,
        "primary_counts_add_41466": sum(counts.values()) == 41466,
        "unresolved_sale_rows_41150": sum(f["unresolved_sale"] for f in per_file.values()) == 41150,
        "ambiguous_owner_rows_316": sum(f["ambiguous_owner"] for f in per_file.values()) == 316,
        "fresh_base_cache_eligibility_agrees": not disagreements,
        "full_prior_selection_exact_16042": old_index == expected_old_index,
        "no_unexplained_final_exclusions": not counts["unexplained_final_profile_exclusion"],
        "database_no_writes": db.total_changes == 0,
        "inputs_unchanged": before == {str(path): sha(path) for path in inputs},
    }
    db.close()
    report = {
        "check": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "counting_unit": "original nonblank spreadsheet review row",
        "review_rows": 41466,
        "unresolved_sale_rows": 41150,
        "ambiguous_owner_rows": 316,
        "unresolved_source_sale_event_groups": len(diagnostics),
        "primary_counts": dict(counts),
        "secondary_flags_overlap_do_not_add": dict(flags),
        "files": per_file,
        "category_definitions": CATEGORY_DESCRIPTIONS,
        "recomputed_cache_disagreements": disagreements[:50],
        "captured_snapshot_event_families": snapshot_families,
        "input_sha256": before,
        "diagnostic_model": model,
        "methodology": [
            "All 110,866 original row identities verified unique; only 41,150 unresolved-sale and 316 ambiguous-owner original rows form this review denominator. Distinct source events are not extra original rows.",
            "For every unresolved sale, recompute complete untruncated +/-2 AED sale pool and original-ID, scope, physical-type, review, size, date, reference-consistency and reverse-reuse diagnostics. Frozen eligibility cache serves only as an independent replay check.",
            "Primary category is one reproducible operational attribution, ordered by original contradictions/missing evidence then supported candidate failures then pool diagnostics. Multiple observed failures remain overlapping secondary flags; no assertion of a unique true-world cause.",
            "An original role disagreement is not proof of corrupted data: BuildingNo may denote a parent/phase, but reinterpretation remains unverified. R3 full/numeric aliases require exact qualified master/subcommunity/number and all original rows to agree.",
            "Independent supported property links separate an identified property lacking a matching sale amount from failure to identify a property. Property identity does not establish a transfer or owner.",
            "Catalog absence means no exact vetted-normalized named-label representation in the captured 7,552-place catalog; it does not prove the property or an alias does not exist.",
            "Snapshot contains sale and rental families only; sale pool is exhaustive within this frozen snapshot, not a claim to cover all Dubai registry records, gifts, financing or ownership transfers.",
            "Ambiguous associations are recomputed in memory from exact source party roles and complete alias-unioned sale timelines. Names and contact details are never exported or used as model features.",
            "CART source-only diagnostics predict deterministic operational labels on disjoint file/property/source-unit components; label agreement is neither owner accuracy nor causal proof. No owner promotion or CRM change.",
        ],
        "new_qualified_owner_evidence": 0,
    }
    report["gate_reuse"] = (
        {"path": str(args.reuse_gate_diagnostics), "sha256": sha(args.reuse_gate_diagnostics)}
        if args.reuse_gate_diagnostics
        else None
    )
    write_json(args.output / "root-cause-metrics.json", report)
    workbook(args.workbook, report, examples, row_diagnostics)
    from openpyxl import load_workbook

    wb = load_workbook(args.workbook, read_only=True, data_only=True)
    reopened = list(wb["Primary causes"].values)
    assert sum(row[1] for row in reopened[1:]) == 41466
    assert wb["Original review rows"].max_row == 41467
    wb.close()
    report["checks"]["workbook_reopened_partition"] = True
    write_json(args.output / "root-cause-metrics.json", report)
    print(
        json.dumps(
            {
                "check": report["check"],
                "review_rows": 41466,
                "primary_counts": dict(counts),
                "checks": report["checks"],
                "workbook": str(args.workbook),
                "model_status": model["status"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if report["check"] != "PASS":
        raise SystemExit(1)


def workbook(path, report, examples, row_diagnostics):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Read me"
    ws.append(["ROOT CAUSES — 41,466 ORIGINAL REVIEW ROWS"])
    for text in report["methodology"]:
        ws.append([text])
    ws.append(["Verification", report["check"]])
    ws.append(["Owner promotions", 0])
    causes = sorted(
        report["primary_counts"], key=lambda cause: (-report["primary_counts"][cause], cause)
    )
    ws = wb.create_sheet("Primary causes")
    ws.append(
        [
            "Mutually exclusive primary cause",
            "Original review rows",
            "Percent review rows",
            "Meaning",
        ]
    )
    for cause in causes:
        count = report["primary_counts"][cause]
        ws.append([cause, count, round(100 * count / 41466, 4), CATEGORY_DESCRIPTIONS[cause]])
    ws = wb.create_sheet("Per file partition")
    ws.append(
        [
            "Filename",
            "Unresolved sale",
            "Ambiguous owner",
            "Original review total",
            *causes,
            "Cause sum",
            "Difference",
        ]
    )
    for filename, counts in report["files"].items():
        total = sum(counts["primary_counts"].values())
        ws.append(
            [
                filename,
                counts["unresolved_sale"],
                counts["ambiguous_owner"],
                counts["original_review_rows"],
                *[counts["primary_counts"].get(c, 0) for c in causes],
                total,
                counts["original_review_rows"] - total,
            ]
        )
    ws = wb.create_sheet("Secondary overlapping flags")
    ws.append(["Overlapping flag — DO NOT ADD", "Original review rows"])
    for flag, count in sorted(
        report["secondary_flags_overlap_do_not_add"].items(), key=lambda pair: -pair[1]
    ):
        ws.append([flag, count])
    ws = wb.create_sheet("Property evidence examples")
    ws.append(
        [
            "Filename",
            "Sheet",
            "Original Excel row",
            "Primary cause",
            "Source property evidence",
            "Original property fields",
            "Candidate examples / failed gate evidence",
            "Secondary flags",
        ]
    )
    for example in examples:
        evidence = example["property_evidence"]
        ws.append(
            [
                excel_value(v)
                for v in [
                    example["filename"],
                    example["sheet"],
                    example["row"],
                    example["primary_cause"],
                    evidence.get("source_property"),
                    evidence.get("raw_original_property_fields"),
                    {
                        k: v
                        for k, v in evidence.items()
                        if k not in {"source_property", "raw_original_property_fields"}
                    },
                    example["secondary_flags"],
                ]
            ]
        )
    ws = wb.create_sheet("Original review rows")
    ws.append(
        [
            "Filename",
            "Sheet",
            "Original Excel row",
            "Review status",
            "Primary cause",
            "Secondary flags",
            "Source event identifier",
        ]
    )
    for record, _ in row_diagnostics.values():
        ws.append(
            [
                excel_value(v)
                for v in [
                    record["filename"],
                    record["sheet"],
                    record["row"],
                    record["category"],
                    record["primary_cause"],
                    record["secondary_flags"],
                    record["source_event_id"],
                ]
            ]
        )
    ws = wb.create_sheet("Diagnostic ML")
    ws.append(["Metric", "Value"])
    for key, value in report["diagnostic_model"].items():
        if key != "tree":
            ws.append([key, excel_value(value)])
    ws = wb.create_sheet("Verification")
    ws.append(["Check", "Result"])
    for key, value in report["checks"].items():
        ws.append([key, "PASS" if value else "FAIL"])
    for sheet in wb:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="183442")
        for col in range(1, sheet.max_column + 1):
            sheet.column_dimensions[get_column_letter(col)].width = 65 if col == 1 else 28
    wb.save(path)
    path.chmod(0o600)


if __name__ == "__main__":
    main()
