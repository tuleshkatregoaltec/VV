"""Validation helpers: closest exact comparables, live-listing stats and the verdicts."""

from datetime import date

from app.crm.valuation_validation import (
    closest_sales,
    gap_pct,
    listing_stats,
    pick_sample,
    summarise,
)

SUBJECT = {
    "unit_key": "187",
    "building_key": "reem",
    "property_type": "Villa",
    "bedrooms": "3 Bed",
    "size_sqft": 2000.0,
}


def _s(unit, size, price, day="2026-08-01"):
    return {
        "unit_key": unit,
        "size_sqft": size,
        "sale_amount_aed": price,
        "transaction_date": date.fromisoformat(day),
    }


def test_own_unit_sale_is_reported_separately():
    out = closest_sales(SUBJECT, [_s("187", 2000, 2_700_000), _s("190", 2000, 2_600_000)])
    assert out["same_unit_resale"]["sale_amount_aed"] == 2_700_000
    assert [c["unit_key"] for c in out["comparables"]] == ["190"]


def test_comparables_outside_size_band_are_excluded():
    out = closest_sales(SUBJECT, [_s("1", 2200, 2_640_000), _s("2", 2600, 3_000_000)])
    assert [c["unit_key"] for c in out["comparables"]] == ["1"]
    assert out["median_adjusted_aed"] == 2_400_000  # 1200 psf x 2000 sqft


def test_closest_sales_keeps_five_nearest_in_size_then_newest():
    sales = [_s(str(i), 2000 + i * 10, 2_000_000) for i in range(8)]
    out = closest_sales(SUBJECT, sales)
    assert [c["unit_key"] for c in out["comparables"]] == ["0", "1", "2", "3", "4"]


def test_no_comparables_gives_none_median():
    assert closest_sales(SUBJECT, [])["median_adjusted_aed"] is None


def test_gap_pct():
    assert gap_pct(2_200_000, 2_000_000) == 10.0


def test_pick_sample_is_stratified_and_deterministic():
    groups = [(a, c) for a in "ABCDE" for c in ("high", "medium", "low")] * 10
    claims = [{"id": i, "area": a, "confidence": c} for i, (a, c) in enumerate(groups)]
    one, two = pick_sample(claims, 25), pick_sample(claims, 25)
    assert one == two and len(one) == 25
    assert {c["confidence"] for c in one} == {"high", "medium", "low"}
    assert {c["area"] for c in one} == set("ABCDE")


def test_duplicate_listings_count_once():
    rows = [
        {"asking_aed": 2_900_000, "size_sqft": 2000, "off_plan": "no"},
        {"asking_aed": 2_900_000, "size_sqft": 2010, "off_plan": "no"},
        {"asking_aed": 3_100_000, "size_sqft": 2100, "off_plan": "no"},
    ]
    assert listing_stats(rows)["count"] == 2


def test_off_plan_listings_are_excluded():
    rows = [{"asking_aed": 4_000_000, "size_sqft": 2000, "off_plan": "yes"}]
    assert listing_stats(rows)["count"] == 0


def test_listing_verdict_uses_asking_premium_band():
    # 8% under asking passes; 25% under fails.
    ok = summarise([], {"1": {"estimate": 2_760_000, "median": 3_000_000}})
    bad = summarise([], {"1": {"estimate": 2_250_000, "median": 3_000_000}})
    assert ok["verdicts"]["listings"] is True
    assert bad["verdicts"]["listings"] is False


def test_comparables_verdict_passes_at_ten_percent_median_gap():
    rows = [{"gap_pct": g, "confidence": "high"} for g in (-4.0, 6.0, 9.0, -12.0, 3.0)]
    out = summarise(rows, {})
    assert out["comparables"]["median_abs_gap"] == 6.0
    assert out["verdicts"]["comparables"] is True
