"""The feasibility chat works in square feet; the workbook keeps square metres."""

import pytest
from pydantic_ai.messages import ToolCallPart

from app.feasibility.chat import _extract_payload
from app.feasibility.chat_units import to_sqft_view, to_workbook_units

SQFT = 10.7639


def test_the_chat_sees_areas_in_sq_ft_and_rates_per_sq_ft():
    view = to_sqft_view(
        {
            "plotAreaSqm": 1000,
            "parkingAreaPerSpaceSqm": 30,
            "constructionCostPsqmBua": 4000,
            "unitConfigs": [{"id": "1br", "avgSizeSqm": 70, "sellingRatePsqm": 20000}],
            "median_rent_psm_annual": 1076.39,
            "price_per_gfa_sqm": 5000,
            "avg_rent_price_sqm_12m": None,
            # "current" holds "rent" as letters but is not a rate: the size still converts as area.
            "currentAreaSqm": 10,
            "label": "unchanged",
        }
    )

    assert view == {
        "plotAreaSqft": 10763.9,
        "parkingAreaPerSpaceSqft": 322.92,
        "constructionCostPsqftBua": 371.61,
        "unitConfigs": [{"id": "1br", "avgSizeSqft": 753.47, "sellingRatePsqft": 1858.06}],
        "median_rent_psqft_annual": 100.0,
        "price_per_gfa_sqft": 464.52,
        "avg_rent_price_sqft_12m": None,
        "currentAreaSqft": 107.64,
        "label": "unchanged",
    }


def test_proposals_in_sq_ft_reach_the_workbook_in_m2():
    workbook = to_workbook_units({"constructionCostPsqftBua": 400, "parkingAreaPerSpaceSqft": 323})
    assert workbook["constructionCostPsqmBua"] == pytest.approx(400 * SQFT)
    assert workbook["parkingAreaPerSpaceSqm"] == pytest.approx(323 / SQFT)
    # A workbook key the chat did not convert passes through unchanged.
    assert to_workbook_units({"targetCoveragePct": 45}) == {"targetCoveragePct": 45}


def test_staged_price_and_unit_mix_changes_are_converted_for_the_frontend():
    prices = _extract_payload(ToolCallPart("update_prices", {"prices": {"1br": 1800}}))
    assert prices == {"1br": pytest.approx(1800 * SQFT)}

    rows = _extract_payload(
        ToolCallPart(
            "replace_unit_mix",
            {"unit_mix": [{"type": "1br", "count": 40, "avgSizeSqft": 750, "price_sqft": 1800}]},
        )
    )
    assert rows == [
        {
            "type": "1br",
            "count": 40,
            "avgSizeSqm": pytest.approx(750 / SQFT),
            "price_sqm": pytest.approx(1800 * SQFT),
        }
    ]
