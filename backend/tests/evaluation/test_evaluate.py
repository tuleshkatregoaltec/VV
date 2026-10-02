from copy import deepcopy

import pytest

from scripts.evaluation.evaluate import apply_references, compare, evaluate_case, observation


def inputs():
    record = {
        "question": "Question",
        "http_status": 200,
        "events": [{"type": "done"}],
        "persisted_messages": [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer"},
        ],
    }
    observed = {
        "answer": "Answer",
        "models": [{"gen_ai.request.model": "model"}],
        "tools": [],
        "queries": [],
        "sources": [],
        "trace_root_present": True,
        "trace_missing_parents": [],
    }
    return record, observed, {"tools": {}}


def test_completed_stream_does_not_imply_grounded_or_numerically_correct_answer():
    record, observed, runtime = inputs()
    checks = evaluate_case(
        record,
        observed,
        runtime,
        {
            "required_sources": ["registered_rents"],
            "capability_verified": True,
            "missing_capabilities": ["rental comparison"],
        },
    )
    assert checks["execution"]["status"] == "pass"
    assert checks["source_coverage"]["status"] == "fail"
    assert checks["grounding"]["status"] == "unassessed"
    assert checks["numerical_correctness"]["status"] == "unassessed"
    assert checks["query_execution"]["status"] == "unassessed"
    assert checks["capability_support"]["status"] == "unsupported"


def test_empty_evidence_and_nonfinite_values_are_not_database_exceptions():
    record, observed, runtime = inputs()
    observed["queries"] = [{"result": [{"median": float("nan")}], "error": False, "sql": ""}]
    observed["tools"] = [
        {
            "name": "pulse",
            "arguments": {},
            "result": {"success": True, "transaction_count": 0},
            "error": False,
        }
    ]
    runtime["tools"]["pulse"] = {"schema": {"type": "object"}}
    checks = evaluate_case(record, observed, runtime, {})
    assert checks["finite_query_values"]["status"] == "fail"
    assert checks["evidence_availability"]["reason"] == "empty"
    assert checks["query_execution"]["status"] == "pass"
    assert checks["tool_execution"]["status"] == "pass"


def test_previous_quarter_requires_calendar_sql_not_rolling_days():
    record, observed, runtime = inputs()
    observed["queries"] = [
        {
            "sql": "WHERE instance_date >= today() - {period_days:Int32}",
            "error": False,
            "result": [],
        }
    ]
    checks = evaluate_case(record, observed, runtime, {"calendar_window": "previous_quarter"})
    assert checks["calendar_window"]["status"] == "fail"


def test_tool_argument_validation_and_error_termination_fail_independently():
    record, observed, runtime = inputs()
    record["events"] = [{"type": "error"}, {"type": "done"}]
    observed["tools"] = [
        {"name": "pulse", "arguments": {"days": "ninety"}, "result": {}, "error": False}
    ]
    runtime["tools"]["pulse"] = {
        "schema": {"type": "object", "properties": {"days": {"type": "integer"}}}
    }
    checks = evaluate_case(record, observed, runtime, {})
    assert checks["execution"]["status"] == "fail"
    assert checks["tool_schema"]["status"] == "fail"
    record["events"] = []
    assert evaluate_case(record, observed, runtime, {})["execution"]["status"] == "fail"


def test_reference_ranges_records_and_missing_values_do_not_grade_answer_text():
    checks = {}
    observed = {"tools": [{"result": {"count": 10, "entities": ["B", "A"]}}]}
    apply_references(
        checks,
        observed,
        [
            {
                "path": ["tools", 0, "result", "count"],
                "kind": "range",
                "min": 9,
                "max": 11,
                "source": "curated snapshot",
            },
            {
                "path": ["tools", 0, "result", "entities"],
                "kind": "records",
                "expected": ["A", "B"],
                "source": "curated records",
            },
            {
                "path": ["tools", 0, "result", "absent"],
                "kind": "exact",
                "expected": 0,
                "source": "curated snapshot",
            },
        ],
    )
    assert [check["status"] for check in checks.values()] == ["pass", "pass", "fail"]
    with pytest.raises(ValueError, match="structured"):
        apply_references(
            {},
            observed,
            [{"path": ["answer"], "kind": "exact", "expected": "same text", "source": "reference"}],
        )


@pytest.mark.parametrize(
    "candidate_check",
    [
        {"status": "unassessed", "method": "human"},
        {"status": "unassessed", "method": "assisted_review"},
        None,
    ],
)
def test_comparison_detects_lost_assessment_and_rejects_changed_benchmark_context(candidate_check):
    baseline = {
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
    baseline["cases"] = [
        {
            "case_id": "q01",
            "question_sha256": "same",
            "parameters_sha256": "same",
            "checks": {"grounding": {"status": "pass", "method": "human"}},
        }
    ]
    candidate = deepcopy(baseline)
    candidate["cases"][0]["checks"] = (
        {"grounding": candidate_check} if candidate_check is not None else {}
    )
    result = compare(baseline, candidate)
    assert result["comparable"] and len(result["regressions"]) == 1
    candidate["date"] = "different"
    assert compare(baseline, candidate)["comparable"] is False
    candidate = deepcopy(baseline)
    baseline["data_context"] = candidate["data_context"] = "local-mutable-warehouse"
    assert compare(baseline, candidate)["comparable"] is False


def test_trace_extraction_does_not_double_count_agent_and_model_tokens():
    record = {"trace_ids": {"stream": "abc"}}
    spans = [
        {
            "context": {"trace_id": "0xabc"},
            "name": "agent run",
            "attributes": {"gen_ai.usage.input_tokens": 30},
        },
        {
            "context": {"trace_id": "0xabc"},
            "name": "model",
            "attributes": {"gen_ai.request.model": "model", "gen_ai.usage.input_tokens": 30},
        },
    ]
    assert observation(record, spans)["token_usage"]["input"] == 30


def test_trace_coverage_rejects_missing_infrastructure_parents():
    record, observed, runtime = inputs()
    observed["trace_missing_parents"] = ["unrecorded-fastapi-parent"]
    assert evaluate_case(record, observed, runtime, {})["trace_coverage"]["status"] == "fail"


def test_each_requested_quality_dimension_stays_unassessed_after_successful_stream():
    record, observed, runtime = inputs()
    checks = evaluate_case(record, observed, runtime, {})
    for dimension in (
        "numerical_correctness",
        "filters",
        "tool_arguments",
        "completeness",
        "clarification",
        "freshness",
        "privacy",
    ):
        assert checks[dimension]["status"] == "unassessed"


def test_explicit_clarification_can_complete_without_a_provider_trace():
    record, observed, runtime = inputs()
    record["unbound_parameters"] = ["building"]
    record["persisted_messages"][1]["meta_data"] = {
        "clarification_required": True,
        "required_bindings": ["building"],
    }
    observed["models"] = []
    checks = evaluate_case(record, observed, runtime, {})
    assert checks["clarification"]["status"] == "pass"
    assert checks["trace_coverage"]["status"] == "pass"
    assert checks["numerical_correctness"]["status"] == "unassessed"


def test_reference_selector_requires_unique_row_and_never_proves_answer_correctness():
    from scripts.evaluation.evaluate import apply_dimension_suites

    observed = {
        "tools": [
            {
                "name": "compare_listing_age",
                "arguments": {"request": {"bedrooms": "2"}},
                "result": {"rows": [{"id": "old", "age": 122}]},
            }
        ]
    }
    refs = [
        {
            "tool": "compare_listing_age",
            "path": ["tools", 0, "result", "rows", {"where": {"id": "old"}}, "age"],
            "kind": "exact",
            "expected": 122,
            "source": "independent fixture",
        }
    ]
    checks = {}
    apply_references(checks, observed, refs)
    assert checks["reference_evidence_0"]["status"] == "pass"
    assert "numerical_correctness" not in checks
    observed["tools"][0]["result"]["rows"].append({"id": "old", "age": 122})
    apply_references(checks, observed, refs)
    assert checks["reference_evidence_0"]["status"] == "fail"
    with pytest.raises(ValueError, match="complete"):
        apply_dimension_suites(checks, {"filters": {"references": [0], "source": "fixture"}})
    with pytest.raises(ValueError, match="complete"):
        apply_dimension_suites(
            checks,
            {"numerical_correctness": {"references": [0], "source": "fixture", "complete": True}},
        )


def test_mcp_unavailable_is_not_evidence_success():
    record, observed, runtime = inputs()
    observed["tools"] = [
        {
            "name": "compare_listing_rents",
            "arguments": {},
            "result": {"status": "unavailable", "data": None},
            "error": False,
        }
    ]
    runtime["tools"]["compare_listing_rents"] = {"schema": {"type": "object"}}
    checks = evaluate_case(record, observed, runtime, {})
    assert checks["evidence_availability"]["status"] == "unassessed"
    assert checks["numerical_correctness"]["status"] == "unassessed"


def test_persisted_mcp_evidence_mismatch_is_not_silently_replaced():
    record = {
        "trace_ids": {"stream": "abc"},
        "persisted_messages": [
            {
                "role": "assistant",
                "meta_data": {"evidence": [{"tool": "metric", "result": {"count": 3}}]},
            }
        ],
    }
    spans = [
        {
            "context": {"trace_id": "abc", "span_id": "one"},
            "name": "tool",
            "status": {"status_code": "OK"},
            "attributes": {
                "gen_ai.tool.name": "metric",
                "tool_arguments": "{}",
                "tool_response": '{"count":4}',
            },
        }
    ]
    observed = observation(record, spans)
    assert observed["evidence_consistency"] is False
    assert observed["tools"][0]["result"] == {"count": 4}


@pytest.mark.parametrize("unavailable_retrieval", [False, True])
def test_binding_success_cannot_turn_absent_or_unavailable_evidence_into_pass(
    unavailable_retrieval,
):
    record, observed, runtime = inputs()
    observed["tools"] = [
        {
            "name": "bind_market_scope",
            "arguments": {},
            "error": False,
            "result": {
                "status": "ok",
                "data": {"cohorts": [{"id": "scope", "evidence_kind": "listings"}]},
            },
        }
    ]
    if unavailable_retrieval:
        observed["tools"].append(
            {
                "name": "get_listing_inventory",
                "arguments": {},
                "error": False,
                "result": {"status": "unavailable", "data": None},
            }
        )
    runtime["tools"] = {tool["name"]: {"schema": {"type": "object"}} for tool in observed["tools"]}
    checks = evaluate_case(record, observed, runtime, {"required_sources": ["listings"]})
    assert checks["tool_execution"]["status"] == "pass"
    assert checks["evidence_availability"]["status"] == "unassessed"
    assert checks["source_coverage"]["status"] == "fail"
    assert checks["numerical_correctness"]["status"] == "unassessed"
