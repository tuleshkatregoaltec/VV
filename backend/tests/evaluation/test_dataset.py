import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.evaluation.dataset import Benchmark, Case, load_benchmark


def test_canonical_questions_remain_verbatim_and_all_fifteen_are_present():
    benchmark = load_benchmark()
    assert [case.id for case in benchmark.cases] == [f"q{number:02}" for number in range(1, 16)]
    # Fingerprint the original supplied questions, independent of metadata/format changes.
    questions = json.dumps([case.question for case in benchmark.cases], ensure_ascii=False)
    assert (
        hashlib.sha256(questions.encode()).hexdigest()
        == "e02c1ff447407d15dd5d74b875551572121e34c80427834ca19604d7d270868e"
    )
    assert {case.id: case.parameters for case in benchmark.cases if case.parameters} == {
        "q12": ["building"],
        "q13": ["building"],
        "q15": ["Project A", "Project B", "Project C"],
    }


def test_templates_require_complete_explicit_bindings_without_inventing_entities():
    case = load_benchmark().cases[-1]
    assert case.bind() == case.question
    with pytest.raises(ValueError, match="exactly"):
        case.bind({"Project A": "User-supplied A"})
    with pytest.raises(ValueError, match="concrete"):
        case.bind({"Project A": "A", "Project B": " ", "Project C": "C"})
    with pytest.raises(ValueError, match="concrete"):
        case.bind({"Project A": "[Project B]", "Project B": "B", "Project C": "C"})
    bound = case.bind({"Project A": "A", "Project B": "B", "Project C": "C"})
    assert "comparing A, B, and C" in bound
    assert "[Project A]" in case.question


def test_malformed_or_duplicate_cases_cannot_silently_change_benchmark_coverage():
    case = load_benchmark().cases[0]
    with pytest.raises(ValidationError, match="unique"):
        Benchmark(version=1, cases=[case, case])
    with pytest.raises(ValidationError, match="placeholders"):
        Case(id="q16", title="New", question="Question [building]", parameters=[])


def test_dataset_can_grow_and_fingerprint_tracks_content_not_json_format(tmp_path: Path):
    benchmark = load_benchmark()
    original = benchmark.digest
    path = tmp_path / "benchmark.json"
    path.write_text(benchmark.model_dump_json(indent=4))
    assert load_benchmark(path).digest == original
    benchmark.cases.append(Case(id="q16", title="Additional case", question="User-added question"))
    assert benchmark.digest != original
    assert len(benchmark.cases) == 16


def test_scope_heldout_inputs_are_separate_from_canonical_and_training_examples():
    from scripts.evaluation.dataset import BENCHMARK

    heldout = load_benchmark(BENCHMARK.with_name("scope_heldout.json"))
    canonical = load_benchmark()
    prepared = json.loads(BENCHMARK.with_name("behavioral_examples.json").read_text())
    expectations = json.loads(BENCHMARK.with_name("scope_heldout_expectations.json").read_text())
    assert heldout.digest != canonical.digest
    assert not {case.id for case in heldout.cases} & {case.id for case in canonical.cases}
    assert not {case.question for case in heldout.cases} & {
        example["user"] for split in ("train", "heldout") for example in prepared[split]
    }
    assert {case.id for case in heldout.cases} == set(expectations["cases"])
    # Exact inputs survive existing binding/execution; this does not grade model interpretation.
    assert all(case.bind() == case.question and not case.parameters for case in heldout.cases)
