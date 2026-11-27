"""Per-case results and per-layer summaries for the CRM Assistant evaluation.

Every layer reports what it planned, executed, passed, failed, errored and could not apply, by
case ID. A summary says every planned case passed only when each was executed and passed; a
case that was not run, not applicable or errored is never counted as passed. Details are safe
to store: check names, counts, statuses and exception types, never record contents, prompts or
tool results.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Layer = Literal["offline_fixture", "db_integration", "live_model"]
Status = Literal["passed", "failed", "error", "not_applicable"]
# deterministic: authorization, tool use, writes and persisted state. text: answer facts and
# forbidden claims found in the answer (a heuristic, never a substitute for the former).
CheckKind = Literal["deterministic", "text"]


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""
    kind: CheckKind = "deterministic"


@dataclass
class CaseResult:
    case_id: str
    layer: Layer
    status: Status
    checks: list[Check] = field(default_factory=list)

    @classmethod
    def from_checks(cls, case_id: str, layer: Layer, checks: list[Check]) -> CaseResult:
        if not checks:
            # A case that checked nothing has not passed anything.
            return cls(case_id, layer, "error", [Check("checks_ran", False, "no checks ran")])
        status: Status = "passed" if all(check.ok for check in checks) else "failed"
        return cls(case_id, layer, status, checks)

    def passed(self, kind: CheckKind) -> bool:
        return all(check.ok for check in self.checks if check.kind == kind)


def safe_error(exc: BaseException) -> str:
    """An exception's type and HTTP status only: messages can quote records or queries."""
    status = getattr(exc, "status_code", None)
    return type(exc).__name__ + (f" (HTTP {status})" if status else "")


def summarize(layer: Layer, planned: list[str], results: list[CaseResult]) -> dict:
    reported = {result.case_id for result in results}
    if len(reported) != len(results):
        raise ValueError("Each case is reported once")
    if reported - set(planned):
        raise ValueError("Results include cases that were not planned")

    def ids(status: Status) -> list[str]:
        return sorted(r.case_id for r in results if r.status == status)

    passed, failed, errors, not_applicable = (
        ids("passed"),
        ids("failed"),
        ids("error"),
        ids("not_applicable"),
    )
    not_run = sorted(set(planned) - reported)
    summary = {
        "layer": layer,
        "planned": len(planned),
        "executed": len(passed) + len(failed) + len(errors),
        "passed": len(passed),
        "failed": len(failed),
        "errors": len(errors),
        "not_applicable": len(not_applicable),
        "not_run": len(not_run),
        "all_planned_passed": len(passed) == len(planned) and len(planned) > 0,
        "failed_cases": [
            {
                "case_id": r.case_id,
                "status": r.status,
                "checks": [
                    {"name": c.name, "kind": c.kind, "detail": c.detail}
                    for c in r.checks
                    if not c.ok
                ],
            }
            for r in sorted(results, key=lambda item: item.case_id)
            if r.status in {"failed", "error"}
        ],
        "not_applicable_cases": not_applicable,
        "not_run_cases": not_run,
    }
    if layer == "live_model":
        # Deterministic and answer-text checks are reported apart: a fluent answer never makes
        # up for a wrong tool, permission or write, and the reverse is visible too.
        executed = [r for r in results if r.status in {"passed", "failed"}]
        summary["deterministic_passed"] = sum(r.passed("deterministic") for r in executed)
        summary["text_passed"] = sum(r.passed("text") for r in executed)
    return summary


def as_record(result: CaseResult) -> dict:
    return asdict(result)
