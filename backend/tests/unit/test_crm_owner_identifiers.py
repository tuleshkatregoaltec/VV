"""Owner-sheet identifiers: one unit key and one extractor shared by the owner matcher."""

from __future__ import annotations

import pytest

from app.crm.owner_identifiers import (
    SourceIdentifier,
    event_unit_keys,
    is_ordinal_label,
    source_identifiers,
    unit_key,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2510 (Q 3)", "2510"),
        ("FLAT 415", "415"),
        ("Unit No. 415", "415"),
        ("415", "415"),
        ("A-101", "A101"),
        ("A 101", "A101"),
        ("0103", "103"),
        ("DH2-XR1139B", "XR1139B"),
        ("AFNCTH003", "AFNCTH3"),
        ("DL-K138", "K138"),
        ("AR3-2A-SD-034", "AR32ASD34"),
        ("", ""),
    ],
)
def test_unit_key_matches_analytics_examples(raw: str, expected: str) -> None:
    assert unit_key(raw) == expected


def test_r3_building_number_is_namespaced_villa() -> None:
    assert source_identifiers({"building_number": "R3 Ruba-V-357"}) == [
        SourceIdentifier("villa", "R3 Ruba-V-357", "357", "ruba")
    ]


def test_full_plot_code_is_never_truncated() -> None:
    found = source_identifiers({"plot_number": "AFMU019B"})
    assert [i.key for i in found] == ["AFMU19B"]
    assert all(i.key != "19B" for i in found)


def test_blank_noise_yields_nothing() -> None:
    fields = {"unit_number": "null", "plot_number": 0, "building_number": "#REF!"}
    assert source_identifiers(fields) == []


def test_flat_ignores_parent_plot_code() -> None:
    fields = {"unit_number": "1111", "plot_number": "AFMU009_10A", "building_number": "1"}
    assert source_identifiers(fields) == [SourceIdentifier("unit", "1111", "1111", "")]


def test_namespaced_villa_suppresses_bare_duplicate() -> None:
    fields = {"building_number": "R3 Sun-V-157", "plot_number": "157", "property_number": "161"}
    found = source_identifiers(fields)
    assert SourceIdentifier("villa", "R3 Sun-V-157", "157", "sun") in found
    assert [i.key for i in found if not i.namespace] == ["161"]


def test_namespaced_villa_is_kept_when_unit_number_is_present() -> None:
    fields = {"unit_number": "9", "building_number": "R3 Sun-V-157"}
    assert {(i.kind, i.key) for i in source_identifiers(fields)} == {
        ("unit", "9"),
        ("villa", "157"),
    }


def test_two_different_villa_codes_are_both_returned() -> None:
    fields = {"building_number": "R3 Sun-V-118", "building_name": "R3 Sun-V-122"}
    assert [(i.namespace, i.key) for i in source_identifiers(fields)] == [
        ("sun", "118"),
        ("sun", "122"),
    ]


def test_kind_comes_from_the_column() -> None:
    fields = {"plot_number": "P-7", "property_number": "55"}
    assert [(i.kind, i.key) for i in source_identifiers(fields)] == [
        ("plot", "P7"),
        ("property", "55"),
    ]
    assert source_identifiers({"unit_number": "101"})[0].kind == "unit"


def test_building_name_counts_only_when_it_is_an_identifier() -> None:
    assert [i.key for i in source_identifiers({"building_name": "357"})] == ["357"]
    assert source_identifiers({"building_name": "Navitas Tower E"}) == []


def test_spreadsheet_numbers_do_not_grow_a_digit() -> None:
    found = source_identifiers({"unit_number": 101.0, "plot_number": "0.0"})
    assert [i.key for i in found] == ["101"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("R3 Sun-V-259", ("R3SUNV259", "259")),
        ("R3 Spring-V-055", ("R3SPRINGV55", "55")),
        ("415", ("415",)),
        ("DH2-XR1139B", ("XR1139B",)),
        ("", ()),
    ],
)
def test_event_unit_keys_index_a_villa_code_under_both_forms(
    raw: str, expected: tuple[str, ...]
) -> None:
    assert event_unit_keys(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["1", "01", "9", "VILLA NO. 1", "VILLA NUMBER 1", "VILLA-1", "VILLA - 1", "UNIT-01", "Villa 12"]
    + ["TOWNHOUSE 9", "B1", "G01", "VILLA.99"],
)
def test_ordinal_labels_are_not_identifiers(raw: str) -> None:
    assert is_ordinal_label(raw)


@pytest.mark.parametrize(
    "raw",
    ["101", "1410", "VILLA 101", "UNIT 1410", "A-101", "AFWETH017", "DH2-XL1282B", "12A", "327"]
    + ["S 3 Community B-TH-331", "R3 Sun-V-9", "", "null"],
)
def test_apartment_numbers_and_codes_are_not_ordinal(raw: str) -> None:
    assert not is_ordinal_label(raw)


def test_source_identifiers_flag_the_ordinal_and_keep_the_plot_code() -> None:
    # Furjan OLD 12339: BuildingNo "VILLA NUMBER 1" next to the plot code AFWETH017.
    found = source_identifiers({"building_number": "VILLA NUMBER 1", "plot_number": "AFWETH017"})
    assert [(i.raw, i.ordinal) for i in found] == [("VILLA NUMBER 1", True), ("AFWETH017", False)]


def test_a_namespaced_villa_code_is_never_ordinal() -> None:
    assert not source_identifiers({"building_number": "R3 Sun-V-9"})[0].ordinal


def test_identifiers_remember_their_column() -> None:
    found = source_identifiers(
        {"unit_number": "112", "property_number": "113", "building_name": "789"}
    )
    assert [(i.column, i.key) for i in found] == [
        ("unit_number", "112"),
        ("property_number", "113"),
        ("building_name", "789"),
    ]
