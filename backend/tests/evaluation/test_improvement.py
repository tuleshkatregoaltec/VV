import json
from copy import deepcopy

import pytest

from scripts.evaluation.improvement import (
    QUALITY_DIMENSIONS,
    load_examples,
    prepare,
    promotion_gate,
)


def test_synthetic_splits_are_disjoint_and_preparation_cannot_start_training(tmp_path):
    examples = load_examples()
    assert len(examples["train"]) == 8 and len(examples["heldout"]) == 4
    output = tmp_path / "prepared"
    manifest = prepare(output)
    assert manifest["training_started"] is False
    assert manifest["support"]["training_authorized"] is False
    assert manifest["support"]["runtime_training_endpoint_verified"] is False
    assert (output.stat().st_mode & 0o777) == 0o700
    assert json.loads((output / "heldout.json").read_text())[0]["messages"]


def test_dataset_rejects_train_heldout_overlap_and_private_identifiers(tmp_path):
    examples = load_examples()
    examples["heldout"][0]["user"] = examples["train"][0]["user"]
    path = tmp_path / "examples.json"
    path.write_text(json.dumps(examples))
    with pytest.raises(ValueError, match="distinct"):
        load_examples(path)
    examples = load_examples()
    examples["train"][0]["user"] = "Contact private.person@example.test"
    path.write_text(json.dumps(examples))
    with pytest.raises(ValueError, match="private"):
        load_examples(path)


def assessment():
    result = {
        key: "same"
        for key in (
            "dataset_sha256",
            "criteria_sha256",
            "references_sha256",
            "evaluator_sha256",
            "date",
            "data_context",
        )
    }
    result["runtime"] = {"configured_model": "approved-baseline", "prompt_version": "v1"}
    result["cases"] = [
        {
            "case_id": "q01",
            "question_sha256": "q",
            "parameters_sha256": "p",
            "checks": {
                dimension: {"status": "pass", "method": "human"} for dimension in QUALITY_DIMENSIONS
            },
        }
    ]
    return result


def test_promotion_requires_improvement_complete_assessment_and_privacy_without_regression():
    baseline = assessment()
    candidate = deepcopy(baseline)
    assert not promotion_gate(baseline, candidate)["promote"]
    baseline["cases"][0]["checks"]["completeness"]["status"] = "fail"
    assert promotion_gate(baseline, candidate)["promote"]
    candidate["cases"][0]["checks"]["privacy"]["status"] = "unassessed"
    result = promotion_gate(baseline, candidate)
    assert not result["promote"]
    assert result["rollback"] == baseline["runtime"]
    candidate["cases"][0]["checks"].pop("privacy")
    assert not promotion_gate(baseline, candidate)["promote"]
