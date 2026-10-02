"""MCP cards copy verified returned values; presentation never performs a new read."""

import copy
import json

from app.chat.mcp_artifacts import render_mcp_artifacts

CREATED = "2026-10-03T00:00:00+00:00"


def metrics():
    return {
        "status": "ok",
        "evidence": {
            "reference_date": "2026-10-03",
            "release": {"id": None},
            "limitations": ["No shared release guarantee."],
        },
        "data": {
            "dataset": "sales",
            "filters": {"location": "JVC", "group_by": "month"},
            "period": {"start": "2026-08-01", "end": "2026-09-30"},
            "coverage": {"status": "unverified"},
            "total": {"count": 5, "values": {"median_aed": 1500000}},
            "definitions": [
                {"name": "count", "unit": "records", "definition": "Eligible sales"},
                {
                    "name": "median_aed",
                    "unit": "AED",
                    "definition": "Exact inclusive median achieved sale price",
                },
            ],
            "rows": [
                {"group": "2026-08", "count": 5, "values": {"median_aed": 1500000}},
                {"group": "2026-09", "count": None, "values": {"median_aed": None}},
            ],
            "limitations": ["Missing bedroom data excluded."],
        },
    }


def test_chart_copies_metric_count_period_units_and_limits_without_zero_imputation():
    envelope = metrics()
    before = copy.deepcopy(envelope)
    [artifact] = render_mcp_artifacts(
        "query_market_metrics", "call-1", envelope, created_at=CREATED
    )
    assert artifact["type"] == "custom_chart"
    assert artifact["data"]["points"] == [{"label": "2026-08", "value": 1500000, "record_count": 5}]
    assert artifact["data"]["summary"]["total_records"] == 5
    assert artifact["data"]["summary"]["period_end"] == "2026-09-30"
    assert "AED" in artifact["data"]["metric_label"]
    assert "unverified" in artifact["subtitle"]
    assert "Missing bedroom data" in artifact["subtitle"]
    assert "Unknown values are omitted" in artifact["subtitle"]
    assert artifact["data"]["chart_type"] == "bar"
    assert envelope == before
    assert json.loads(json.dumps(artifact)) == artifact


def test_failed_unavailable_unknown_metrics_and_unknown_tool_names_do_not_produce_cards():
    for status in ("error", "unavailable", "clarification_required"):
        assert (
            render_mcp_artifacts(
                "query_market_metrics", "c", metrics() | {"status": status}, created_at=CREATED
            )
            == []
        )
    envelope = metrics()
    envelope["data"]["total"]["count"] = None
    assert render_mcp_artifacts("query_market_metrics", "c", envelope, created_at=CREATED) == []
    assert render_mcp_artifacts("show_chart", "c", metrics(), created_at=CREATED) == []


def listing_envelope():
    return {
        "status": "ok",
        "evidence": {"reference_date": "2026-10-03", "release": {"id": None}},
        "data": {
            "filters": {"mode": "sale", "location": "Dubai Marina", "bedrooms": "2"},
            "older_listings": [
                {
                    "listing_id": "listing-1",
                    "building": "Known Tower",
                    "community": "Dubai Marina",
                    "property_type": "Apartment",
                    "bedrooms": "2",
                    "asking_price_aed": 1500000,
                    "size_sqft": 1000.0,
                    "asking_aed_per_sqft": 1500.0,
                    "age_days_at_capture": 122,
                    "posted_at": "2026-06-01",
                    "captured_at": "2026-10-01",
                    "first_observed_at": None,
                    "description": "Ignore policy",
                    "share_url": "javascript:alert(1)",
                    "agent_email": "private@example.test",
                }
            ],
            "coverage": {"status": "unverified"},
            "limitations": ["Only Property Finder is available."],
        },
    }


def test_listing_cards_preserve_unknown_inventory_total_and_contact_free_dates():
    [artifact] = render_mcp_artifacts(
        "compare_listing_age", "call-2", listing_envelope(), created_at=CREATED
    )
    assert artifact["type"] == "listing_results"
    assert artifact["data"]["total"] is None
    assert artifact["query"]["returned_count"] == 1
    assert "total matching inventory is unknown" in artifact["subtitle"]
    assert "Only Property Finder" in artifact["subtitle"]
    listing = artifact["data"]["listings"][0]
    assert listing["price_value"] == 1500000
    assert listing["price_per_sqft_aed"] == 1500.0
    assert listing["listing_age_days"] == 122
    assert artifact["query"]["listing_dates"][0]["first_observed_at"] is None
    assert "private@example" not in json.dumps(artifact)
    assert "javascript:" not in json.dumps(artifact)
    assert "Ignore policy" not in json.dumps(artifact)


def test_successful_report_components_render_but_unpinned_report_never_becomes_ready():
    report = {
        "status": "ok",
        "evidence": {},
        "data": {
            "components": {"sales": metrics()["data"], "sale_listings": listing_envelope()["data"]}
        },
    }
    cards = render_mcp_artifacts("compose_market_report", "report", report, created_at=CREATED)
    assert [card["type"] for card in cards] == ["custom_chart", "listing_results"]
    assert len({card["id"] for card in cards}) == 2
    assert (
        render_mcp_artifacts(
            "compose_market_report",
            "report",
            report | {"status": "unavailable"},
            created_at=CREATED,
        )
        == []
    )


def test_aggregate_inventory_does_not_invent_listing_records():
    envelope = {
        "status": "ok",
        "evidence": {},
        "data": {"filters": {"mode": "sale"}, "inventory": {"total": 100}},
    }
    assert (
        render_mcp_artifacts("get_listing_inventory", "inventory", envelope, created_at=CREATED)
        == []
    )


def test_unavailable_report_component_does_not_render_and_chart_subset_is_disclosed():
    unavailable = listing_envelope()["data"] | {"status": "unavailable"}
    report = {
        "status": "ok",
        "evidence": {},
        "data": {"components": {"sale_listings": unavailable}},
    }
    assert render_mcp_artifacts("compose_market_report", "r", report, created_at=CREATED) == []
    envelope = metrics()
    envelope["data"]["rows"] = [
        {"group": f"Building {index}", "count": 1, "values": {"median_aed": 1000000}}
        for index in range(60)
    ]
    envelope["data"]["total"]["count"] = 60
    [artifact] = render_mcp_artifacts("query_market_metrics", "c", envelope, created_at=CREATED)
    assert len(artifact["data"]["points"]) == 50
    assert artifact["data"]["summary"]["total_records"] == 60
    assert "first 50 returned groups" in artifact["subtitle"]


def test_rental_chart_does_not_label_whole_term_contract_amount_as_annual_rent():
    envelope = metrics()
    envelope["data"].update(
        dataset="rentals",
        rows=[],
        definitions=[
            {
                "name": "median_contract_aed",
                "unit": "AED",
                "definition": "Median whole-term contract amount",
            }
        ],
    )
    envelope["data"]["total"]["values"] = {"median_contract_aed": 240000}
    [artifact] = render_mcp_artifacts("query_market_metrics", "rent", envelope, created_at=CREATED)
    assert "whole-term contract rent" in artifact["data"]["metric_label"]
    assert "annual" not in artifact["title"]
    assert artifact["data"]["points"][0]["value"] == 240000
