"""Reject expanded work before workbook libraries allocate it; retain normal files."""

import io
from unittest.mock import Mock
from zipfile import ZIP_DEFLATED, ZipFile

import openpyxl
import pytest

from app.crm import import_parsing, import_safety


def workbook_archive(extra_name, content):
    result = io.BytesIO()
    with ZipFile(result, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr(extra_name, content)
    return result.getvalue()


def test_expansion_rejected_before_openpyxl(monkeypatch):
    monkeypatch.setattr(import_safety, "_MAX_EXPANDED_BYTES", 100)
    decoder = Mock(side_effect=AssertionError("must not allocate unsafe workbook"))
    monkeypatch.setattr(import_parsing.openpyxl, "load_workbook", decoder)
    with pytest.raises(ValueError, match="expanded size"):
        import_parsing._inspect_xlsx(
            workbook_archive("xl/worksheets/sheet1.xml", "x" * 500), "owners.xlsx"
        )
    decoder.assert_not_called()


def test_high_ratio_and_shared_strings_have_independent_bounds(monkeypatch):
    with pytest.raises(ValueError, match="compression ratio"):
        import_safety.validate_xlsx(workbook_archive("xl/worksheets/sheet1.xml", "a" * 2_000_000))
    monkeypatch.setattr(import_safety, "_MAX_SHARED_STRINGS_BYTES", 100)
    with pytest.raises(ValueError, match="shared strings"):
        import_safety.validate_xlsx(workbook_archive("xl/sharedStrings.xml", "x" * 500))


def test_archive_member_path_and_count_are_bounded(monkeypatch):
    with pytest.raises(ValueError, match="ambiguous archive paths"):
        import_safety.validate_xlsx(workbook_archive("../outside.xml", "x"))
    monkeypatch.setattr(import_safety, "_MAX_MEMBERS", 2)
    with pytest.raises(ValueError, match="too many"):
        import_safety.validate_xlsx(workbook_archive("xl/worksheets/sheet1.xml", "x"))


def test_normal_workbook_and_bounded_csv_remain_supported():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Owner", "Unit"])
    sheet.append(["Synthetic", "101"])
    result = io.BytesIO()
    workbook.save(result)
    import_safety.validate_xlsx(result.getvalue())
    assert import_safety.csv_rows(b"Owner,Unit\nSynthetic,101\n", max_rows=2) == [
        ["Owner", "Unit"],
        ["Synthetic", "101"],
    ]
    with pytest.raises(ValueError, match="row limit"):
        import_safety.csv_rows(b"a\nb\nc\n", max_rows=2)
    with pytest.raises(ValueError, match="column limit"):
        import_safety.csv_rows(("," * import_safety.MAX_IMPORT_COLUMNS).encode())
