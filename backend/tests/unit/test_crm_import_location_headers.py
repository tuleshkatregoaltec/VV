"""Location and identifier headers vary between workbooks; none may be dropped silently.

Real owner exports carry the project in ``Project Lnd`` or the master project in
``Master Project Land`` (and DM numbers as ``AreaMuncipalityNumber``). When the parser ignored
them, whole sheets imported with no location and could never be matched to a registry property.
"""

import io

import openpyxl
import pytest

from app.crm.import_parsing import _inspect_xlsx, _parse_xlsx, is_blank, repair_autofill_runs


def _parse(headers, *rows, filename="Example Owners.xlsx"):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    data = stream.getvalue()
    profiles = _inspect_xlsx(data, filename)
    contacts, _ = _parse_xlsx(data, filename, profiles)
    return profiles[0], contacts


def test_sheet_whose_only_project_column_is_project_lnd_still_gets_a_project():
    # Furjan-style export: no other project column, so dropping "Project Lnd" left every row
    # without a location.
    profile, contacts = _parse(
        ["Owner Name", "Project Lnd", "UnitNumber"],
        ["Example Owner", "Westwood By Imtiaz", "101"],
    )

    assert profile.field_map["project_name"] == "Project Lnd"
    assert contacts[0].project_name == "Westwood By Imtiaz"
    assert contacts[0].building_name == "Westwood By Imtiaz"


def test_explicit_project_wins_over_project_lnd_but_blank_cell_falls_back():
    # The explicit column is the better-curated one; the "Lnd" variant only fills its gaps.
    _, contacts = _parse(
        ["Owner Name", "Project", "Project Lnd", "UnitNumber"],
        ["Owner A", "Explicit Project", "Land Project", "1"],
        ["Owner B", None, "Land Project", "2"],
        ["Owner C", "  ", "Land Project", "3"],
    )

    assert [c.project_name for c in contacts] == [
        "Explicit Project",
        "Land Project",
        "Land Project",
    ]


@pytest.mark.parametrize("error", ["#REF!", "#N/A", "#VALUE!", "#DIV/0!", "#NAME?"])
def test_spreadsheet_error_values_are_blank_not_a_location(error):
    # "#REF!" is a broken formula, not a project; using it would invent a location.
    _, contacts = _parse(
        ["Owner Name", "Project", "Project Lnd", "UnitNumber"],
        ["Owner A", error, "Land Project", "1"],
        ["Owner B", error, error, "2"],
    )

    assert contacts[0].project_name == "Land Project"
    assert contacts[1].project_name == ""
    assert error not in contacts[1].area_name


def test_master_project_land_supplies_area_when_master_project_is_absent():
    # Greens-style export: "Master Project Land" holds the community and "Project Lnd" is #REF!.
    profile, contacts = _parse(
        ["Owner Name", "Master Project Land", "Project Lnd", "UnitNumber"],
        ["Example Owner", "Greens", "#REF!", "101"],
    )

    assert profile.field_map["master_project"] == "Master Project Land"
    assert contacts[0].area_name == "Greens"
    assert contacts[0].project_name == "Greens"
    assert "#REF!" not in {contacts[0].area_name, contacts[0].project_name}


def test_explicit_master_project_wins_over_master_project_land():
    _, contacts = _parse(
        ["Owner Name", "Master Project", "Master Project Land", "UnitNumber"],
        ["Owner A", "Explicit Master", "Land Master", "1"],
        ["Owner B", "#REF!", "Land Master", "2"],
    )

    assert [c.area_name for c in contacts] == ["Explicit Master", "Land Master"]


def test_project_lnd_beats_master_project_as_the_project_fallback():
    # With a Master Project column present (Furjan OLD), the specific Project Lnd must still be
    # preferred over repeating the master project as the project.
    _, contacts = _parse(
        ["Owner Name", "Master Project", "Project Lnd", "UnitNumber"],
        ["Example Owner", "Al Furjan", "Prime Townhouses", "101"],
    )

    assert contacts[0].area_name == "Al Furjan"
    assert contacts[0].project_name == "Prime Townhouses"


def test_misspelled_municipality_number_headers_keep_their_identifiers():
    # JVT workbooks spell "Muncipality"; the sibling sheets call these Municipality No / Sub No.
    profile, contacts = _parse(
        ["Owner Name", "Project", "UnitNumber", "AreaMuncipalityNumber", "LandMuncipalityNumber"],
        ["Example Owner", "The Ivy", "101", 684, 9747],
    )

    assert profile.field_map["municipality_number"] == "AreaMuncipalityNumber"
    assert profile.field_map["municipality_sub_number"] == "LandMuncipalityNumber"
    identifiers = contacts[0].evidence["source_identifiers"]
    assert identifiers["municipality_number"] == "684"
    assert identifiers["municipality_sub_number"] == "9747"


def test_dropped_data_columns_are_named_in_a_warning():
    # A column the parser does not read must be visible, not silently lost.
    profile, _ = _parse(
        ["Owner Name", "Project", "UnitNumber", "Plot Size", "Built Up"],
        ["Example Owner", "The Ivy", "101", 200, 150],
    )

    warning = next(w for w in profile.warnings if w.startswith("Columns not imported"))
    assert "Plot Size" in warning and "Built Up" in warning
    assert "Project" not in warning.replace("Columns not imported", "")


def test_fully_mapped_sheet_has_no_dropped_column_warning():
    profile, _ = _parse(
        ["Owner Name", "Project Lnd", "UnitNumber", "Mobile"],
        ["Example Owner", "The Ivy", "101", "0501234567"],
    )

    assert not [w for w in profile.warnings if w.startswith("Columns not imported")]


def test_owner_identity_columns_are_not_listed_as_dropped():
    # Identity documents are deliberately never imported; the warning is for property data.
    profile, _ = _parse(
        ["Owner Name", "Project", "UnitNumber", "IdNumber", "Nationality", "Birth Date"],
        ["Example Owner", "The Ivy", "101", "X", "Y", "2000-01-01"],
    )

    assert not [w for w in profile.warnings if w.startswith("Columns not imported")]


def test_land_variant_is_an_ordered_fallback_when_the_explicit_column_exists():
    # Later tasks read the fallback order from the profile instead of private parser helpers.
    profile, _ = _parse(
        ["Owner Name", "Project", "Project Lnd", "Master Project", "Master Project Land", "Unit"],
        ["Example Owner", "A", "B", "C", "D", "1"],
    )

    assert profile.field_map["project_name"] == "Project"
    assert profile.fallback_map["project_name"] == ["Project Lnd"]
    assert profile.field_map["master_project"] == "Master Project"
    assert profile.fallback_map["master_project"] == ["Master Project Land"]


@pytest.mark.parametrize(
    "value", [None, "", "  ", "0", 0, "null", "NULL", "None", "n/a", "N/A", "-", "#REF!", "#ref!"]
)
def test_is_blank_covers_placeholders_and_spreadsheet_errors(value):
    assert is_blank(value) is True


@pytest.mark.parametrize("value", ["Damac Hills", 1, "0 Marina", "Null Street", "#1 Tower"])
def test_is_blank_keeps_real_values(value):
    assert is_blank(value) is False


def test_unmapped_data_headers_are_listed():
    profile, _ = _parse(
        ["Owner Name", "Project", "UnitNumber", "Sub Type", "Empty Notes"],
        ["Example Owner", "The Ivy", "101", "Studio", None],
    )

    # Only columns that actually hold data are reported; a personal column is never listed.
    assert profile.unmapped_headers == ["Sub Type"]
    assert "Sub Type" in next(w for w in profile.warnings if w.startswith("Columns not imported"))
    assert "Empty Notes" not in " ".join(profile.warnings)


def test_personal_column_is_never_listed_as_unmapped():
    profile, _ = _parse(
        ["Owner Name", "Project", "UnitNumber", "Passport No", "Other Owner Name"],
        ["Example Owner", "The Ivy", "101", "X123", "Someone Else"],
    )

    assert profile.unmapped_headers == []


def test_every_unmapped_header_is_named_in_the_warning():
    headers = ["Owner Name", "Project", "UnitNumber"] + [f"Extra {n}" for n in range(15)]
    profile, _ = _parse(headers, ["Example Owner", "The Ivy", "101"] + list(range(1, 16)))

    warning = next(w for w in profile.warnings if w.startswith("Columns not imported"))
    assert all(f"Extra {n}" in warning for n in range(15))


def _autofill(first_row, count, base="DAMAC HILLS", offset=97):
    return [(first_row + i, f"{base} {first_row + i - offset}") for i in range(count)]


def test_damac_autofill_run_restored_to_seed_label():
    # Excel autofill turned the seed "DAMAC HILLS 2" into DAMAC HILLS 3, 4, 5, ... row by row.
    values = [(99, "DAMAC HILLS 2"), *_autofill(100, 100)]

    repaired = repair_autofill_runs(values)

    assert repaired == {row: "DAMAC HILLS 2" for row in range(100, 200)}


def test_short_numbered_runs_are_left_alone():
    values = [(99, "DAMAC HILLS 2"), *_autofill(100, 10)]

    assert repair_autofill_runs(values) == {}


def test_numbering_that_does_not_follow_the_row_number_is_not_autofill():
    # Real buildings numbered 1..N independent of the sheet row are data, not an artefact.
    values = [(100 + i, f"TOWER {i % 7 + 1}") for i in range(120)]

    assert repair_autofill_runs(values) == {}


def test_autofill_run_stops_at_a_blank_or_different_label():
    values = [
        (99, "DAMAC HILLS 2"),
        *_autofill(100, 60),
        (160, None),
        *_autofill(161, 60),
    ]

    repaired = repair_autofill_runs(values)

    # The blank breaks the run; the second block has no seed row before it, so its first row is
    # taken as the seed and the rest are restored to that label.
    assert {row for row, label in repaired.items() if label == "DAMAC HILLS 2"} == set(
        range(100, 160)
    )
    assert repaired[162] == "DAMAC HILLS 64"


def test_parser_repairs_autofill_labels_and_keeps_the_original():
    rows = [["Example Owner", f"DAMAC HILLS {n}", "VILLA-1"] for n in range(2, 2 + 80)]
    # Row 2 holds the seed (n=2); rows 3.. then follow n = row_number (autofill drag).
    profile, contacts = _parse(["Owner Name", "Project", "UnitNumber"], *rows)

    assert {c.project_name for c in contacts} == {"DAMAC HILLS 2"}
    assert contacts[10].evidence["original_fields"]["project_name"] == "DAMAC HILLS 12"
    assert "original_fields" not in contacts[0].evidence
    assert any("autofill" in w.lower() for w in profile.warnings)
