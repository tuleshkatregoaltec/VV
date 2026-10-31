"""Flat identifiers in company sheets must survive without borrowing plot IDs."""

import io

import openpyxl
import pytest

from app.crm.import_parsing import _inspect_xlsx, _parse_xlsx


@pytest.mark.parametrize("header", ["FLAT NUMBER", " FLAT NUMBER", "Flat No."])
def test_flat_number_is_mapped_independently_of_plot_number(header):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["PLOT NUMBER", header, "OWNER NAME", "BUILDING NAME"])
    sheet.append(["19.0001D", "1204", "Example Owner", "Example Tower"])
    stream = io.BytesIO()
    workbook.save(stream)
    data = stream.getvalue()

    profiles = _inspect_xlsx(data, "Example Tower March 2025.xlsx")
    contacts, nonblank = _parse_xlsx(data, "Example Tower March 2025.xlsx", profiles)

    assert nonblank == 1 and len(contacts) == 1
    assert profiles[0].field_map["unit_number"] == header.strip()
    assert profiles[0].field_map["plot_number"] == "PLOT NUMBER"
    assert contacts[0].unit_number == "1204"
    assert contacts[0].building_name == "Example Tower"
