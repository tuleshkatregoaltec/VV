"""A property denominator must not merge a villa cluster or count sales as properties."""

from scripts.crm.clean_owner_workbook import normalize_row
from scripts.crm.inventory_owner_workbook import build_inventory, candidate_events


def record(
    number,
    *,
    name=None,
    building="Villa-1",
    unit=None,
    land="42",
    size=200,
    project="Maple",
    price=1000000,
    date="2020-01-01",
    kind="Villa",
):
    row = normalize_row(
        (
            date,
            price,
            "Dubai Hills",
            project,
            "plot-42",
            building,
            name,
            size,
            unit,
            "123",
            kind,
            land,
            "Buyer",
            "Example",
            "0500000000",
            "AE",
            None,
        )
    )
    return number, row, row


def test_multiple_villas_on_one_plot_keep_individual_names_despite_shared_building_number():
    inventory, _, metrics = build_inventory(
        [
            record(2, name="Villa-1"),
            record(3, name="Villa-2"),
            record(4, name="Villa-1", date="2023-01-01", price=2000000, kind="Building"),
        ]
    )
    assert metrics["reference_groups_by_kind"] == {"named_villa_or_building": 2}
    assert metrics["references_with_multiple_dates"] == 1
    assert len(inventory) == 2


def test_same_apartment_number_and_size_in_different_towers_are_different_properties():
    _, _, metrics = build_inventory(
        [
            record(2, name="Tower A", unit="101", kind="Flat"),
            record(3, name="Tower B", unit="101", kind="Unit"),
        ]
    )
    assert metrics["reference_groups_by_kind"] == {"unit": 2}


def test_similar_size_villas_must_not_create_false_unique_link():
    _, proposals, metrics = build_inventory(
        [
            record(2, name="Villa-1", size=305.05),
            record(3, name="Villa-2", size=305.29),
            record(4, size=305.1),
        ]
    )
    assert proposals[0]["decision"] == "multiple_size_matches_do_not_merge"
    assert metrics["source_reference_groups"] == 3
    assert metrics["exact_physical_property_count"] is None


def test_unique_observed_area_link_is_only_a_proposal_and_retains_source():
    inventory, proposals, metrics = build_inventory(
        [
            record(2, name="Villa-1", size=200),
            record(3, name="Villa-2", size=300),
            record(4, size=200),
        ]
    )
    assert proposals[0]["decision"] == "one_observed_size_match_proposed_only"
    assert len(inventory) == 3
    assert metrics["clean_rows"] == 3


def test_parent_parcel_is_not_added_to_individual_count_or_discarded():
    inventory, _, metrics = build_inventory(
        [
            record(2, name="Villa-1", size=200),
            record(3, building=None, size=1000, kind="Land"),
        ]
    )
    parcel = next(item for item in inventory if item["kind"] == "parcel_only")
    assert "parcel_overlaps_individual_asset_records" in parcel["review_reasons"]
    assert metrics["named_individual_reference_groups"] == 1
    assert metrics["source_rows"] == 2


def test_conflicting_parcels_and_large_area_variation_remain_visible():
    inventory, _, _ = build_inventory(
        [
            record(2, name="Tower A", unit="101", size=80),
            record(3, name="Tower A", unit="101", size=300, land="99"),
        ]
    )
    assert "same_address_multiple_land_numbers" in inventory[0]["review_reasons"]
    assert "area_spread_over_10_percent" in inventory[0]["review_reasons"]


def test_event_label_variants_and_buyer_seller_sides_do_not_multiply_event_count():
    first = record(2, name="Villa-1", kind="Villa")
    number, raw, normalized = record(3, name="Villa-1", kind="Building")
    seller = list(normalized)
    seller[12] = "Seller"
    seller[13] = "Different party"
    third = record(4, name="Villa-1", date="2023-01-01", price=2000000)
    events = candidate_events([first, (number, raw, tuple(seller)), third])
    assert len(events) == 2
    assert events[0]["source_attribute_variants"] == 2
    assert events[0]["buyer_rows"] == 1
    assert events[0]["seller_rows"] == 1
    assert sum(event["retained_party_rows"] for event in events) == 3
