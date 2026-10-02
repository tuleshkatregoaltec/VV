"""Boundary choices are explicit; malformed brackets cannot silently change membership."""

import pytest
from pydantic import ValidationError

from app.analytics.market_metrics import _band_label
from app.analytics.models import MarketMetricsRequest
from app.listings.capability_models import ListingEvidenceRequest


def metrics(**fields):
    return MarketMetricsRequest(dataset="sales", period={"type": "previous_month"}, **fields)


def test_price_boundary_defaults_preserve_existing_callers():
    request = metrics()
    assert request.min_value_inclusive is True
    assert request.max_value_inclusive is False
    assert request.price_band_upper_inclusive is None
    listing = ListingEvidenceRequest()
    assert listing.price_min_inclusive is True
    assert listing.price_max_inclusive is True
    assert ListingEvidenceRequest(price_min=999_999.99).price_min == 999_999.99


@pytest.mark.parametrize(
    "fields",
    [
        {"price_band_upper_inclusive": [True]},
        {"group_by": "price_band", "price_bands": [1, 2], "price_band_upper_inclusive": [True]},
        {"group_by": "price_band", "price_bands": [1], "price_band_upper_inclusive": [True, False]},
        {"group_by": "price_band", "price_bands": [1, float("inf")]},
        {"group_by": "price_band", "price_bands": [float("nan")]},
        {"max_value_aed": float("inf")},
    ],
)
def test_price_boundary_invalid_specs_fail_before_querying(fields):
    with pytest.raises(ValidationError):
        metrics(**fields)


def test_price_boundary_labels_preserve_fractional_thresholds_and_equality_ownership():
    bands = [999_999.99, 2_000_000.01]
    assert [_band_label(i, bands, (False, True)) for i in range(3)] == [
        "under 999,999.99",
        "999,999.99 to including 2,000,000.01",
        "over 2,000,000.01",
    ]
    assert [_band_label(i, bands, (True, False)) for i in range(3)] == [
        "up to and including 999,999.99",
        "over 999,999.99 to under 2,000,000.01",
        "2,000,000.01 and above",
    ]
