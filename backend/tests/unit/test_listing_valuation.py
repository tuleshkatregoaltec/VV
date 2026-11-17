"""Turning a Property Finder sale listing into a DLD-sales valuation subject (11 Nov 2026)."""

from datetime import date

from app.listings.comparables import ListingValuation
from app.listings.valuation import listing_subject, location_key, market_position

TODAY = date(2026, 11, 11)


def _row(**extra):
    row = {
        "listing_id": "L1",
        "category_id": 1,
        "location_names": ["Dubai", "Town Square", "Hayat Boulevard", "Hayat Boulevard 2A"],
        "property_type": "apartment",
        "completion_status": "completed",
        "bedrooms": "2",
        "price_aed": 1_500_000,
        "size_sqft": 1200.0,
    }
    row.update(extra)
    return row


def _valuation(value, low, high, confidence, level="building_type_beds", **detail):
    detail = {
        "level": level,
        "size_sqft": 1000.0,
        "comparable_size_sqft": 1000,
        "exact_count": 5,
        **detail,
    }
    return ListingValuation(value, low, high, confidence, detail)


def test_location_key_matches_dld_building_key():
    assert location_key("Hayat Boulevard 2A") == "hayatboulevard2a"
    assert location_key("Zahra Apartments 1A") == "zahraapartment1a"
    assert location_key("Elite Downtown Residences") == "elitedowntownresidence"
    assert location_key(None) == ""


def test_listing_subject_maps_apartment_with_building_candidates():
    s = listing_subject(_row(), TODAY)
    assert s.building_candidates == ["hayatboulevard2a", "hayatboulevard"]
    assert (s.subject.property_type, s.subject.bedrooms, s.area_key) == (
        "Apartment",
        "2 Bed",
        "townsquare",
    )
    assert (s.asking_aed, s.subject.size_sqft) == (1_500_000, 1200.0)


def test_villa_candidate_is_the_project():
    s = listing_subject(
        _row(location_names=["Dubai", "Damac Hills 2", "Verona"], property_type="villa"), TODAY
    )
    assert s.building_candidates == ["verona"]
    assert s.subject.property_type == "Villa"


def test_offplan_rent_and_commercial_are_not_valued():
    assert listing_subject(_row(completion_status="off_plan"), TODAY) is None
    assert listing_subject(_row(completion_status="off_plan_primary"), TODAY) is None
    assert listing_subject(_row(category_id=2), TODAY) is None
    assert listing_subject(_row(category_id=3), TODAY) is None
    assert listing_subject(_row(property_type="land"), TODAY) is None


def test_listing_subject_bedroom_and_price_edge_cases():
    assert listing_subject(_row(bedrooms="7+"), TODAY).subject.bedrooms == "7 Bed"
    assert listing_subject(_row(bedrooms="studio"), TODAY).subject.bedrooms == "Studio"
    villa = listing_subject(_row(bedrooms="", property_type="villa"), TODAY)
    assert villa.subject.bedrooms == ""
    assert listing_subject(_row(size_sqft=0), TODAY) is None
    assert listing_subject(_row(price_aed=None), TODAY) is None
    assert listing_subject(_row(property_type="penthouse"), TODAY).subject.property_type == (
        "Apartment"
    )


def test_market_position_rule():
    v = _valuation(2_000_000, 1_900_000, 2_100_000, "high")
    assert market_position(1_800_000, v) == ("below_market", -0.1)
    assert market_position(2_000_000, v)[0] == "near_market"
    assert market_position(2_300_000, v)[0] == "above_market"
    assert market_position(1_000_000, None) == ("insufficient_data", None)


def test_unmatched_building_never_flags():
    low = _valuation(2_000_000, 1_900_000, 2_100_000, "low")
    assert market_position(1_000_000, low) == ("insufficient_data", -0.5)


def test_area_level_estimate_is_never_flagged():
    # Area-wide sales mix very different homes (Dubai Hills 5BR: Maple townhouses with mansions).
    v = _valuation(18_500_000, 17_500_000, 19_500_000, "medium", level="area_type_beds")
    assert market_position(6_000_000, v)[0] == "insufficient_data"


def test_implausible_discount_is_not_a_bargain():
    # More than 40% under same-building sales is almost always a data error, not a bargain.
    v = _valuation(2_000_000, 1_900_000, 2_100_000, "high")
    assert market_position(1_100_000, v) == ("insufficient_data", -0.45)
    assert market_position(1_300_000, v)[0] == "below_market"


def test_building_without_same_bedroom_sales_is_not_flagged():
    # All-bedroom building prices mix studios with 2BR (Marina Diamond 2).
    v = _valuation(2_100_000, 2_000_000, 2_200_000, "medium", level="building_type")
    assert market_position(1_300_000, v)[0] == "insufficient_data"


def test_listing_far_from_the_sold_sizes_is_not_flagged():
    # Park Horizon Tower 2 3BR: sales are ~1,356 sqft; a 2,291 sqft listing gives a fake discount.
    v = _valuation(
        6_351_000, 6_000_000, 6_700_000, "high", size_sqft=2291.0, comparable_size_sqft=1356
    )
    assert market_position(3_850_000, v)[0] == "insufficient_data"


def test_villa_priced_by_bedroom_skips_the_size_check():
    v = _valuation(
        2_000_000,
        1_900_000,
        2_100_000,
        "high",
        basis="bedroom_price",
        size_sqft=2400.0,
        comparable_size_sqft=1215,
    )
    assert market_position(1_700_000, v)[0] == "below_market"


def test_apartment_needs_three_exact_comparables_to_be_flagged():
    v = _valuation(2_000_000, 1_900_000, 2_100_000, "high", exact_count=2)
    assert market_position(1_700_000, v)[0] == "insufficient_data"
