"""Property-first owner matcher: unit first, then the sale within 2 AED, then the Transactions pass.

Fixture values are real DXBI / DLD values from the 29-row trial run (2026-10-29). Dates never
decide a match, so most tests give a source date far from the sale date on purpose.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.crm.owner_matcher import (
    MATCHER_VERSION,
    MatchResult,
    SalesIndex,
    later_sale_date,
    match_row,
    promote_learned_aliases,
)
from app.crm.owner_places import PlaceIndex, load_place_aliases

COMMUNITIES = (
    "damachills2",
    "damachills",
    "alfurjan",
    "arabianranches3",
    "arabianranches",
    "citywalk",
    "emiratesliving",
    "liwan",
)
PROJECT_ALIASES, MASTER_ALIASES = load_place_aliases()
# Analytics buildings the sheets name (building-keys.json). A sheet label restricts the place only
# when it is one of these; DLD packages and phases are not.
KNOWN_BUILDINGS = (
    ("damachills2", "navitastowera"),
    ("damachills2", "navitastowere"),
    ("damachills2", "viridisa"),
    ("damachills2", "viridisb"),
    ("damachills2", "viridisc"),
    ("damachills2", "viridisd"),
    ("damachills2", "aster"),
    ("alfurjan", "quortaj"),
    ("alfurjan", "quortaj2"),
    ("alfurjan", "aziziberton"),
    ("alwasl", "vervetowera"),
    ("alwasl", "vervetowerb"),
    ("arabianranches3", "ruba"),
    ("arabianranches3", "sun"),
    ("arabianranches3", "spring"),
)
PLACES = PlaceIndex(
    [{"community_key": key, "name_key": key} for key in COMMUNITIES]
    + [{"community_key": community, "name_key": name} for community, name in KNOWN_BUILDINGS],
    PROJECT_ALIASES,
    MASTER_ALIASES,
)


def event(
    unit: str,
    building: str,
    amount: float,
    *,
    family: str = "sale",
    area: str = "Damac Hills 2",
    project: str = "",
    size: float | None = None,
    date: str = "2022-01-01",
    kind: str = "Apartment",
    key: str | None = None,
) -> dict[str, Any]:
    return {
        "family": family,
        "amount": amount,
        "event_date": date,
        "unit_number": unit,
        "building_name": building,
        "project_name": project,
        "area_name": area,
        "size_sqft": size,
        "property_type": kind,
        "event_key": key or f"{family}-{building}-{unit}-{amount}-{date}",
    }


def transaction(
    amount: float,
    *,
    sqm: float,
    master: str,
    area: str = "",
    project: str = "",
    building: str = "",
    unit: str = "",
    procedure: str = "Sell",
    date: str = "2023-01-01",
    status: str = "dld_only",
) -> dict[str, Any]:
    return {
        "instance_date": date,
        "procedure_name_en": procedure,
        "actual_worth": amount,
        "procedure_area": sqm,
        "property_type_en": "Unit",
        "area_name_en": area,
        "master_project_en": master,
        "project_name_en": project,
        "building_name_en": building,
        "unit_number": unit,
        "community_name": master,
        "match_status": status,
    }


def match(
    source: dict[str, Any],
    events: list[dict[str, Any]],
    registry: list[dict[str, Any]] | None = None,
) -> MatchResult:
    return match_row(source, SalesIndex(events, PLACES, registry or []))


NAVITAS = {
    "master_project": "DAMAC HILLS 2",
    "building_name": "NAVITAS ( E )@AKOYA OXYGEN",
    "unit_number": "1410",
    "property_type": "Hotel Rooms",
    "size_unknown": "31.01",
    "transaction_price_aed": "460000",
    "transaction_date": "2022-05-20 00:00:00",
}
NAVITAS_WORLD = [
    event("1410", "Navitas Tower E", 441750, project="Navitas", size=334, date="2016-10-06"),
    event("1410", "Navitas Tower E", 460000, project="Navitas", size=334, date="2022-05-20"),
    event("1410", "Viridis A", 750000, project="Viridis", size=804, date="2026-09-18"),
    event("1410", "Golf Vita - A", 460000, project="Golf Vita", area="Damac Hills", size=428),
]


def test_version_is_stamped() -> None:
    assert MATCHER_VERSION == "property-first-2"


def test_navitas_1410_matches_sale() -> None:
    result = match(NAVITAS, NAVITAS_WORLD)
    assert result.outcome == "matched_sale"
    assert result.sale is not None and result.sale["event_date"] == "2022-05-20"
    assert result.property_key == ("navitase", "1410")


def test_hotel_rooms_label_does_not_veto() -> None:
    result = match(NAVITAS, NAVITAS_WORLD)
    assert result.outcome == "matched_sale"
    assert any(w.startswith("type_label_differs") for w in result.warnings)


def test_furjan_afncth003_matches_sale_under_legal_area() -> None:
    source = {
        "master_project": "Al Furjan",
        "project_name": "Al Furjan",
        "building_number": "VILLA NO. 1",
        "plot_number": "AFNCTH003",
        "size_unknown": "896",
        "transaction_price_aed": "687500",
        "transaction_date": "2023-09-11 00:00:00",
    }
    plot = dict(area="Jabal Ali 1", size=9644, kind="Plot")
    result = match(
        source,
        [
            event("AFNCTH003", "Al Furjan", 2870000, date="2015-07-21", **plot),
            event("AFNCTH003", "Al Furjan", 687500, date="2023-09-13", **plot),
        ],
    )
    assert result.outcome == "matched_sale"
    assert result.sale is not None and result.sale["event_date"] == "2023-09-13"
    assert result.property_key is not None and result.property_key[1] == "AFNCTH3"


def test_ruba_357_matches_despite_date_gap() -> None:
    source = {
        "master_project": "Arabian Ranches 3",
        "project_name": "Arabian Ranches lll - Ruba",
        "building_name": "357",
        "building_number": "R3 Ruba-V-357",
        "plot_number": "AR3-2A-SD-34",
        "size_unknown": "260.51",
        "transaction_price_aed": "2200888",
        "transaction_date": "2024-03-18 00:00:00",
    }
    ar3 = dict(area="Arabian Ranches 3", project="Arabian Ranches 3", kind="Villa")
    result = match(
        source,
        [
            event("357", "Ruba", 2200888, size=2804, date="2021-08-23", **ar3),
            event("357", "Sun", 2200888, size=2408, date="2020-07-16", **ar3),
            event("357", "Anya 1", 2704888, size=2682, date="2023-03-01", **ar3),
        ],
    )
    assert result.outcome == "matched_sale"
    assert result.sale is not None and result.sale["event_date"] == "2021-08-23"
    assert result.property_key == ("ruba", "357")


def test_damac_no_identifier_unique_price_size_matches_inferred_unit() -> None:
    source = {
        "master_project": "DAMAC HILLS 2",
        "size_unknown": "174.8",
        "transaction_price_aed": "370000",
        "transaction_date": "2022-03-03 00:00:00",
    }
    result = match(
        source,
        [
            event("DH2-XL1282B", "Mulberry", 370000, size=1882, kind="Villa"),
            event("DH2-XM9", "Mulberry", 370000, size=1100, kind="Villa"),  # wrong size
            event("B1", "Golf Vita", 370000, area="Damac Hills", size=1882),  # other community
        ],
    )
    assert result.outcome == "matched_sale_inferred_unit"
    assert result.property_key is not None and result.property_key[1] == "XL1282B"
    assert any("sqm" in reason for reason in result.reasons)


def test_ambiguous_price_size_is_no_evidence_with_candidates() -> None:
    source = {
        "master_project": "DAMAC HILLS 2",
        "size_unknown": "112.24",
        "transaction_price_aed": "450000",
    }
    result = match(
        source,
        [
            event("XW1002B", "Mulberry", 450000, size=1208),
            event("XV776B", "Mulberry", 450000, size=1208),
        ],
    )
    assert result.outcome == "no_evidence"
    assert "ambiguous_price_size" in result.reasons
    assert {r["unit_number"] for r in result.rejected} == {"XW1002B", "XV776B"}


def test_prime_townhouses_afwbth023_matches_sale() -> None:
    source = {
        "master_project": "Al Furjan",
        "project_name": "Prime Townhouses",
        "building_number": "TH 23-1",
        "plot_number": "AFWBTH023",
        "size_unknown": "896",
        "transaction_price_aed": "1832447.4",
        "transaction_date": "2020-11-03 00:00:00",
    }
    prime = dict(area="Al Furjan", project="Prime Townhouses")
    result = match(
        source,
        [
            event("AFWBTH023", "Prime Townhouses", 1832447, size=9644, date="2020-11-03", **prime),
            event("TH 23-1", "Prime Townhouses", 1500, family="rental", size=9644, **prime),
        ],
    )
    assert result.outcome == "matched_sale"
    assert result.property_key is not None and result.property_key[1] == "AFWBTH23"


BERTON = {
    "master_project": "Al Furjan",
    "project_name": "Azizi Berton",
    "building_name": "Azizi Berton",
    "unit_number": "211",
    "building_number": "1",
    "plot_number": "AFC016",
    "size_unknown": "37.27",
    "transaction_price_aed": "386400",
    "transaction_date": "2023-11-22 00:00:00",
}
BERTON_WORLD = [
    event("211", "Azizi Berton", 24000, family="rental", area="Al Furjan", size=401),
    event("620", "Azizi Berton", 386400, area="Al Furjan", size=385, date="2023-09-08"),
]


def test_azizi_berton_211_is_property_confirmed_not_620() -> None:
    result = match(BERTON, BERTON_WORLD)
    assert result.outcome == "property_confirmed_no_sale"
    assert result.property_key is not None and result.property_key[1] == "211"
    assert result.sale is None
    assert [(r["unit_number"], r["reason"]) for r in result.rejected] == [
        ("620", "different_unit_same_price")
    ]


def test_azizi_berton_211_matches_registry_sale_by_elimination() -> None:
    berton = dict(master="Al Furjan", area="Jabal Ali First", project="Azizi Berton")
    registry = [
        transaction(386400, sqm=36.93, building="Azizi Berton", date="2023-08-28", **berton),
        transaction(386400, sqm=36.98, unit="209", building="Azizi Berton", **berton),
        transaction(386400, sqm=35.77, unit="620", building="Azizi Berton", **berton),
        transaction(  # same price and size, another Furjan building
            386400,
            sqm=36.98,
            unit="1103",
            master="Al Furjan",
            project="Azizi Shaista Residence",
            building="Azizi Shaista Residence",
        ),
    ]
    result = match(BERTON, BERTON_WORLD, registry)
    assert result.outcome == "matched_registry_sale"
    assert result.sale is registry[0]
    assert result.property_key is not None and result.property_key[1] == "211"


def test_aster_no_unit_matches_registry_sale() -> None:
    source = {
        "master_project": "DAMAC HILLS 2",
        "size_unknown": "173.06",
        "transaction_price_aed": "325990",
    }
    aster = transaction(
        325990,
        sqm=173.06,
        master="DAMAC HILLS 2",
        area="Madinat Hind 4",
        project="DAMAC HILLS (2) - ASTER",
        procedure="Grant",
    )
    elsewhere = transaction(
        325990, sqm=173.06, master="DAMAC HILLS", area="Al Hebiah Third", project="CARSON"
    )
    result = match(source, [], [aster, elsewhere])
    assert result.outcome == "matched_registry_sale_no_unit"
    assert result.sale is aster
    assert result.property_key is None


def test_city_walk_unit_differs_goes_to_review() -> None:
    source = {
        "master_project": "City Walk",
        "project_name": "NO. 4A, NO.4B, NO.5 CITYWALK RESIDENTIAL",
        "building_name": "Citywalk Residential Building 5",
        "unit_number": "102",
        "size_unknown": "107.63",
        "transaction_price_aed": "850000",
        "transaction_date": "2021-06-20 00:00:00",
    }
    walk = dict(area="City Walk", family="rental", size=1160)
    events = [
        event("102", "Citywalk Residential Building 5", 90000, **walk),
        event("102", "Building 4a (CW)", 90000, **walk),
    ]
    other_unit = transaction(
        850000,
        sqm=107.63,
        master="City Walk",
        area="Al Wasl",
        project="CITYWALK RESIDENTIAL",
        building="Citywalk Residential Building 5",
        unit="715",
        status="matched",
    )
    result = match(source, events, [other_unit])
    assert result.outcome == "matched_sale_review"
    assert result.sale is other_unit
    assert any("unit" in reason for reason in result.reasons)


SUN = {
    "master_project": "Arabian Ranches 3",
    "project_name": "Arabian Ranches III - SUN",
    "building_name": "R3 Sun-V-122",
    "building_number": "R3 Sun-V-118",
    "plot_number": "AR3.B.37",
    "size_unknown": "128.58",
    "transaction_price_aed": "700000",
    "transaction_date": "2023-01-31 00:00:00",
}
AR3 = dict(area="Arabian Ranches 3", project="Arabian Ranches 3", kind="Villa")


def test_sun_two_villas_goes_to_review() -> None:
    liwan = event("19", "Mazaya 19", 700000, area="Liwan", project="Qpoint", size=1384)
    result = match(
        SUN,
        [
            event("118", "Sun", 1900000, size=1384, date="2021-02-01", **AR3),
            event("122", "Sun", 1300000, size=1384, date="2021-03-01", **AR3),
            event("122", "Sun", 700000, size=692, date="2023-02-10", **AR3),
            liwan,
        ],
    )
    assert result.outcome == "matched_sale_review"
    assert result.sale is not None and result.sale["building_name"] == "Sun"
    assert result.sale["amount"] == 700000
    assert any(w.startswith("sheet_names_two_villas") for w in result.warnings)


def test_ar3_name_column_villa_that_sold_is_the_match() -> None:
    # AR3 writes "R3 Sun-V-173" in BuildingNo and "177" in BuildingNameEn: two numberings, the name
    # column 1-5 higher. DXBI follows the name column (3,480 of 3,514 differing rows), so when only
    # that villa sold at this price it is green, with the renumbering noted.
    source = {**SUN, "building_number": "R3 Sun-V-173", "building_name": "177"}
    world = [
        event("173", "Sun", 1900000, size=1384, date="2021-02-01", **AR3),
        event("177", "Sun", 700000, size=1384, date="2023-02-10", **AR3),
    ]
    result = match(source, world)
    assert result.outcome == "matched_sale"
    assert result.sale is not None and result.sale["unit_number"] == "177"
    assert any(w.startswith("buildingno_renumbered") for w in result.warnings)


def test_ar3_buildingno_villa_that_sold_goes_to_review() -> None:
    # The rare opposite (6 of 3,514): only the BuildingNo villa sold at this price. That goes
    # against how DXBI numbers AR3, so a person decides.
    source = {**SUN, "building_number": "R3 Sun-V-173", "building_name": "177"}
    world = [
        event("173", "Sun", 700000, size=1384, date="2021-02-01", **AR3),
        event("177", "Sun", 1900000, size=1384, date="2023-02-10", **AR3),
    ]
    result = match(source, world)
    assert result.outcome == "matched_sale_review"
    assert result.sale is not None and result.sale["unit_number"] == "173"
    assert any(w.startswith("sheet_names_two_units") for w in result.warnings)


def test_share_sale_keeps_the_match_and_warns() -> None:
    source = {**SUN, "building_number": "", "building_name": "R3 Sun-V-122"}
    world = [
        event("122", "Sun", 1300000, size=1384, date="2021-03-01", **AR3),
        event("122", "Sun", 700000, size=692, date="2023-02-10", **AR3),
    ]
    result = match(source, world)
    assert result.outcome == "matched_sale"
    assert "share_sale" in result.warnings


def test_sale_size_is_checked_not_any_event_on_the_unit() -> None:
    # 1,384 sqft matches the unit's other sale, but the 700,000 sale is 900 sqft: not half of it.
    # The unit is identified and sold at this price, so the size is a warning, not a rejection,
    # and the warning is not the share-sale one. A different size basis is never green (v2c).
    source = {**SUN, "building_number": "", "building_name": "R3 Sun-V-122"}
    world = [
        event("122", "Sun", 1300000, size=1384, date="2021-03-01", **AR3),
        event("122", "Sun", 700000, size=900, date="2023-02-10", **AR3),
    ]
    result = match(source, world)
    assert result.outcome == "matched_sale_review"
    assert "size_basis_differs" in result.warnings
    assert "share_sale" not in result.warnings


def test_liwan_candidate_rejected_different_community() -> None:
    source = {**SUN, "building_number": "", "building_name": "R3 Sun-V-122"}
    liwan = event("122", "Mazaya 19", 700000, area="Liwan", project="Qpoint", size=1384)
    result = match(source, [liwan])
    assert result.outcome == "no_evidence"
    assert "unit_not_in_dxbi" in result.reasons
    assert [(r["building_name"], r["reason"]) for r in result.rejected] == [
        ("Mazaya 19", "different_community")
    ]


def test_named_building_wins_over_same_number_elsewhere() -> None:
    source = {
        "master_project": "DAMAC HILLS 2",
        "building_name": "VIRIDIS D",
        "unit_number": "1006",
        "size_unknown": "39.86",
        "transaction_price_aed": "340000",
    }
    world = [
        event("1006", "Viridis A", 340000, size=429, project="Viridis"),
        event("1006", "Viridis B", 340000, size=429, project="Viridis"),
    ]
    result = match(source, world)
    assert result.outcome == "no_evidence"
    assert "unit_not_in_dxbi" in result.reasons
    assert result.sale is None


def test_repeat_price_same_property_uses_nearest_and_flags() -> None:
    source = {
        **NAVITAS,
        "unit_number": "1410",
        "transaction_date": "2021-12-01",
        "transaction_price_aed": "460000",
    }
    world = [
        event("1410", "Navitas Tower E", 460000, project="Navitas", size=334, date="2019-01-05"),
        event("1410", "Navitas Tower E", 460000, project="Navitas", size=334, date="2022-02-01"),
        event("1411", "Navitas Tower E", 460000, project="Navitas", size=334, date="2021-12-01"),
    ]
    result = match(source, world)
    assert result.outcome == "matched_sale"
    assert result.sale is not None and result.sale["event_date"] == "2022-02-01"
    assert result.property_key == ("navitase", "1410")
    assert "repeat_price" in result.warnings


def test_size_conflict_on_a_unit_without_a_sale_at_the_price_is_rejected() -> None:
    # No sale within 2 AED on the unit, so nothing proves the sheet means this unit.
    source = {**NAVITAS, "size_unknown": "120", "transaction_price_aed": "500000"}
    result = match(source, NAVITAS_WORLD)
    assert result.outcome == "rejected"
    assert "size_conflict" in result.reasons


@pytest.mark.parametrize(
    "procedure",
    ["Mortgage Registration", "Lease Finance Registration", "Lease To Own Registration", "Modify"],
)
def test_mortgage_is_never_a_sale(procedure: str) -> None:
    source = {
        "master_project": "DAMAC HILLS 2",
        "size_unknown": "173.06",
        "transaction_price_aed": "325990",
    }
    financing = transaction(
        325990, sqm=173.06, master="DAMAC HILLS 2", project="ASTER", procedure=procedure
    )
    result = match(source, [], [financing])
    assert result.outcome == "no_evidence"
    assert result.sale is None


def test_registry_pass_with_two_fitting_sales_stays_unmatched() -> None:
    source = {
        "master_project": "DAMAC HILLS 2",
        "size_unknown": "173.06",
        "transaction_price_aed": "325990",
    }
    rows = [
        transaction(325990, sqm=173.06, master="DAMAC HILLS 2", project="ASTER"),
        transaction(325990, sqm=173.1, master="DAMAC HILLS 2", project="MULBERRY"),
    ]
    assert match(source, [], rows).outcome == "no_evidence"


def test_registry_pass_with_two_unit_codes_goes_to_review() -> None:
    source = {**BERTON, "unit_number": "", "building_number": "209", "building_name": "211"}
    row = transaction(
        386400,
        sqm=36.93,
        master="Al Furjan",
        project="Azizi Berton",
        building="Azizi Berton",
    )
    result = match(source, BERTON_WORLD, [row])
    assert result.outcome == "matched_sale_review"
    assert result.sale is row


def test_no_place_and_no_identifier_is_no_evidence() -> None:
    source = {"size_unknown": "100", "transaction_price_aed": "500000"}
    assert match(source, [event("1", "X", 500000, size=1076)]).outcome == "no_evidence"


def test_amount_uses_decimal_two_dirham_window() -> None:
    inside = {**NAVITAS, "transaction_price_aed": Decimal("460002")}
    outside = {**NAVITAS, "transaction_price_aed": Decimal("460002.01")}
    assert match(inside, NAVITAS_WORLD).outcome == "matched_sale"
    assert match(outside, NAVITAS_WORLD).outcome == "property_confirmed_no_sale"


# (case id, sheet row, DXBI events, Transactions rows, outcome, sale as (amount, unit, date))
# Each world is the smallest set of the trial run's real DXBI / DLD rows that keeps the result.
# damac2-15184 (Viridis C 206) is a deliberate change from the trial's property_confirmed_no_sale:
# the trial let DLD rows of Viridis A/B/D count as "Viridis C" through the shared project name.
TRIAL_CASES: list[tuple[Any, ...]] = [
    (
        "damac2-23187",
        {
            "master_project": "DAMAC HILLS 2",
            "property_type": "Residential",
            "size_unknown": "182.94",
            "transaction_price_aed": "300000",
            "transaction_date": "2021-04-14",
        },
        [
            event(
                "DH2-XL2108B",
                "Damac Hills 2",
                300000,
                area="Madinat Hind 4",
                size=1969,
                date="2021-04-14",
            )
        ],
        [],
        "matched_sale_inferred_unit",
        (300000, "DH2-XL2108B", "2021-04-14"),
    ),
    (
        "damac2-18611",
        {
            "master_project": "DAMAC HILLS 2",
            "property_type": "Residential",
            "size_unknown": "174.8",
            "transaction_price_aed": "370000",
            "transaction_date": "2022-03-03",
        },
        [
            event(
                "DH2-XL1282B",
                "Mulberry",
                370000,
                area="Damac Hills 2",
                project="Mulberry",
                size=1882,
                date="2021-11-23",
            )
        ],
        [],
        "matched_sale_inferred_unit",
        (370000, "DH2-XL1282B", "2021-11-23"),
    ),
    (
        "furjan-7698",
        {
            "master_project": "Al Furjan",
            "project_name": "Al Furjan",
            "building_number": "VILLA NO. 1",
            "plot_number": "AFNCTH003",
            "property_type": "Land",
            "size_unknown": "896",
            "transaction_price_aed": "687500",
            "transaction_date": "2023-09-11",
        },
        [event("AFNCTH003", "Al Furjan", 687500, area="Jabal Ali 1", size=9644, date="2023-09-13")],
        [],
        "matched_sale",
        (687500, "AFNCTH003", "2023-09-13"),
    ),
    (
        "ar3-166",
        {
            "master_project": "Arabian Ranches 3",
            "project_name": "Arabian Ranches lll - Ruba",
            "building_name": "357",
            "building_number": "R3 Ruba-V-357",
            "plot_number": "AR3-2A-SD-34",
            "property_type": "Building",
            "size_unknown": "260.51",
            "transaction_price_aed": "2200888",
            "transaction_date": "2024-03-18",
        },
        [
            event(
                "357",
                "Ruba",
                2200888,
                area="Arabian Ranches 3",
                project="Arabian Ranches 3",
                size=2804,
                date="2021-08-23",
            )
        ],
        [],
        "matched_sale",
        (2200888, "357", "2021-08-23"),
    ),
    (
        "ar3-12421",
        {
            "master_project": "Arabian Ranches 3",
            "project_name": "Arabian Ranches lll - Ruba",
            "building_name": "267",
            "building_number": "R3 Ruba-V-267",
            "plot_number": "AR3-2A-SD-20",
            "property_type": "Villa",
            "size_unknown": "250.28",
            "transaction_price_aed": "1752888",
            "transaction_date": "2020-02-03",
        },
        [
            event(
                "267",
                "Ruba",
                1752888,
                area="Arabian Ranches 3",
                project="Arabian Ranches 3",
                size=2694,
                date="2020-02-03",
            )
        ],
        [],
        "matched_sale",
        (1752888, "267", "2020-02-03"),
    ),
    (
        "furjan-24336",
        {
            "master_project": "Al Furjan",
            "project_name": "Prime Townhouses",
            "building_number": "TH 23-1",
            "plot_number": "AFWBTH023",
            "property_type": "Commercial",
            "size_unknown": "896",
            "transaction_price_aed": "1832447.4",
            "transaction_date": "2020-11-03",
        },
        [
            event(
                "AFWBTH023",
                "Prime Townhouses",
                1832447,
                area="Al Furjan",
                project="Prime Townhouses",
                size=9644,
                date="2020-11-03",
            )
        ],
        [],
        "matched_sale",
        (1832447, "AFWBTH023", "2020-11-03"),
    ),
    (
        "damac2-17157",
        {
            "master_project": "DAMAC HILLS 2",
            "building_name": "NAVITAS ( E )@AKOYA OXYGEN",
            "unit_number": "1410",
            "property_type": "Hotel Rooms",
            "size_unknown": "31.01",
            "transaction_price_aed": "460000",
            "transaction_date": "2022-05-20",
        },
        [
            event(
                "1410",
                "Navitas Tower E",
                460000,
                area="Damac Hills 2",
                project="Navitas",
                size=334,
                date="2022-05-20",
            )
        ],
        [],
        "matched_sale",
        (460000, "1410", "2022-05-20"),
    ),
    (
        "citywalk-5311",
        {
            "master_project": "City Walk",
            "project_name": "NO. 4A, NO.4B, NO.5 CITYWALK RESIDENTIAL",
            "building_name": "Citywalk Residential Building 5",
            "unit_number": "102",
            "property_type": "Flat",
            "size_unknown": "107.63",
            "transaction_price_aed": "850000",
            "transaction_date": "2021-06-20",
        },
        [
            event(
                "102",
                "Building 5 (CW)",
                2052000,
                area="City Walk",
                project="City Walk",
                size=1159,
                date="2016-11-09",
            )
        ],
        [
            transaction(
                850000,
                sqm=107.63,
                master="City Walk",
                area="Al Wasl",
                project="NO. 4A, NO.4B, NO.5 CITYWALK RESIDENTIAL",
                building="Citywalk Residential Building 5",
                unit="715",
                procedure="Sell",
                date="2021-06-21",
                status="matched",
            )
        ],
        "matched_sale_review",
        (850000, "715", "2021-06-21"),
    ),
    (
        "furjan-22783",
        {
            "master_project": "Al Furjan",
            "project_name": "Roy Mediterranean Hotel Apartments",
            "building_name": "ROY MEDITERRANEAN",
            "unit_number": "629",
            "building_number": "1",
            "plot_number": "AFC008",
            "property_type": "Hotel Apartment",
            "size_unknown": "36.29",
            "transaction_price_aed": "250000",
            "transaction_date": "2021-03-28",
        },
        [
            event(
                "629",
                "Roy Mediterranean",
                36000,
                family="rental",
                area="Al Furjan",
                project="Roy Mediterranean Hotel Apartments",
                size=391,
                date="2025-06-20",
            ),
            event(
                "408",
                "Starz Tower 1",
                250000,
                area="Al Furjan",
                project="Starz Tower By Danube",
                size=208,
                date="2024-03-06",
            ),
        ],
        [
            transaction(
                250000,
                sqm=36.29,
                master="Al Furjan",
                area="Jabal Ali First",
                project="Roy Mediterranean Hotel Apartments",
                building="ROY MEDITERRANEAN",
                procedure="Sell",
                date="2021-03-29",
                status="dld_only",
            )
        ],
        "matched_registry_sale",
        (250000, "", "2021-03-29"),
    ),
    (
        "furjan-24114",
        {
            "master_project": "Al Furjan",
            "project_name": "Roy Mediterranean Hotel Apartments",
            "building_name": "ROY MEDITERRANEAN",
            "unit_number": "205",
            "building_number": "1",
            "plot_number": "AFC008",
            "property_type": "Hotel Apartment",
            "size_unknown": "35.92",
            "transaction_price_aed": "270000",
            "transaction_date": "2020-11-08",
        },
        [
            event(
                "205",
                "Roy Mediterranean",
                40000,
                family="rental",
                area="Al Furjan",
                project="Roy Mediterranean Hotel Apartments",
                size=387,
                date="2025-10-15",
            ),
            event(
                "437",
                "Roy Mediterranean",
                270000,
                area="Al Furjan",
                project="Roy Mediterranean Hotel Apartments",
                size=384,
                date="2021-01-27",
            ),
        ],
        [
            transaction(
                270000,
                sqm=35.92,
                master="Al Furjan",
                area="Jabal Ali First",
                project="Roy Mediterranean Hotel Apartments",
                building="ROY MEDITERRANEAN",
                procedure="Sell",
                date="2020-11-09",
                status="dld_only",
            )
        ],
        "matched_registry_sale",
        (270000, "", "2020-11-09"),
    ),
    (
        "damac2-15184",
        {
            "master_project": "DAMAC HILLS 2",
            "building_name": "VIRIDIS C",
            "unit_number": "206",
            "property_type": "Flat",
            "size_unknown": "40.15",
            "transaction_price_aed": "340000",
            "transaction_date": "2022-08-25",
        },
        [
            event(
                "206",
                "Viridis C",
                37000,
                family="rental",
                area="Damac Hills 2",
                project="Viridis",
                size=432,
                date="2026-08-26",
            ),
            event(
                "203",
                "Viridis D",
                340000,
                area="Damac Hills 2",
                project="Viridis",
                size=437,
                date="2021-09-23",
            ),
        ],
        [
            transaction(
                340000,
                sqm=40.03,
                master="DAMAC HILLS 2",
                area="Madinat Hind 4",
                project="DAMAC HILLS (2) - VIRIDIS",
                building="VIRIDIS C",
                procedure="Sell - Pre registration",
                date="2019-05-20",
                status="dld_only",
            )
        ],
        "matched_registry_sale",
        (340000, "", "2019-05-20"),
    ),
    (
        "furjan-5261",
        {
            "master_project": "Al Furjan",
            "project_name": "Azizi Berton",
            "building_name": "Azizi Berton",
            "unit_number": "211",
            "building_number": "1",
            "plot_number": "AFC016",
            "property_type": "Unit",
            "size_unknown": "37.27",
            "transaction_price_aed": "386400",
            "transaction_date": "2023-11-22",
        },
        [
            event(
                "211",
                "Azizi Berton",
                49800,
                family="rental",
                area="Al Furjan",
                project="Azizi Berton",
                size=401,
                date="2026-09-11",
            ),
            event(
                "1103",
                "Azizi Shaista Residence",
                386400,
                area="Al Furjan",
                project="Azizi Shaista Residence",
                size=398,
                date="2022-08-16",
            ),
        ],
        [
            transaction(
                386400,
                sqm=36.93,
                master="Al Furjan",
                area="Jabal Ali First",
                project="Azizi Berton",
                building="Azizi Berton",
                procedure="Sell - Pre registration",
                date="2023-08-28",
                status="dld_only",
            )
        ],
        "matched_registry_sale",
        (386400, "", "2023-08-28"),
    ),
    (
        "ar3-6494",
        {
            "master_project": "Arabian Ranches 3",
            "project_name": "Arabian Ranches III - SUN",
            "building_name": "R3 Sun-V-122",
            "building_number": "R3 Sun-V-118",
            "plot_number": "AR3.B.37",
            "property_type": "Building",
            "size_unknown": "128.58",
            "transaction_price_aed": "700000",
            "transaction_date": "2023-01-31",
        },
        [
            event(
                "122",
                "Sun",
                700000,
                area="Arabian Ranches 3",
                project="Arabian Ranches 3",
                size=692,
                date="2023-01-31",
            ),
            event(
                "122",
                "Sun",
                1288000,
                area="Arabian Ranches 3",
                project="Arabian Ranches 3",
                size=1384,
                date="2021-03-04",
            ),
        ],
        [],
        "matched_sale_review",
        (700000, "122", "2023-01-31"),
    ),
    (
        "living-5111",
        {
            "master_project": "Emirates Living",
            "project_name": "Springs - 3",
            "building_name": "124",
            "building_number": "S 3 Community A-TH-126",
            "property_type": "Villa",
            "size_unknown": "245.69",
            "transaction_price_aed": "79668",
            "transaction_date": "2022-10-27",
        },
        [],
        [],
        "no_evidence",
        None,
    ),
    (
        "damac2-11532",
        {
            "master_project": "DAMAC HILLS 2",
            "project_name": "DAMAC HILLS (2) - ALBIZIA ",
            "building_number": "XW814B",
            "plot_number": "DH2-XW814B",
            "property_type": "Land",
            "size_unknown": "247.54",
            "transaction_price_aed": "1187000",
            "transaction_date": "2023-03-14",
        },
        [
            event(
                "XW814B",
                "Albizia",
                1150000,
                area="Damac Hills 2",
                project="Albizia",
                size=2664,
                date="2023-06-26",
            )
        ],
        [],
        "property_confirmed_no_sale",
        None,
    ),
    (
        "living-8256",
        {
            "master_project": "Emirates Living",
            "project_name": "Emirates Hills",
            "property_type": "Commercial",
            "size_unknown": "1206.81",
            "transaction_price_aed": "15643",
            "transaction_date": "2021-08-04",
        },
        [],
        [],
        "no_evidence",
        None,
    ),
    (
        "damac2-16438",
        {
            "master_project": "DAMAC HILLS 2",
            "property_type": "Residential",
            "size_unknown": "174.8",
            "transaction_price_aed": "250000",
            "transaction_date": "2022-07-05",
        },
        [],
        [],
        "no_evidence",
        None,
    ),
    (
        "damac2-22588",
        {
            "master_project": "DAMAC HILLS 2",
            "property_type": "Residential",
            "size_unknown": "112.24",
            "transaction_price_aed": "450000",
            "transaction_date": "2021-06-27",
        },
        [
            event(
                "XW1002B",
                "Albizia",
                450000,
                area="Damac Hills 2",
                project="Albizia",
                size=1208,
                date="2023-08-09",
            ),
            event(
                "XV776B",
                "Basswood",
                450000,
                area="Damac Hills 2",
                project="Basswood",
                size=1208,
                date="2023-08-16",
            ),
        ],
        [
            transaction(
                450000,
                sqm=112.23,
                master="DAMAC HILLS 2",
                area="Damac Hills 2",
                project="DAMAC HILLS (2) - ALBIZIA",
                building="Albizia",
                unit="XW1002B",
                procedure="",
                date="2023-08-09",
                status="dxbi_preferred",
            ),
            transaction(
                450000,
                sqm=112.23,
                master="DAMAC HILLS 2",
                area="Damac Hills 2",
                project="DAMAC HILLS (2) - BASSWOOD",
                building="Basswood",
                unit="XV776B",
                procedure="",
                date="2023-08-16",
                status="dxbi_preferred",
            ),
        ],
        "no_evidence",
        None,
    ),
    (
        "damac2-20886",
        {
            "master_project": "DAMAC HILLS 2",
            "property_type": "Residential",
            "size_unknown": "174.93",
            "transaction_price_aed": "684000",
            "transaction_date": "2021-10-20",
        },
        [
            event(
                "DH2-XL2010B",
                "Damac Hills 2",
                684000,
                area="Madinat Hind 4",
                size=1883,
                date="2016-01-27",
            )
        ],
        [],
        "matched_sale_inferred_unit",
        (684000, "DH2-XL2010B", "2016-01-27"),
    ),
    (
        "furjan-5991",
        {
            "master_project": "Al Furjan",
            "project_name": "STARZ TOWER by DANUBE",
            "building_name": "Starz Tower 2",
            "unit_number": "1111",
            "building_number": "1",
            "plot_number": "AFMU009_10A",
            "property_type": "Unit",
            "size_unknown": "37.17",
            "transaction_price_aed": "100000",
            "transaction_date": "2023-10-31",
        },
        [
            event(
                "1111",
                "Starz Tower 2",
                488819,
                area="Al Furjan",
                project="Starz Tower By Danube",
                size=400,
                date="2016-05-10",
            ),
            event(
                "1111",
                "Glamz Residence Tower 2",
                72000,
                family="rental",
                area="Al Furjan",
                project="Glamz Residence",
                size=769,
                date="2025-09-22",
            ),
        ],
        [],
        # v2c: "Glamz Residence Tower 2" shared only the marker "Tower 2" with Starz, which made
        # unit 1111 ambiguous (no_evidence). With the stems compared, Starz Tower 2 unit 1111 is
        # the one property and it has no sale at 100,000.
        "property_confirmed_no_sale",
        None,
    ),
    (
        "damac2-17423",
        {
            "master_project": "DAMAC HILLS 2",
            "building_name": "VIRIDIS C",
            "unit_number": "304",
            "property_type": "Flat",
            "size_unknown": "40.04",
            "transaction_price_aed": "324950",
            "transaction_date": "2022-05-05",
        },
        [
            event(
                "304",
                "Viridis C",
                400000,
                area="Damac Hills 2",
                project="Viridis",
                size=431,
                date="2024-06-27",
            )
        ],
        [
            transaction(
                324950,
                sqm=40.01,
                master="DAMAC HILLS 2",
                area="Madinat Hind 4",
                project="DAMAC HILLS (2) - VIRIDIS",
                building="VIRIDIS C",
                procedure="Sell - Pre registration",
                date="2021-10-04",
                status="dld_only",
            )
        ],
        "matched_registry_sale",
        (324950, "", "2021-10-04"),
    ),
    (
        "damac2-17545",
        {
            "master_project": "DAMAC HILLS 2",
            "building_name": "VIRIDIS D",
            "unit_number": "1006",
            "property_type": "Flat",
            "size_unknown": "39.86",
            "transaction_price_aed": "340000",
            "transaction_date": "2022-04-26",
        },
        [
            event(
                "203",
                "Viridis D",
                340000,
                area="Damac Hills 2",
                project="Viridis",
                size=437,
                date="2021-09-23",
            )
        ],
        [
            transaction(
                340000,
                sqm=40.04,
                master="DAMAC HILLS 2",
                area="Madinat Hind 4",
                project="DAMAC HILLS (2) - VIRIDIS",
                building="VIRIDIS D",
                procedure="Sell - Pre registration",
                date="2019-05-20",
                status="dld_only",
            ),
            transaction(
                340000,
                sqm=40.63,
                master="DAMAC HILLS 2",
                area="Madinat Hind 4",
                project="DAMAC HILLS (2) - VIRIDIS",
                building="VIRIDIS D",
                procedure="Sell - Pre registration",
                date="2020-02-17",
                status="dld_only",
            ),
        ],
        "no_evidence",
        None,
    ),
    (
        "furjan-16796",
        {
            "master_project": "Al Furjan",
            "project_name": "Azizi Shaista Residence",
            "building_name": "Azizi Shaista Residence",
            "unit_number": "222",
            "building_number": "1",
            "plot_number": "AFMU015B_16A",
            "property_type": "Flat",
            "size_unknown": "35.96",
            "transaction_price_aed": "380100",
            "transaction_date": "2022-09-28",
        },
        [
            event(
                "823",
                "Azizi Farishta",
                380100,
                area="Al Furjan",
                project="Azizi Farishta Residence",
                size=380,
                date="2022-03-16",
            )
        ],
        [
            transaction(
                380100,
                sqm=35.96,
                master="Al Furjan",
                area="Jabal Ali First",
                project="Azizi Shaista Residence",
                building="Azizi Shaista Residence",
                procedure="Delayed Sell",
                date="2022-04-04",
                status="dld_only",
            )
        ],
        "matched_registry_sale",
        (380100, "", "2022-04-04"),
    ),
    (
        "damac2-16370",
        {
            "master_project": "DAMAC HILLS 2",
            "building_name": "VIRIDIS A",
            "unit_number": "711",
            "property_type": "Hotel Apartment",
            "size_unknown": "33.02",
            "transaction_price_aed": "381000",
            "transaction_date": "2022-07-12",
        },
        [
            event(
                "711",
                "Viridis A",
                333000,
                area="Damac Hills 2",
                project="Viridis",
                size=355,
                date="2024-04-22",
            )
        ],
        [],
        "property_confirmed_no_sale",
        None,
    ),
    (
        "ar3-9494",
        {
            "master_project": "Arabian Ranches 3",
            "project_name": "Arabian Ranches III - SUN",
            "building_name": "161",
            "building_number": "R3 Sun-V-157",
            "plot_number": "AR3.B.33",
            "property_type": "Villa",
            "size_unknown": "128.57",
            "transaction_price_aed": "1178931",
            "transaction_date": "2021-12-05",
        },
        [
            event(
                "157",
                "Sun",
                1745888,
                area="Arabian Ranches 3",
                project="Arabian Ranches 3",
                size=2407,
                date="2019-10-03",
            )
        ],
        [
            transaction(
                1178931,
                sqm=128.57,
                master="Arabian Ranches 3",
                area="Wadi Al Safa 5",
                project="Arabian Ranches III - SUN",
                procedure="Sell - Pre registration",
                date="2021-12-06",
                status="dld_only",
            )
        ],
        "matched_sale_review",
        (1178931, "", "2021-12-06"),
    ),
    (
        "damac2-21561",
        {
            "master_project": "DAMAC HILLS 2",
            "property_type": "Residential",
            "size_unknown": "173.06",
            "transaction_price_aed": "325990",
            "transaction_date": "2021-09-22",
        },
        [],
        [
            transaction(
                325990,
                sqm=173.06,
                master="DAMAC HILLS 2",
                area="Al Yufrah 2",
                project="DAMAC HILLS (2) - ASTER",
                procedure="Grant on Delayed Sell",
                date="2018-04-18",
                status="dld_only",
            )
        ],
        "matched_registry_sale_no_unit",
        (325990, "", "2018-04-18"),
    ),
    (
        "living-9334",
        {
            "master_project": "Emirates Living",
            "project_name": "Emirates Hills",
            "property_type": "Commercial",
            "size_unknown": "1526.21",
            "transaction_price_aed": "7185110",
            "transaction_date": "2021-01-11",
        },
        [],
        [
            transaction(
                7185110,
                sqm=1526.21,
                master="Emirates Hills",
                area="Al Thanayah Fourth",
                project="Emirates Hills",
                procedure="Sell",
                date="2021-01-11",
                status="dld_only",
            )
        ],
        "matched_registry_sale_no_unit",
        (7185110, "", "2021-01-11"),
    ),
    (
        "furjan-10334",
        {
            "master_project": "Al Furjan",
            "project_name": "Azizi Farishta Residence ",
            "building_name": "AZIZI FARISHTA",
            "unit_number": "1213",
            "building_number": "1",
            "plot_number": "AFMU035B_36A",
            "property_type": "Unit",
            "size_unknown": "191.01",
            "transaction_price_aed": "147285",
            "transaction_date": "2023-07-11",
        },
        [
            event(
                "1213",
                "Azizi Farishta",
                120000,
                family="rental",
                area="Al Furjan",
                project="Azizi Farishta Residence",
                size=2056,
                date="2025-08-01",
            )
        ],
        [],
        "property_confirmed_no_sale",
        None,
    ),
    (
        "damac2-17594",
        {
            "master_project": "DAMAC HILLS 2",
            "building_name": "VIRIDIS D",
            "unit_number": "707",
            "property_type": "Flat",
            "size_unknown": "37.99",
            "transaction_price_aed": "422256",
            "transaction_date": "2022-04-25",
        },
        [
            event(
                "707",
                "Viridis D",
                40000,
                family="rental",
                area="Damac Hills 2",
                project="Viridis",
                size=409,
                date="2026-03-05",
            )
        ],
        [
            transaction(
                422256,
                sqm=37.54,
                master="DAMAC HILLS 2",
                area="Madinat Hind 4",
                project="DAMAC HILLS (2) - VIRIDIS",
                building="VIRIDIS D",
                procedure="Sell - Pre registration",
                date="2016-02-01",
                status="dld_only",
            )
        ],
        "matched_registry_sale",
        (422256, "", "2016-02-01"),
    ),
]


def _sale_id(sale: Any) -> tuple[float, str, str] | None:
    if sale is None:
        return None
    if "actual_worth" in sale:
        return (sale["actual_worth"], sale["unit_number"], sale["instance_date"])
    return (sale["amount"], sale["unit_number"], sale["event_date"])


@pytest.mark.parametrize(
    ("source", "events", "registry", "outcome", "sale"),
    [case[1:] for case in TRIAL_CASES],
    ids=[case[0] for case in TRIAL_CASES],
)
def test_trial_rows_keep_their_outcome(
    source: dict[str, Any],
    events: list[dict[str, Any]],
    registry: list[dict[str, Any]],
    outcome: str,
    sale: tuple[float, str, str] | None,
) -> None:
    result = match(source, events, registry)
    assert (result.outcome, _sale_id(result.sale)) == (outcome, sale)


# --------------------------------------------------------------------------- shadow-run fixes
# Values below are the real property values of the shadow-run rows named in each test.

R3_EVENTS = dict(area="Arabian Ranches 3", project="Arabian Ranches 3", kind="Villa")


def test_sun_villa_code_on_the_dxbi_side_matches_the_sheet_key() -> None:
    # AR3 Sheet1 row 5633: sheet "R3 Sun-V-259" (key 259, namespace sun); DXBI unit "R3 Sun-V-259".
    source = {
        "master_project": "Arabian Ranches 3",
        "project_name": "Arabian Ranches III - SUN",
        "building_name": "R3 Sun-V-259",
        "building_number": "R3 Sun-V-259",
        "plot_number": "AR3.B.09",
        "property_type": "Building",
        "size_unknown": "224.78",
        "transaction_price_aed": "1761888",
        "transaction_date": "2023-03-02",
    }
    world = [
        event(
            "R3 Sun-V-259",
            "",
            210000,
            family="rental",
            size=2420,
            date="2025-03-19",
            **{**R3_EVENTS, "project": "Sun"},
        ),
        event("R3 Sun-V-259", "Sun", 1761888, size=2418, date="2022-03-08", **R3_EVENTS),
        event("R3 Ruba-V-259", "Ruba", 1761888, size=2418, date="2021-03-08", **R3_EVENTS),
    ]
    result = match(source, world)
    assert result.outcome == "matched_sale"
    assert result.sale is not None and result.sale["event_date"] == "2022-03-08"
    assert result.property_key == ("sun", "259")


def test_bare_villa_number_finds_the_dxbi_villa_code_before_any_dld_sale() -> None:
    # AR3 Sheet1 row 11756: sheet "397"; DXBI "R3 Sun-V-397" sold in 2022. DLD has the same
    # price on two other villas and one sale with no unit.
    source = {
        "master_project": "Arabian Ranches 3",
        "project_name": "Arabian Ranches III - SUN",
        "building_name": "397",
        "building_number": "397",
        "plot_number": "AR3.B.04",
        "property_type": "Villa",
        "size_unknown": "223.62",
        "transaction_price_aed": "1623888",
        "transaction_date": "2020-11-15",
    }
    sun = dict(
        master="Arabian Ranches 3", area="Wadi Al Safa 5", project="Arabian Ranches III - SUN"
    )
    world = [event("R3 Sun-V-397", "Sun", 1623888, size=2399, date="2022-01-24", **R3_EVENTS)]
    registry = [
        transaction(1623888, sqm=223.62, date="2020-11-16", **sun),
        transaction(1623888, sqm=222.91, unit="405", building="Sun", date="2022-01-24", **sun),
    ]
    result = match(source, world, registry)
    assert result.outcome == "matched_sale"
    assert result.sale is world[0]


def test_spring_villa_code_beats_a_2011_dld_sale() -> None:
    # AR3 Sheet1 row 1434: "R3 Spring-V-55", 2,100,000, 235.1 sqm; DXBI sale 2022-04-15.
    source = {
        "master_project": "Arabian Ranches 3",
        "project_name": "Arabian Ranches III - Spring",
        "building_name": "R3 Spring-V-55",
        "building_number": "R3 Spring-V-55",
        "plot_number": "AR3.D.25",
        "property_type": "Building",
        "size_unknown": "235.1",
        "transaction_price_aed": "2100000",
        "transaction_date": "2023-12-01",
    }
    world = [event("R3 Spring-V-55", "Spring", 2100000, size=2531, date="2022-04-15", **R3_EVENTS)]
    old_dld = transaction(
        2100000, sqm=232.36, master="Arabian Ranches 3", area="Wadi Al Safa 6", date="2011-12-05"
    )
    result = match(source, world, [old_dld])
    assert result.outcome == "matched_sale"
    assert result.sale is world[0]


def test_villa_code_namespace_still_separates_communities() -> None:
    source = {
        "master_project": "Arabian Ranches 3",
        "project_name": "Arabian Ranches III - Ruba",
        "building_name": "R3 Ruba-V-259",
        "size_unknown": "224.78",
        "transaction_price_aed": "1761888",
    }
    world = [event("R3 Sun-V-259", "Sun", 1761888, size=2418, **R3_EVENTS)]
    assert match(source, world).outcome == "no_evidence"


def test_letter_tower_sheet_name_with_the_community_inside_matches_dxbi() -> None:
    # City Walk New / Until August row 752: "Verve City Walk Tower B" unit 803, 77.48 sqm.
    source = {
        "area_name": "Al Wasl",
        "master_project": "City Walk",
        "project_name": "Verve",
        "building_name": "Verve City Walk Tower B",
        "unit_number": "803",
        "building_number": "Verve Tower B",
        "property_number": "803",
        "property_type": "Apartments",
        "size_unknown": "77.48",
        "transaction_price_aed": "2559000",
        "transaction_date": "2024-08-22",
    }
    walk = dict(area="City Walk", project="City Walk")
    sale = event("803", "Verve Tower B", 2559000, size=834, date="2024-08-22", **walk)
    other_tower = event("803", "Verve Tower A", 2559000, size=834, date="2023-08-22", **walk)
    result = match(source, [other_tower, sale])
    assert result.outcome == "matched_sale"
    assert result.sale is sale


MEADOWS = dict(area="Emirates Living", project="Meadows", kind="Villa")


@pytest.mark.parametrize(
    ("code", "project", "plot_sqm", "price", "dxbi_sqft", "outcome"),
    [
        # A plot area 2.0x the built-up area is plausible for a Land row: green, with a warning.
        ("M 5 Community B-V-145", "Meadows 5", "666.39", "908755", 3586, "matched_sale"),  # 8077
        # 5.0x and 3.6x are not: the row goes to review.
        ("M PA2C-V-36", "Meadows 1", "539.95", "1100000", 1163, "matched_sale_review"),  # 2489
        ("M 5 Community A-V-44", "Meadows 5", "573.86", "5980000", 1730, "matched_sale_review"),
    ],
)
def test_plot_area_against_built_up_area_is_green_only_when_the_ratio_is_plausible(
    code: str, project: str, plot_sqm: str, price: str, dxbi_sqft: int, outcome: str
) -> None:
    source = {
        "master_project": "Emirates Living",
        "project_name": project,
        "building_number": code,
        "property_type": "Land",
        "size_unknown": plot_sqm,
        "transaction_price_aed": price,
        "transaction_date": "2023-08-02",
    }
    sale = event(code, project, float(price), size=dxbi_sqft, date="2023-08-03", **MEADOWS)
    result = match(source, [sale])
    assert result.outcome == outcome
    assert result.sale is sale
    assert "size_basis_differs" in result.warnings


def test_size_stays_a_hard_gate_without_an_identifier() -> None:
    source = {
        "master_project": "Emirates Living",
        "project_name": "Meadows 1",
        "size_unknown": "539.95",
        "transaction_price_aed": "1100000",
    }
    sale = event("M PA2C-V-36", "Meadows 1", 1100000, size=1163, **MEADOWS)
    assert match(source, [sale]).outcome == "no_evidence"


def test_size_stays_a_hard_gate_for_registry_matches() -> None:
    source = {
        "master_project": "Emirates Living",
        "project_name": "Meadows 1",
        "building_number": "M PA2C-V-36",
        "size_unknown": "539.95",
        "transaction_price_aed": "1100000",
    }
    elsewhere = transaction(
        1100000, sqm=108.0, master="Emirates Living", project="Meadows 1", status="dld_only"
    )
    assert match(source, [], [elsewhere]).outcome == "no_evidence"


def test_unknown_package_label_does_not_veto_a_unit_and_price_match() -> None:
    # Furjan OLD row 21498: DLD's "ALFURJAN PACKAGE 4"; DXBI has the villa in Quortaj.
    source = {
        "master_project": "Al Furjan",
        "project_name": "ALFURJAN PACKAGE 4",
        "building_number": "AFSGQMOTHB1085",
        "plot_number": "AFSGQMOTHB1085",
        "property_type": "Commercial",
        "size_unknown": "224",
        "transaction_price_aed": "2400000",
        "transaction_date": "2021-11-24",
    }
    furjan = dict(area="Al Furjan", kind="Villa", size=2411)
    sale = event(
        "AFSGQMOTHB1085", "Quortaj", 2400000, project="Quortaj", date="2021-11-24", **furjan
    )
    other = event("AFEMQMOTHB1849", "Quortaj 2", 2400000, project="Quortaj 2", **furjan)
    result = match(source, [sale, other])
    assert result.outcome == "matched_sale"
    assert result.sale is sale
    # a same-price sale of another unit is still never a match
    assert match(source, [other]).outcome != "matched_sale"


def test_building_designator_the_hierarchy_lacks_still_picks_the_building() -> None:
    # City Walk New / Old row 2445: unit 401 exists in 60 City Walk buildings; the sheet says 11B.
    source = {
        "master_project": "City Walk",
        "building_name": "Citywalk Residential Building 11B",
        "unit_number": "401",
        "property_type": "Flat",
        "size_unknown": "216.88",
        "transaction_price_aed": "4100000",
        "transaction_date": "2022-12-27",
    }
    walk = dict(area="City Walk", size=2335)
    sale = event("401", "Building 11b (CW)", 4100000, **walk)
    same_price_next_door = event("401", "Building 12b (CW)", 4100000, **walk)
    result = match(source, [same_price_next_door, sale])
    assert result.outcome == "matched_sale"
    assert result.sale is sale


# --------------------------------------------------------------------------- v2c fixes
# Real property values of the v2b shadow-run rows named in each test.

FURJAN_VILLA_1 = {
    "master_project": "Al Furjan",
    "project_name": "Al Furjan",
    "building_number": "VILLA NUMBER 1",
    "plot_number": "AFWETH017",
    "property_type": "Building",
    "size_unknown": "190.83",
    "transaction_price_aed": "500000",
    "transaction_date": "2023-05-08",
}


def test_generic_villa_number_never_identifies_a_property_across_a_community() -> None:
    # Furjan OLD 12339: BuildingNo "VILLA NUMBER 1" matched AFWETH017 to a 514 sqft sale of
    # whichever "VILLA NUMBER 1" Al Furjan holds. Every cluster has one.
    generic = event(
        "VILLA NUMBER 1", "Al Furjan", 500000, area="Jabal Ali 1", size=514, kind="Villa"
    )
    result = match(FURJAN_VILLA_1, [generic])
    assert result.outcome == "no_evidence"
    assert result.sale is None


def test_a_bare_ordinal_never_identifies_a_property_across_a_community() -> None:
    # Furjan OLD 4781: BuildingNo "1" next to AFWBTH005 matched a 3,000,000 sale of unit "1".
    source = {
        "master_project": "Al Furjan",
        "project_name": "Al Furjan",
        "building_number": "1",
        "plot_number": "AFWBTH005",
        "property_type": "Building",
        "size_unknown": "225.4",
        "transaction_price_aed": "3000000",
        "transaction_date": "2023-09-18",
    }
    generic = event("1", "Al Furjan", 3000000, area="Jabal Ali 1", size=2441, kind="Villa")
    result = match(source, [generic])
    assert result.outcome == "no_evidence" and result.sale is None


def test_the_full_plot_code_still_matches_next_to_an_ordinal() -> None:
    plot = event("AFWETH017", "Al Furjan", 500000, area="Jabal Ali 1", size=2054, kind="Villa")
    generic = event("VILLA NUMBER 1", "Al Furjan", 500000, area="Jabal Ali 1", size=514)
    result = match(FURJAN_VILLA_1, [generic, plot])
    assert result.outcome == "matched_sale" and result.sale is plot


def test_an_ordinal_unit_inside_a_named_building_is_still_an_identifier() -> None:
    source = {
        "master_project": "Arabian Ranches 3",
        "building_name": "Sun",
        "unit_number": "12",
        "size_unknown": "224.78",
        "transaction_price_aed": "1761888",
    }
    sale = event("12", "Sun", 1761888, size=2418, **R3_EVENTS)
    assert match(source, [sale]).outcome == "matched_sale"


def test_an_ordinal_villa_inside_a_named_project_is_still_an_identifier() -> None:
    # AR3 Sheet1 135: villa 87 of the June project (DXBI files it under "June 1").
    source = {
        "master_project": "Arabian Ranches 3",
        "project_name": "Arabian Ranches lll - June",
        "building_number": "87",
        "plot_number": "AR3.3A.46",
        "size_unknown": "420",
        "transaction_price_aed": "3949888",
    }
    sale = event("87", "June 1", 3949888, size=4521, **R3_EVENTS)
    result = match(source, [sale])
    assert result.outcome == "matched_sale" and result.sale is sale


def test_apartment_numbers_stay_valid_across_a_community() -> None:
    source = {
        "master_project": "DAMAC HILLS 2",
        "unit_number": "101",
        "size_unknown": "40",
        "transaction_price_aed": "324950",
    }
    sale = event("101", "Viridis C", 324950, size=431, project="Viridis")
    assert match(source, [sale]).outcome == "matched_sale"


def test_sales_of_a_generic_unit_label_are_not_one_property_for_inference() -> None:
    # Two different villas both labelled "1" in Al Furjan are two properties, not a repeat price.
    source = {
        "master_project": "Al Furjan",
        "project_name": "Al Furjan",
        "size_unknown": "225.4",
        "transaction_price_aed": "3000000",
    }
    sales = [
        event("1", "Al Furjan", 3000000, area="Jabal Ali 1", size=2441, date="2023-09-18"),
        event("1", "Al Furjan", 3000000, area="Jabal Ali 1", size=2441, date="2021-02-03"),
    ]
    result = match(source, sales)
    assert result.outcome == "no_evidence"
    assert "ambiguous_price_size" in result.reasons


def test_a_dld_sale_with_a_generic_unit_label_is_not_an_eliminated_unit() -> None:
    # "Villa 1" says nothing about which villa sold, so it cannot rule the sale out for AFWETH017
    # (nor in): both fitting DLD sales stay candidates and the row stays unmatched.
    sheet = {**FURJAN_VILLA_1, "building_number": ""}
    base = dict(master="Al Furjan", area="Jabal Ali First", project="Al Furjan")
    rows = [
        transaction(500000, sqm=190.8, unit="VILLA NO. 1", **base),
        transaction(500000, sqm=190.9, **base),
    ]
    result = match(sheet, [], rows)
    assert result.outcome == "no_evidence"
    assert "ambiguous_registry_sale" in result.reasons


SIZE_BASIS = {
    "master_project": "Arabian Ranches 3",
    "building_name": "Joy",
    "unit_number": "918",
    "property_type": "Building",
    "size_unknown": "245.62",  # 2644 sqft against 2572 sqft: 2.8% apart
    "transaction_price_aed": "2391888",
}


def test_size_basis_differs_goes_to_review_not_green() -> None:
    sale = event("918", "Joy", 2391888, size=2572, **R3_EVENTS)
    result = match({**SIZE_BASIS}, [sale])
    assert result.outcome == "matched_sale_review"
    assert result.sale is sale
    assert "size_basis_differs" in result.warnings


def test_a_land_row_stays_green_when_the_plot_ratio_is_plausible() -> None:
    sale = event("918", "Joy", 2391888, size=1300, **R3_EVENTS)  # 2644 / 1300 = 2.03
    result = match({**SIZE_BASIS, "property_type": "Land"}, [sale])
    assert result.outcome == "matched_sale"
    assert "size_basis_differs" in result.warnings


def test_a_land_size_of_unknown_unit_is_read_as_square_metres_for_the_ratio() -> None:
    # 700 read as square feet would be 1.2x of 600 sqft, but a 700 sqm plot is 12.6x: review.
    sale = event("918", "Joy", 2391888, size=600, **R3_EVENTS)
    result = match({**SIZE_BASIS, "property_type": "Land", "size_unknown": "700"}, [sale])
    assert result.outcome == "matched_sale_review"


@pytest.mark.parametrize("dxbi_sqft", [900, 5000])  # 2.9x and 0.53x
def test_a_land_row_beyond_the_ratio_limits_goes_to_review(dxbi_sqft: int) -> None:
    sale = event("918", "Joy", 2391888, size=dxbi_sqft, **R3_EVENTS)
    result = match({**SIZE_BASIS, "property_type": "Land"}, [sale])
    assert result.outcome == "matched_sale_review"


PRIMROSE = {
    "master_project": "DAMAC HILLS 2",
    "project_name": "DAMAC HILLS (2) - PRIMROSE",
    "building_number": "C237B",
    "plot_number": "DH2-C237B",
    "property_type": "Land",
    "size_unknown": "174.8",
    "transaction_price_aed": "1808800",
    "transaction_date": "2023-03-27",
}


def _primrose_rows(unit_sqm: float = 174.8, others: int = 2, **overrides: Any) -> list[Any]:
    base = dict(
        master="DAMAC HILLS 2",
        area="Al Yufrah 2",
        project="DAMAC HILLS (2) - PRIMROSE",
        procedure="Delayed Sell",
    )
    candidate = transaction(1808800, sqm=174.57, **{**base, **overrides})
    elsewhere = [
        transaction(1808800, sqm=unit_sqm, unit=f"DH2-D{i}B", building="Aster", **base)
        for i in range(others)
    ]
    return [candidate, *elsewhere]


def test_elimination_in_a_project_without_a_known_building_goes_to_review() -> None:
    # Damac Sheet1 11050: the sheet names a project, not a building, and 25 units were eliminated.
    rows = _primrose_rows(others=25)
    result = match(PRIMROSE, [], rows)
    assert result.outcome == "matched_sale_review"
    assert result.sale is rows[0]
    assert any("elimination" in reason for reason in result.reasons)


def test_elimination_of_more_than_three_units_goes_to_review() -> None:
    berton = dict(master="Al Furjan", area="Jabal Ali First", project="Azizi Berton")
    rows = [transaction(386400, sqm=36.93, building="Azizi Berton", **berton)] + [
        transaction(386400, sqm=36.98, unit=str(300 + i), building="Azizi Berton", **berton)
        for i in range(4)
    ]
    result = match(BERTON, BERTON_WORLD, rows)
    assert result.outcome == "matched_sale_review" and result.sale is rows[0]


def test_elimination_of_exactly_three_units_in_a_known_building_stays_green() -> None:
    berton = dict(master="Al Furjan", area="Jabal Ali First", project="Azizi Berton")
    rows = [transaction(386400, sqm=36.93, building="Azizi Berton", **berton)] + [
        transaction(386400, sqm=36.98, unit=str(300 + i), building="Azizi Berton", **berton)
        for i in range(3)
    ]
    result = match(BERTON, BERTON_WORLD, rows)
    assert result.outcome == "matched_registry_sale" and result.sale is rows[0]


def test_elimination_onto_a_plain_grant_goes_to_review() -> None:
    berton = dict(master="Al Furjan", area="Jabal Ali First", project="Azizi Berton")
    rows = [
        transaction(386400, sqm=36.93, building="Azizi Berton", procedure="Grant", **berton),
        transaction(386400, sqm=36.98, unit="209", building="Azizi Berton", **berton),
    ]
    result = match(BERTON, BERTON_WORLD, rows)
    assert result.outcome == "matched_sale_review" and result.sale is rows[0]


def test_a_grant_without_any_elimination_is_still_a_match() -> None:
    # Greens "Grant" rows: nothing was eliminated, so there is nothing to doubt.
    source = {
        "master_project": "DAMAC HILLS 2",
        "size_unknown": "173.06",
        "transaction_price_aed": "325990",
    }
    aster = transaction(
        325990, sqm=173.06, master="DAMAC HILLS 2", project="ASTER", procedure="Grant"
    )
    assert match(source, [], [aster]).outcome == "matched_registry_sale_no_unit"


def test_damac_registry_sale_in_reem_mira_oasis_is_not_a_damac_hills_2_match() -> None:
    # Damac Sheet1 18902: DLD files this Mira Oasis villa under master DAMAC HILLS 2.
    source = {
        "master_project": "DAMAC HILLS 2",
        "property_type": "Residential",
        "size_unknown": "407.44",
        "transaction_price_aed": "2100000",
    }
    row = transaction(
        2100000,
        sqm=407.1,
        master="DAMAC HILLS 2",
        area="Al Yelayiss 1",
        project="REEM - MIRA OASIS COMMUNITY PHASE 3",
        building="Reem - Mira Oasis Community Phase 3",
    )
    places = PlaceIndex(
        [
            *({"community_key": key, "name_key": key} for key in COMMUNITIES),
            {"community_key": "alyelayiss1", "name_key": "reemmiraoasiscommunityphase3"},
        ],
        PROJECT_ALIASES,
        MASTER_ALIASES,
    )
    assert match_row(source, SalesIndex([], places, [row])).outcome == "no_evidence"


def test_springs_sub_community_numbers_must_agree_with_the_registry() -> None:
    # Emirates Living 13163: sheet "Springs - 1"; DLD's master for this sale is "Springs - 2".
    source = {
        "master_project": "Emirates Living",
        "project_name": "Springs - 1",
        "building_number": "S 1 Community B-TH-763",
        "property_type": "Villa",
        "size_unknown": "186.24",
        "transaction_price_aed": "1350000",
    }
    other = transaction(
        1350000,
        sqm=190.17,
        master="Springs - 2",
        area="Al Thanayah Fourth",
        project="Emirates Living - Springs 12",
        procedure="Grant",
    )
    assert match(source, [], [other]).outcome == "no_evidence"
    same = transaction(
        1350000,
        sqm=190.17,
        master="Springs - 1",
        area="Al Thanayah Fourth",
        project="Emirates Living - Springs 12",
        procedure="Grant",
    )
    assert match(source, [], [same]).outcome == "matched_registry_sale"


def test_two_unit_numbers_in_the_sheet_row_go_to_review() -> None:
    # JVT Until August 309: UnitNumber 112 but property_number 113; DXBI has only 113.
    source = {
        "area_name": "Jumeirah Village Triangle (JVT)",
        "master_project": "JVT District 3",
        "project_name": "Bali Residences",
        "building_name": "Bali Residences",
        "unit_number": "112",
        "building_number": "Bali Residences",
        "property_number": "113",
        "property_type": "Apartments",
        "size_unknown": "78.1",
        "transaction_price_aed": "1200000",
        "transaction_date": "2024-05-27",
    }
    sale = event(
        "113",
        "Bali Residences",
        1200000,
        area="Jumeirah Village Triangle",
        project="Bali Residences",
        size=841,
    )
    result = match(source, [sale])
    assert result.outcome == "matched_sale_review"
    assert result.sale is sale
    assert any("sheet_names_two_units" in warning for warning in result.warnings)


def test_a_villa_code_and_a_higher_building_name_number_follow_the_name_column() -> None:
    # AR3 Sheet1 12282: BuildingNo "R3 Joy-V-788", name column "789". DXBI's sale is on 789 at the
    # exact price and size, which is how DXBI numbers AR3 (see test above), so it stays green.
    source = {
        "master_project": "Arabian Ranches 3",
        "project_name": "Arabian Ranches III - JOY",
        "building_name": "789",
        "building_number": "R3 Joy-V-788",
        "plot_number": "AR3.A.24",
        "size_unknown": "235.9",
        "transaction_price_aed": "2450000",
    }
    sale = event("R3 Joy-V-789", "Joy", 2450000, size=2539, **R3_EVENTS)
    result = match(source, [sale])
    assert result.outcome == "matched_sale"
    assert any(w.startswith("buildingno_renumbered") for w in result.warnings)


def test_unit_and_property_number_that_differ_without_digits_still_go_to_review() -> None:
    # JVT Until August 960: UnitNumber "RETAIL 1" but property_number "RETAIL".
    source = {
        "area_name": "Jumeirah Village Triangle (JVT)",
        "master_project": "JVT District 3",
        "project_name": "Bali Residences",
        "building_name": "Bali Residences",
        "unit_number": "RETAIL 1",
        "property_number": "RETAIL",
        "size_unknown": "50",
        "transaction_price_aed": "396017",
    }
    sale = event(
        "RETAIL",
        "Bali Residences",
        396017,
        area="Jumeirah Village Triangle",
        project="Bali Residences",
        size=538,
    )
    result = match(source, [sale])
    assert result.outcome == "matched_sale_review" and result.sale is sale


def test_a_building_name_in_the_building_number_column_is_not_a_second_unit() -> None:
    # City Walk New / Until August 650: BuildingNo repeats the building's name ("Rove City Walk").
    source = {
        "master_project": "City Walk",
        "project_name": "Rove City Walk",
        "building_name": "Rove City Walk",
        "building_number": "Rove City Walk",
        "property_number": "414",
        "size_unknown": "30.8",
        "transaction_price_aed": "1150000",
    }
    sale = event("414", "Rove City Walk", 1150000, area="City Walk", size=331)
    assert match(source, [sale]).outcome == "matched_sale"


def test_the_same_unit_written_twice_is_not_two_units() -> None:
    source = {**NAVITAS, "property_number": "1410"}
    assert match(source, NAVITAS_WORLD).outcome == "matched_sale"


def test_a_shared_tower_number_with_another_name_is_not_the_building() -> None:
    # Furjan OLD 24293: sheet "Glamz Residence Tower 2"; the only 1111 sale is in Starz Tower 2.
    source = {
        "master_project": "Al Furjan",
        "building_name": "Glamz Residence Tower 2",
        "unit_number": "1111",
        "size_unknown": "37.17",
        "transaction_price_aed": "488819",
    }
    starz = event("1111", "Starz Tower 2", 488819, area="Al Furjan", size=400)
    assert match(source, [starz]).outcome == "no_evidence"


@pytest.mark.parametrize(
    "procedure",
    [
        "Mortgage Registration",
        "Lease to Own Registration",
        "Modify Mortgage",
        "Lease Finance Registration",
    ],
)
def test_a_financing_row_confirms_the_property_but_never_links_a_sale(procedure: str) -> None:
    # Dated on a day the unit did not sell, so the same-day mortgage rule does not apply.
    source = {**NAVITAS, "procedure_type": procedure, "transaction_date": "2020-03-01"}
    result = match(source, NAVITAS_WORLD)
    assert result.outcome == "property_confirmed_no_sale"
    assert result.sale is None
    assert result.property_key is not None and result.property_key[1] == "1410"
    assert "financing_row" in result.reasons


def test_a_financing_row_with_no_property_is_no_evidence() -> None:
    source = {
        "master_project": "DAMAC HILLS 2",
        "size_unknown": "173.06",
        "transaction_price_aed": "325990",
        "procedure_type": "Lease to Own Registration",
    }
    aster = transaction(325990, sqm=173.06, master="DAMAC HILLS 2", project="ASTER")
    result = match(source, [], [aster])
    assert result.outcome == "no_evidence" and result.sale is None
    assert "financing_row" in result.reasons


def test_a_sale_procedure_row_is_unaffected_by_the_financing_rule() -> None:
    assert match({**NAVITAS, "procedure_type": "Sell"}, NAVITAS_WORLD).outcome == "matched_sale"


# --------------------------------------------------------------------------- same-day mortgage


def _loan(amount: str = "368000", **changes: str) -> dict[str, str]:
    """A DLD mortgage row for Navitas 1410: its amount is the loan, not a sale price."""
    return {
        **NAVITAS,
        "procedure_type": "Mortgage Registration",
        "transaction_price_aed": amount,
        **changes,
    }


def test_a_mortgage_on_the_day_of_the_units_one_sale_is_that_sale() -> None:
    # The owner (mortgagor) bought the unit the day the mortgage was registered.
    result = match(_loan(), NAVITAS_WORLD)
    assert result.outcome == "matched_sale_via_mortgage"
    assert result.sale is not None and result.sale["event_date"] == "2022-05-20"
    assert result.sale["amount"] == 460000
    assert result.property_key == ("navitase", "1410")
    assert "financing_row" in result.reasons


def test_a_mortgage_whose_amount_equals_the_sale_price_is_still_via_mortgage() -> None:
    result = match(_loan("460000"), NAVITAS_WORLD)
    assert result.outcome == "matched_sale_via_mortgage"
    assert result.sale is not None and result.sale["amount"] == 460000


@pytest.mark.parametrize("date", ["2022-05-21", "2022-05-19", "1990-01-01"])
def test_a_mortgage_on_another_day_is_not_tied_to_the_sale(date: str) -> None:
    # Dates never select a sale: only the day a sale already happened on can confirm it.
    result = match(_loan(transaction_date=date), NAVITAS_WORLD)
    assert result.outcome == "property_confirmed_no_sale"
    assert result.sale is None


def test_a_mortgage_with_no_date_is_not_tied_to_a_sale() -> None:
    source = _loan()
    del source["transaction_date"]
    assert match(source, NAVITAS_WORLD).outcome == "property_confirmed_no_sale"


def test_two_sales_of_the_unit_on_the_mortgage_day_are_ambiguous() -> None:
    world = [
        *NAVITAS_WORLD,
        event("1410", "Navitas Tower E", 465000, project="Navitas", size=334, date="2022-05-20"),
    ]
    result = match(_loan(), world)
    assert result.outcome == "property_confirmed_no_sale"
    assert result.sale is None


def test_a_mortgage_on_a_unit_dxbi_does_not_know_stays_no_evidence() -> None:
    source = _loan(unit_number="9999")
    result = match(source, NAVITAS_WORLD)
    assert result.outcome == "no_evidence"


def test_a_mortgage_whose_size_contradicts_the_unit_is_still_rejected() -> None:
    result = match(_loan(size_unknown="900"), NAVITAS_WORLD)
    assert result.outcome == "rejected"


def test_a_sale_row_on_the_same_day_is_not_touched_by_the_mortgage_rule() -> None:
    result = match({**NAVITAS, "procedure_type": "Sell"}, NAVITAS_WORLD)
    assert result.outcome == "matched_sale"


# --------------------------------------------------------------------------- later sales


def test_a_later_sale_of_the_same_unit_is_reported() -> None:
    world = [
        *NAVITAS_WORLD,
        event("1410", "Navitas Tower E", 520000, project="Navitas", size=334, date="2024-02-01"),
    ]
    index = SalesIndex(world, PLACES, [])
    result = match_row(NAVITAS, index)
    assert result.outcome == "matched_sale"
    assert later_sale_date(index, result) == "2024-02-01"


def test_a_unit_with_no_sale_after_the_matched_one_has_no_later_sale() -> None:
    index = SalesIndex(NAVITAS_WORLD, PLACES, [])
    result = match_row(NAVITAS, index)
    # The 2026 Viridis A sale is a different building's 1410, and the 2016 one is earlier.
    assert later_sale_date(index, result) is None


def test_a_rental_after_the_sale_is_not_a_later_sale() -> None:
    world = [
        *NAVITAS_WORLD,
        event(
            "1410", "Navitas Tower E", 40000, family="rental", project="Navitas", date="2023-01-01"
        ),
    ]
    index = SalesIndex(world, PLACES, [])
    assert later_sale_date(index, match_row(NAVITAS, index)) is None


def test_a_registry_match_with_no_sale_unit_has_nothing_to_check_later_sales_on() -> None:
    source = {
        "master_project": "DAMAC HILLS 2",
        "size_unknown": "173.06",
        "transaction_price_aed": "325990",
    }
    aster = transaction(
        325990, sqm=173.06, master="DAMAC HILLS 2", area="Madinat Hind 4", project="ASTER"
    )
    index = SalesIndex([], PLACES, [aster])
    result = match_row(source, index)
    assert result.outcome == "matched_registry_sale_no_unit"
    assert later_sale_date(index, result) is None


def test_a_mortgage_match_checks_later_sales_from_the_matched_sale() -> None:
    world = [
        *NAVITAS_WORLD,
        event("1410", "Navitas Tower E", 520000, project="Navitas", size=334, date="2024-02-01"),
    ]
    index = SalesIndex(world, PLACES, [])
    result = match_row(_loan(), index)
    assert result.outcome == "matched_sale_via_mortgage"
    assert later_sale_date(index, result) == "2024-02-01"


# --------------------------------------------------------------------------- learned aliases

WALK = {
    "master_project": "City Walk",
    "project_name": "NO. 4A, NO.4B, NO.5 CITYWALK RESIDENTIAL",
    "building_name": "Citywalk Residential Building 5",
    "size_unknown": "107.63",
}
WALK_EVENTS = [
    event("715", "Citywalk Residential Building 5", 90000, area="City Walk", family="rental"),
    event("102", "Citywalk Residential Building 5", 90000, area="City Walk", family="rental"),
]


def _walk_sale(amount: int, unit: str, key: str, sqm: float = 107.63) -> dict[str, Any]:
    return {
        **transaction(
            amount,
            sqm=sqm,
            master="City Walk",
            area="Al Wasl",
            project="CITYWALK RESIDENTIAL",
            building="Citywalk Residential Building 5",
            unit=unit,
            status="matched",
        ),
        "dxbi_sale_key": key,
    }


def _walk_row(unit: str, amount: int) -> dict[str, str]:
    return {**WALK, "unit_number": unit, "transaction_price_aed": str(amount)}


def _walk(rows: list[tuple[str, int]], sales: list[dict[str, Any]]):
    index = SalesIndex(WALK_EVENTS, PLACES, sales)
    return [(row, match_row(row, index)) for row in (_walk_row(u, a) for u, a in rows)]


def test_a_unit_that_differs_on_two_sales_to_one_dxbi_unit_is_learned() -> None:
    sales = [_walk_sale(850000, "715", "a"), _walk_sale(910000, "715", "b")]
    pairs = _walk([("102", 850000), ("102", 910000)], sales)
    assert [r.outcome for _, r in pairs] == ["matched_sale_review"] * 2
    promoted = promote_learned_aliases(pairs)
    assert [r.outcome for r in promoted] == ["matched_sale"] * 2
    assert all("learned_unit_alias" in r.warnings for r in promoted)
    assert all(r.sale is pairs[i][1].sale for i, r in enumerate(promoted))


def test_a_single_sale_alias_stays_in_review() -> None:
    # Two rows of one sale (buyer and seller) are one piece of evidence.
    pairs = _walk([("102", 850000), ("102", 850000)], [_walk_sale(850000, "715", "a")])
    promoted = promote_learned_aliases(pairs)
    assert [r.outcome for r in promoted] == ["matched_sale_review"] * 2
    assert not any("learned_unit_alias" in r.warnings for r in promoted)


def test_an_alias_pointing_at_two_dxbi_units_is_not_learned() -> None:
    sales = [_walk_sale(850000, "715", "a"), _walk_sale(910000, "716", "b")]
    pairs = _walk([("102", 850000), ("102", 910000)], sales)
    assert {r.outcome for r in promote_learned_aliases(pairs)} == {"matched_sale_review"}


def test_an_alias_is_not_learned_when_another_sheet_unit_points_to_the_same_unit() -> None:
    sales = [
        _walk_sale(850000, "715", "a"),
        _walk_sale(910000, "715", "b"),
        _walk_sale(700000, "715", "c"),
    ]
    pairs = _walk([("102", 850000), ("102", 910000), ("715", 700000)], sales)
    promoted = promote_learned_aliases(pairs)
    assert [r.outcome for r in promoted[:2]] == ["matched_sale_review"] * 2
    assert promoted[2] is pairs[2][1]


def test_aliases_are_learned_per_sheet_place() -> None:
    # The same sheet unit in another building is another group and learns nothing from this one.
    sales = [_walk_sale(850000, "715", "a"), _walk_sale(910000, "715", "b")]
    pairs = _walk([("102", 850000), ("102", 910000)], sales)
    other = {**pairs[0][0], "building_name": "Citywalk Residential Building 4a"}
    promoted = promote_learned_aliases([*pairs[:1], (other, pairs[1][1])])
    assert [r.outcome for r in promoted] == ["matched_sale_review"] * 2


def test_other_outcomes_pass_through_promotion_untouched() -> None:
    sales = [_walk_sale(850000, "715", "a"), _walk_sale(910000, "715", "b")]
    pairs = _walk([("102", 850000), ("102", 910000)], sales)
    unknown = MatchResult("no_evidence", reasons=["unit_not_in_dxbi"])
    promoted = promote_learned_aliases([*pairs, ({"unit_number": "5"}, unknown)])
    assert promoted[-1] is unknown
    assert len(promoted) == 3


# Quarter-share hotel units: DXBI lists "2807 (Q 1)" … "2807 (Q 4)" as separate titles of one unit.
CIEL = {"master_project": "DAMAC HILLS 2", "building_name": "VIRIDIS A", "property_type": "Unit"}


def test_a_sale_of_another_share_of_the_unit_goes_to_review() -> None:
    source = {**CIEL, "unit_number": "2807 (Q 2)", "transaction_price_aed": "1300000"}
    world = [event("2807 (Q 1)", "Viridis A", 1300000, key="q1")]
    result = match(source, world)
    assert result.outcome == "matched_sale_review"
    assert any(w.startswith("share_qualifier_differs") for w in result.warnings)


def test_the_sale_of_the_same_share_wins_over_another_share_at_the_same_price() -> None:
    source = {**CIEL, "unit_number": "2807 (Q 2)", "transaction_price_aed": "1300000"}
    world = [
        event("2807 (Q 1)", "Viridis A", 1300000, key="q1"),
        event("2807 (Q 2)", "Viridis A", 1300000, key="q2"),
    ]
    result = match(source, world)
    assert result.outcome == "matched_sale"
    assert result.sale["event_key"] == "q2"


def test_a_unit_without_a_share_qualifier_is_unaffected() -> None:
    source = {**CIEL, "unit_number": "2807", "transaction_price_aed": "1300000"}
    result = match(source, [event("2807", "Viridis A", 1300000)])
    assert result.outcome == "matched_sale"
