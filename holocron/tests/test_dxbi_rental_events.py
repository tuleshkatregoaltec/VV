from datetime import date

from holocron.sources.dxbi.rental_events import normalize_rental_row


def test_normalize_rental_row_builds_stable_owner_period_candidate() -> None:
    payload = {
        "transaction_type": "rentals",
        "shard": {"date": "2026-07-01"},
        "columns": [
            {
                "id": "PATH_NAME",
                "text": "L-07, Greece Cluster, International City Apartment , Floor No. u-hidden , No.",
            },
            {"id": "PROP_SIZES", "text": "1 Bed 732 sqft"},
            {"id": "TOTAL_PRICES", "text": "38,000 +8.26% Renewed"},
            {"id": "START_DATE", "text": "1 Jul, 2026 - 30 Jun, 2027 12 Months"},
            {"id": "PURCHASE_PRICE", "text": "AED 460K"},
        ],
        "scraped_at": "2026-07-25T22:36:20.321504+00:00",
    }

    event = normalize_rental_row(payload, source_account="account-b")

    assert event is not None
    assert event["building_name"] == "L-07"
    assert event["project_name"] == "Greece Cluster"
    assert event["area_name"] == "International City"
    assert event["property_type"] == "Apartment"
    assert event["bedrooms"] == "1 Bed"
    assert event["size_sqft"] == 732
    assert event["annual_rent_aed"] == 38_000
    assert event["purchase_price_aed"] == 460_000
    assert event["lease_start"] == date(2026, 7, 1)
    assert event["lease_end"] == date(2027, 6, 30)
    assert event["contract_state"] == "Renewed"
    assert event["source_account"] == "account-b"


def test_purchase_price_changes_candidate_not_physical_cohort() -> None:
    base = {
        "columns": [
            {"id": "PATH_NAME", "text": "Ritaj A, Ritaj, DIP Apartment, Floor No. u-hidden"},
            {"id": "PROP_SIZES", "text": "Studio 450 sqft"},
            {"id": "TOTAL_PRICES", "text": "42,000 New"},
            {"id": "START_DATE", "text": "8 Mar, 2025 - 7 Mar, 2026 12 Months"},
            {"id": "PURCHASE_PRICE", "text": "AED 440K"},
        ]
    }
    sold = {
        **base,
        "columns": [
            *base["columns"][:-1],
            {"id": "PURCHASE_PRICE", "text": "AED 525K"},
        ],
    }

    first = normalize_rental_row(base)
    second = normalize_rental_row(sold)

    assert first is not None and second is not None
    assert first["unit_cohort_key"] == second["unit_cohort_key"]
    assert first["unit_candidate_key"] != second["unit_candidate_key"]
