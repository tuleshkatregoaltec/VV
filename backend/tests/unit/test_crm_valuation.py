"""Owner property valuation (client call, 5 Nov 2026).

Owner records only carry the price paid, often years ago. Buyers must be matched against what
the property is worth today, so each current owner's unit gets an estimate from recent
comparable sales, or from its purchase price moved by the area's price index.
"""

from datetime import date

import pytest

from app.crm.valuation import CompStats, ValuationSubject, estimate

TODAY = date(2026, 11, 5)


def _subject(**overrides) -> ValuationSubject:
    values = {
        "claim_id": 1,
        "purchase_price_aed": 2_000_000,
        "purchase_date": date(2023, 3, 1),
        "property_type": "Villa",
        "bedrooms": "3",
        "size_sqft": 1000.0,
        "building_key": "reem-townhouses",
        "area_key": "town-square",
    }
    values.update(overrides)
    return ValuationSubject(**values)


def _comps(**levels) -> dict[str, CompStats | None]:
    names = ("building_type_beds", "building_type", "area_type_beds", "area_type")
    return {name: levels.get(name) for name in names}


def test_building_level_wins_when_it_has_five_sales():
    result = estimate(
        _subject(),
        _comps(
            building_type_beds=CompStats(5, 1800, 2000, 2200),
            area_type=CompStats(500, 900, 1000, 1100),
        ),
        None,
        None,
        TODAY,
    )
    assert result is not None
    assert (result.estimated_value_aed, result.low_aed, result.high_aed) == (
        2_000_000,
        1_800_000,
        2_200_000,
    )
    assert result.method == "comparables"
    assert result.confidence == "high"
    assert result.detail["level"] == "building_type_beds"
    assert result.detail["comparable_count"] == 5


def test_ladder_skips_thin_levels():
    # Four same-layout sales are too few to trust; the building's seven sales of the type win.
    result = estimate(
        _subject(),
        _comps(
            building_type_beds=CompStats(4, 2500, 2600, 2700),
            building_type=CompStats(7, 1900, 2000, 2100),
        ),
        None,
        None,
        TODAY,
    )
    assert result is not None
    assert result.detail["level"] == "building_type"
    assert result.confidence == "medium"


def test_area_levels_need_ten():
    result = estimate(
        _subject(),
        _comps(
            area_type_beds=CompStats(9, 1900, 2000, 2100),
            area_type=CompStats(12, 1900, 2000, 2100),
        ),
        None,
        None,
        TODAY,
    )
    assert result is not None
    assert result.detail["level"] == "area_type"
    assert result.confidence == "low"


def test_no_size_uses_index():
    result = estimate(
        _subject(size_sqft=None, purchase_price_aed=1_500_000),
        _comps(building_type_beds=CompStats(30, 1800, 2000, 2200)),
        CompStats(40, 1500, 1600, 1700),
        CompStats(40, 1100, 1200, 1300),
        TODAY,
    )
    assert result is not None
    assert (result.estimated_value_aed, result.low_aed, result.high_aed) == (
        2_000_000,
        1_700_000,
        2_300_000,
    )
    assert result.method == "indexed_purchase"
    assert result.confidence == "low"
    assert result.detail["index_ratio"] == pytest.approx(1.3333, rel=1e-3)


def test_index_needs_ten_each_side():
    result = estimate(
        _subject(size_sqft=None),
        _comps(),
        CompStats(40, 1500, 1600, 1700),
        CompStats(9, 1100, 1200, 1300),
        TODAY,
    )
    assert result is None


def test_non_residential_is_not_valued():
    result = estimate(
        _subject(property_type="Plot"),
        _comps(building_type_beds=CompStats(30, 1800, 2000, 2200)),
        None,
        None,
        TODAY,
    )
    assert result is None


def test_far_from_purchase_is_flagged():
    # A unit that is not like its neighbours (penthouse, shell) can be valued far from what was
    # paid; the estimate is kept but must not be presented as reliable.
    result = estimate(
        _subject(purchase_price_aed=1_000_000),
        _comps(building_type_beds=CompStats(30, 3800, 4000, 4200)),
        None,
        None,
        TODAY,
    )
    assert result is not None
    assert result.estimated_value_aed == 4_000_000
    assert result.confidence == "low"
    assert result.detail["flag"] == "far_from_purchase"


def test_amounts_round_to_thousand():
    result = estimate(
        _subject(size_sqft=1001.0),
        _comps(building_type_beds=CompStats(30, 1111.1, 1234.5, 1333.3)),
        None,
        None,
        TODAY,
    )
    assert result is not None
    assert result.estimated_value_aed % 1000 == 0
    assert result.low_aed % 1000 == 0
    assert result.high_aed % 1000 == 0
    assert result.detail["valued_at"] == "2026-11-05"


def test_range_is_at_least_five_percent_each_side():
    # Comparables at one price (e.g. one bulk deal) must not produce a near-zero range.
    result = estimate(
        _subject(),
        _comps(building_type_beds=CompStats(6, 1995, 2000, 2005)),
        None,
        None,
        TODAY,
    )
    assert result is not None
    assert (result.low_aed, result.high_aed) == (1_900_000, 2_100_000)


def test_wider_comparable_range_is_kept():
    result = estimate(
        _subject(),
        _comps(building_type_beds=CompStats(6, 1700, 2000, 2400)),
        None,
        None,
        TODAY,
    )
    assert (result.low_aed, result.high_aed) == (1_700_000, 2_400_000)
