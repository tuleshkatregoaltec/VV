import io
import re
import zipfile

import openpyxl

from app.crm.import_parsing import _inspect_xlsx, _parse_xlsx


def test_owner_export_without_optional_sheet_dimensions_preserves_source_rows():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Owner Name", "Project", "UnitNumber"])
    sheet.append(["Example Owner", "Example Tower", "101"])
    original = io.BytesIO()
    workbook.save(original)
    workbook.close()
    rewritten = io.BytesIO()
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(rewritten, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = re.sub(rb"<dimension\b[^>]*/>", b"", data)
            target.writestr(item, data)

    data = rewritten.getvalue()
    profiles = _inspect_xlsx(data, "owners.xlsx")
    candidates, total = _parse_xlsx(data, "owners.xlsx", profiles)

    assert profiles[0].meaningful_rows == total == len(candidates) == 1
    assert candidates[0].source_row_number == 2
    assert candidates[0].contact_name == "Example Owner"
    assert candidates[0].unit_number == "101"
    assert candidates[0].party_role == ""
