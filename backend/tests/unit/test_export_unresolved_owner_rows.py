"""The export must not turn a plausible rejected candidate into an accepted link."""

import gzip
import json

import pytest
from openpyxl import Workbook, load_workbook

from scripts.crm.export_unresolved_owner_rows import export, is_unresolved, sha


def test_candidate_presence_does_not_remove_an_unresolved_row():
    assert is_unresolved(
        {"report_status": "tentative_high_risk", "selected": {"event_key": "sale:guess"}}
    )
    assert is_unresolved({"report_status": "tentative", "selected": {"event_key": "sale:guess"}})
    assert is_unresolved({"report_status": "unresolved", "selected": None})
    assert not is_unresolved({"report_status": "extra_conditional_support"})
    assert not is_unresolved({"report_status": "already_live_recovered"})


def test_new_status_must_be_classified_explicitly():
    with pytest.raises(ValueError, match="Unknown report status"):
        is_unresolved({"report_status": "new_future_status"})


def make_fixture(tmp_path):
    root = tmp_path / "private"
    (root / "sources").mkdir(parents=True)
    (root / "experiment").mkdir()
    filename = "Source.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Owners"
    ws.append(["Owner", "Unit", "Owner", None])
    ws.append(["=literal source text", "001", "Test contact", "Preserve unnamed column"])
    ws["A2"].data_type = "s"
    wb.save(root / "sources" / filename)
    (root / "source-workbooks.json").write_text(
        json.dumps([{"filename": filename, "sha256": sha(root / "sources" / filename)}])
    )
    (root / "parser-mappings.json").write_text(
        json.dumps({filename: [{"sheet": "Owners", "header_row": 1}]})
    )
    row = {
        "row_key": "original-row",
        "filename": filename,
        "sheet": "Owners",
        "row": 2,
        "primary_cause": "no_original_role_correct_full_identifier",
        "report_status": "tentative_high_risk",
        "reason": "two possible units",
        "raw_fields": {"unit_number": "001"},
        "selected": {"event_key": "sale:rejected", "target": {"unit_number": "999"}},
        "conditional_profile_diagnostics": {"example": "failed"},
    }
    with gzip.open(root / "experiment/final-row-results.jsonl.gz", "wt") as f:
        f.write(json.dumps(row) + "\n")
        f.write(json.dumps({"report_status": "extra_conditional_support"}) + "\n")
        f.write(json.dumps({"report_status": "already_live_recovered"}) + "\n")
    return root


def test_export_keeps_all_original_columns_and_labels_rejected_candidates(tmp_path):
    root = make_fixture(tmp_path)
    path = tmp_path / "Unresolved.xlsx"
    result = export(root, path, {"no_original_role_correct_full_identifier": 1})
    assert result["rows"] == result["original_rows_exported"] == 1
    assert result["excluded"] == {"extra_conditional_support": 1, "already_live_recovered": 1}
    wb = load_workbook(path, data_only=False)
    raw = wb["Source 01"]
    assert [raw.cell(1, c).value for c in range(5, 9)] == [
        "Owner",
        "Unit",
        "Owner",
        "(blank column 4)",
    ]
    assert [raw.cell(2, c).value for c in range(5, 9)] == [
        "=literal source text",
        "001",
        "Test contact",
        "Preserve unnamed column",
    ]
    assert raw.cell(2, 5).data_type == "s"
    assert wb["All unresolved"].cell(2, 22).value == "sale:rejected"
    assert "NOT MATCHED" in wb["All unresolved"].cell(1, 22).value
    assert wb["All unresolved"].cell(2, 9).hyperlink.target == "#'Source 01'!A2"
    wb.close()


def test_changed_original_workbook_cannot_be_exported_as_frozen_evidence(tmp_path):
    root = make_fixture(tmp_path)
    with (root / "sources/Source.xlsx").open("ab") as f:
        f.write(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        export(root, tmp_path / "out.xlsx", {"no_original_role_correct_full_identifier": 1})


def test_existing_output_is_not_overwritten(tmp_path):
    path = tmp_path / "important.xlsx"
    path.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        export(tmp_path, path)
    assert path.read_bytes() == b"keep me"
