import json
from datetime import date

from holocron.sources.dxbi.sales_units import compact_payload, location_key, normalize_sales_row


def test_normalize_sales_row_preserves_unit_and_purchase_evidence() -> None:
    payload = {
        "unit_number": "R08",
        "location_text": (
            "Buyer's agent Binghatti Hillcrest, Arjan Offplan Apartment, Floor u-hidden, No. R08"
        ),
        "amount_text": "AED 1,315,999 (-) AED 1,823 /sqft u-hidden% LTV",
        "specs_text": "722 sqft • - sqft BUA 1 Bed Balcony 149 sqft",
        "date_text": "04, Jul 2026 Developer (u-hidden)",
        "detail_url": "https://dxbinteract.com/sold/t-sqy1sjc3y",
    }

    event = normalize_sales_row(payload)

    assert event is not None
    assert event["unit_number"] == "R08"
    assert event["building_name"] == "Binghatti Hillcrest"
    assert event["area_name"] == "Arjan"
    assert event["property_type"] == "Apartment"
    assert event["bedrooms"] == "1 Bed"
    assert event["size_sqft"] == 722
    assert event["sale_amount_aed"] == 1_315_999
    assert event["price_per_sqft_aed"] == 1_823
    assert event["capital_gain_pct"] is None
    assert event["ltv_pct"] is None
    assert event["market_status"] == "Offplan"
    assert event["seller_type"] == "Developer"
    assert event["seller_transaction_count"] is None
    assert event["agent_side"] == "buyer"
    assert event["balcony_sqft"] == 149
    assert event["built_up_area_sqft"] is None
    assert event["transaction_date"] == date(2026, 7, 4)


def test_location_key_normalizes_common_dxbi_spelling_variants() -> None:
    assert location_key("Muraba Residences Palm Jumeriah") == location_key(
        "Muraba Residence Palm Jumeirah"
    )


def test_sales_area_uses_same_canonical_vocabulary_as_rentals() -> None:
    event = normalize_sales_row(
        {
            "unit_number": "602",
            "location_text": ("Tower 108, Jumeirah Village Circle (JVC) Ready Apartment, Floor 6"),
            "amount_text": "AED 900,000 AED 2,000 /sqft",
            "specs_text": "450 sqft Studio",
            "date_text": "01, Jan 2026 Individual",
        }
    )

    assert event is not None
    assert event["area_name"] == "Jumeirah Village Circle"
    assert event["area_key"] == "jumeirahvillagecircle"


def test_compact_payload_ignores_large_columns_array() -> None:
    payload = compact_payload(
        '{"unit_number":"302","location_text":"Tower, Area Ready Apartment, Floor 2",'
        '"columns":[{"html":"large"}]}'
    )

    assert payload == {
        "unit_number": "302",
        "location_text": "Tower, Area Ready Apartment, Floor 2",
    }


def test_compact_payload_adapts_current_raw_report_columns() -> None:
    payload = compact_payload(
        '{"transaction_type":"sales","columns":['
        '{"id":"PATH_NAME","text":"Buyer\'s agent Tower One, Business Bay Ready '
        'Apartment, Floor u-hidden, No. 604-S","links":[{"href":"https://dxbinteract.com/sold/t-123"}]},'
        '{"id":"TOTAL_PRICE","text":"AED 2,250,000 (+73%) AED 1,712 /sqft 80% LTV"},'
        '{"id":"BEDROOM","text":"1,314 sqft 2 Beds"},'
        '{"id":"SOLD_BY","text":"26, Aug 2026 Individual (4 Times)"}]}'
    )

    assert payload == {
        "unit_number": "604-S",
        "location_text": (
            "Buyer's agent Tower One, Business Bay Ready Apartment, Floor u-hidden, No. 604-S"
        ),
        "amount_text": "AED 2,250,000 (+73%) AED 1,712 /sqft 80% LTV",
        "specs_text": "1,314 sqft 2 Beds",
        "date_text": "26, Aug 2026 Individual (4 Times)",
        "detail_url": "https://dxbinteract.com/sold/t-123",
    }


def test_financing_and_resale_signals_are_normalized_without_guessing() -> None:
    event = normalize_sales_row(
        {
            "unit_number": "602",
            "location_text": (
                "Buyer's agent Aspect Tower, Executive Towers, Business Bay "
                "Ready Office, Floor u-hidden, No. 602"
            ),
            "amount_text": "AED 2,250,000 (+73%) AED 1,712 /sqft 80% LTV",
            "specs_text": "1,314 sqft • 1,400 sqft BUA",
            "date_text": "31, Jan 2025 Individual (4 Times)",
            "detail_url": "https://dxbinteract.com/sold/t-ozzxnlm",
        }
    )

    assert event is not None
    assert event["capital_gain_pct"] == 73
    assert event["ltv_pct"] == 80
    assert event["price_per_sqft_aed"] == 1_712
    assert event["seller_type"] == "Individual"
    assert event["seller_transaction_count"] == 4
    assert event["market_status"] == "Ready"
    assert event["built_up_area_sqft"] == 1_400


def test_plot_rows_without_market_status_keep_their_area_and_type() -> None:
    """DXBI lists plots as '<area> Plot' with no Offplan/Ready status. Read as other rows, the
    plot number became the area ('No. 630') and the type was lost (256 sales in 2026)."""

    def plot(location_text: str) -> dict:
        event = normalize_sales_row(
            {
                "unit_number": location_text.rsplit("No. ", 1)[-1],
                "location_text": location_text,
                "amount_text": "AED 4,000,000 (-) AED 400 /sqft",
                "specs_text": "10,000 sqft",
                "date_text": "15, Sep 2026 Individual (1 Time)",
                "detail_url": "https://dxbinteract.com/sold/t-plot",
            }
        )
        assert event is not None
        return event

    lone = plot("Buyer's agent Al Jafliya Plot, Floor u-hidden, No. 630")
    assert (lone["property_type"], lone["market_status"]) == ("Plot", "")
    assert (lone["building_name"], lone["area_name"], lone["unit_number"]) == (
        "Al Jafliya",
        "Al Jafliya",
        "630",
    )

    cluster = plot("Nice 1, Damac Lagoons Plot, Floor u-hidden, No. DL-M235")
    assert (cluster["building_name"], cluster["area_name"]) == ("Nice 1", "Damac Lagoons")

    nested = plot(
        "Bora Bora (All Phases), Damac Islands, Al Yelayiss 1 Plot, Floor u-hidden, No. DI-BB0744"
    )
    assert (nested["building_name"], nested["project_name"], nested["area_name"]) == (
        "Bora Bora (All Phases)",
        "Damac Islands",
        "Al Yelayiss 1",
    )
    assert nested["property_type"] == "Plot"

    # Rows with a status keep their existing reading.
    apartment = plot("Binghatti Hillcrest, Arjan Offplan Apartment, Floor 3, No. 301")
    assert (apartment["property_type"], apartment["market_status"]) == ("Apartment", "Offplan")
    assert (apartment["building_name"], apartment["area_name"]) == ("Binghatti Hillcrest", "Arjan")


def test_a_sale_dxbi_lists_without_its_unit_is_kept() -> None:
    """DXBI hides the unit of some sales (114,466 from 2014 to 2026, audit leak L1). DXBInteract
    still counts them, and dropping them left our sales totals about 10% short."""
    hidden = normalize_sales_row(
        {
            "unit_number": "u-hidden",
            "location_text": "Burj Vista Tower 1, Downtown Dubai Ready Apartment, Floor u-hidden",
            "amount_text": "AED 3,100,000 (+27%) AED 2,113 /sqft",
            "specs_text": "1,467 sqft 2 Beds",
            "date_text": "31, Aug 2026 Individual (1 Time)",
        }
    )
    assert hidden is not None
    assert (hidden["unit_number"], hidden["building_name"], hidden["area_name"]) == (
        "",
        "Burj Vista Tower 1",
        "Downtown Dubai",
    )
    assert (hidden["property_type"], hidden["sale_amount_aed"]) == ("Apartment", 3_100_000)

    # A whole building has no floor or unit, so its type ends the location text.
    building = normalize_sales_row(
        {
            "unit_number": "",
            "location_text": "Emaar Square 3, Downtown Dubai Ready Building",
            "amount_text": "AED 725,000,000 (+44%) AED 1,914 /sqft",
            "specs_text": "378,885 sqft",
            "date_text": "27, Aug 2026 Individual (2 Times)",
        }
    )
    assert building is not None
    assert (building["building_name"], building["area_name"]) == (
        "Emaar Square 3",
        "Downtown Dubai",
    )
    assert (building["property_type"], building["market_status"]) == ("Building", "Ready")


def _location_cell(title: str, text: str) -> dict:
    # The location cell as DXBI's sales report renders it (row HTML read on 2026-10-07).
    return {
        "id": "PATH_NAME",
        "text": text,
        "html": (
            '<div class="margin-left-sm locationsPath">\n<a href="/sold/t-abc">\n'
            f'<span class="bold-title" title="{title}">\n    {title} </span>\n'
            '<p title="Ready Apartment">\n    <span class="bg-ready">Ready</span> Apartment'
            '<span class="u-hidden padding-none">, Floor u-hidden</span>'
            '<span class="lock-access 1203">, No. 1203</span>\n</p>\n</a>\n</div>'
        ),
    }


def test_the_location_dxbi_shows_wins_over_an_agent_name_glued_to_the_building() -> None:
    """The cell's text also holds what DXBI hides on screen, such as the buyer's agent's name
    right before the building: "Hajar Binghatti Royale" for DXBI's "Binghatti Royale" (about 2% of
    sales since 2022). The title attribute holds the location DXBI shows."""
    text = (
        "Buyer's agent Hajar Binghatti Royale, Jumeirah Village Circle (JVC) Ready Apartment, "
        "Floor u-hidden, No. 1203"
    )
    line = json.dumps(
        {
            "transaction_type": "sales",
            "bucket_date": "2026-06-20",
            "unit_number": "1203",
            "location_text": text,
            "amount_text": "AED 1,050,000 (+5%) AED 1,500 /sqft",
            "specs_text": "700 sqft 1 Bed",
            "date_text": "20, Jun 2026 Individual (2 Times)",
            "detail_url": "https://dxbinteract.com/sold/t-abc",
            "columns": [
                _location_cell("Binghatti Royale, Jumeirah Village Circle (JVC)", text),
                {"id": "TOTAL_PRICE", "text": "AED 1,050,000 (+5%) AED 1,500 /sqft", "html": ""},
            ],
        }
    )

    event = normalize_sales_row(compact_payload(line))

    assert event is not None
    assert (event["building_name"], event["building_key"]) == (
        "Binghatti Royale",
        "binghattiroyale",
    )
    assert (event["area_name"], event["unit_number"]) == ("Jumeirah Village Circle", "1203")
    assert (event["property_type"], event["market_status"], event["agent_side"]) == (
        "Apartment",
        "Ready",
        "buyer",
    )

    escaped = compact_payload(
        json.dumps(
            {
                "transaction_type": "sales",
                "columns": [
                    _location_cell(
                        "Seven Hotel &amp; Apartments The Palm - A, Palm Jumeirah",
                        "Seven Hotel & Apartments The Palm - A, Palm Jumeirah Ready Apartment",
                    )
                ],
            }
        )
    )
    assert escaped["location_title"] == "Seven Hotel & Apartments The Palm - A, Palm Jumeirah"


def test_a_row_cut_off_inside_its_columns_keeps_its_text_fields() -> None:
    payload = compact_payload(
        '{"unit_number":"302","location_text":"Tower, Area Ready Apartment, Floor 2",'
        '"columns":[{"id":"PATH_NAME","html":"<span cla'
    )

    assert payload == {
        "unit_number": "302",
        "location_text": "Tower, Area Ready Apartment, Floor 2",
    }


def test_a_unit_number_with_a_space_is_read_whole() -> None:
    """Shops and offices carry units such as "RETAIL 06" (44,185 sales). Cut at the space, every
    retail unit in a building read as the same unit "RETAIL"."""
    payload = compact_payload(
        json.dumps(
            {
                "transaction_type": "sales",
                "columns": [
                    {
                        "id": "PATH_NAME",
                        "text": (
                            "Buyer's agent Sobha Solis Tower B, Al Hebiah First Offplan Shop, "
                            "Floor u-hidden, No. RETAIL 06"
                        ),
                    }
                ],
            }
        )
    )

    assert payload["unit_number"] == "RETAIL 06"


def test_explicit_registration_number_survives_raw_and_compact_reports():
    columns = [{"id": "TRANSACTION_NUMBER", "text": " 11-123-2026 "}]
    assert (
        compact_payload(json.dumps({"columns": columns}))["dld_transaction_number"] == "11-123-2026"
    )
    assert (
        compact_payload(json.dumps({"unit_number": "101", "columns": columns}))[
            "dld_transaction_number"
        ]
        == "11-123-2026"
    )
    payload = {
        "dld_transaction_number": "11-123-2026",
        "location_text": "Tower, Area Ready Apartment",
        "amount_text": "AED 1,000,000",
        "specs_text": "861 sqft",
        "date_text": "10, Sep 2026",
        "detail_url": "https://dxbinteract.com/sold/t-opaque",
    }
    event = normalize_sales_row(payload)
    assert event is not None
    assert event["dld_transaction_number"] == "11-123-2026"
    without = normalize_sales_row({**payload, "dld_transaction_number": ""})
    assert without is not None
    assert without["dld_transaction_number"] == ""
    assert event["sale_key"] == without["sale_key"]  # Enrichment cannot change DXBI identity.


def test_numbered_names_and_single_quoted_property_title_are_preserved() -> None:
    """Catalogue numbered buildings must not lose their prefix when removing agent text."""
    for name in (
        "02 Residence By Ned Al Ghurair",
        "03 Residence By Ned Al Ghurair",
        "08 Life Residences",
        "09 Life Residences",
        "014 Tower",
        "1 Lake Plaza",
    ):
        payload = compact_payload(
            json.dumps(
                {
                    "unit_number": "001-A",
                    "columns": [
                        {
                            "id": "PATH_NAME",
                            "html": f"<span title='{name}, Business Bay' class='bold-title extra'></span>",
                        }
                    ],
                    "location_text": f"Buyer's agent Person {name}, Business Bay Ready Apartment, No. 001-A",
                    "amount_text": "AED 975,000 AED 2,092 /sqft",
                    "specs_text": "466 sqft Studio",
                    "date_text": "17, Apr 2026",
                    "detail_url": "https://dxbinteract.com/sold/t-proof",
                }
            )
        )
        event = normalize_sales_row(payload)
        assert event is not None
        assert event["building_name"] == name
        assert event["unit_number"] == "001-A"
        assert event["detail_url"] == "https://dxbinteract.com/sold/t-proof"


def test_hidden_final_unit_never_becomes_a_building_number() -> None:
    payload = compact_payload(
        json.dumps(
            {
                "columns": [
                    {
                        "id": "PATH_NAME",
                        "text": "Building No. 12, Business Bay Ready Apartment, No. u-hidden",
                    }
                ]
            }
        )
    )
    assert payload["unit_number"] == ""


def test_a_placeholder_in_the_transaction_number_cell_is_no_registration() -> None:
    # Two different sales whose cell shows '-' must not share a "registration" identity.
    payload = {
        "location_text": "Tower, Area Ready Apartment",
        "amount_text": "AED 1,000,000",
        "specs_text": "861 sqft",
        "date_text": "10, Sep 2026",
        "detail_url": "https://dxbinteract.com/sold/t-opaque",
    }
    for placeholder in ("-", "N/A", " "):
        event = normalize_sales_row({**payload, "dld_transaction_number": placeholder})
        assert event is not None and event["dld_transaction_number"] == ""
