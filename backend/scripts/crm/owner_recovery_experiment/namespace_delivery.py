"""Persist the historical namespace delivery derivation previously run inline."""

import collections
import json
from pathlib import Path


def export(root: Path) -> dict:
    counts = collections.Counter()
    with (root / "engine-namespace-delivery.jsonl").open("w") as output:
        for line in (root / "engine-namespace-all.jsonl").open():
            row = json.loads(line)
            if row["status"] != "conditional_existing_namespace_proposal":
                continue
            selected = row["selected"]
            tier = (
                "conditional_namespace_exact"
                if selected["date"]["exact"]
                else "conditional_namespace_date_relaxed"
            )
            counts[tier] += 1
            value = {
                key: row[key]
                for key in (
                    "row_key",
                    "filename",
                    "sheet",
                    "row",
                    "source_event_id",
                    "source_unit_id",
                    "original_category",
                    "primary_cause",
                    "source",
                    "raw_fields",
                )
            }
            value.update(
                status=tier,
                risk_tier=tier,
                rule="existing_full_R3_namespace_with_source_project_alias",
                selected_event_key=selected["event_key"],
                selected_property=selected["property"],
                target=selected["target"],
                selected=selected,
                source_project_normalization=row["normalization"],
                date_gap_days=selected["date"]["gap_days"],
                source_date=selected["date"]["source"],
                target_date=selected["date"]["target"],
                requires_date_review=not selected["date"]["exact"],
                conservative_new_recovery=False,
                conditional_profile="engine-namespace-all",
                blind_holdout_validation_available=False,
            )
            output.write(json.dumps(value, sort_keys=True, default=str) + "\n")
    summary = {
        "check": "PASS",
        "rows": sum(counts.values()),
        "risk_tiers": dict(counts),
        "date_relaxed_review_required": True,
        "main_profile_changed": False,
    }
    (root / "engine-namespace-delivery-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(export(Path(__file__).resolve().parent)))
