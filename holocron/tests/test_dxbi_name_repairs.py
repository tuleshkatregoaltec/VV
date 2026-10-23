from holocron.sources.dxbi.repairs import propose_name_repair
from holocron.sources.dxbi.sales_units import normalize_sales_row


def source():
    return {
        "location_title": "02 Residence, Business Bay",
        "location_text": "Buyer's agent Person 02 Residence, Business Bay Ready Apartment, No. 001-A",
        "unit_number": "001-A",
        "amount_text": "AED 975,000 AED 2,092 /sqft",
        "specs_text": "466 sqft Studio",
        "date_text": "17, Apr 2026",
        "detail_url": "https://dxbinteract.com/sold/t-proof",
    }


def test_repair_preserves_identity_and_numbers_and_is_repeatable():
    payload = source()
    correct = normalize_sales_row(payload)
    assert correct is not None
    old = {**correct, "building_name": "Person 02 Residence", "building_key": "person02residence"}
    proposal = propose_name_repair(payload, [old])
    assert proposal["status"] == "proposed"
    assert proposal["sale_key"] == old["sale_key"]
    assert proposal["changes"]["building_name"]["after"] == "02 Residence"
    assert "unit_number" not in proposal["changes"]
    assert propose_name_repair(payload, [correct])["status"] == "unchanged"


def test_similarity_missing_title_and_conflicting_identity_never_authorize_repair():
    payload = source()
    row = normalize_sales_row(payload)
    assert row is not None
    assert propose_name_repair({**payload, "location_title": ""}, [row])["status"] == "unresolved"
    assert (
        propose_name_repair(payload, [{**row, "detail_url": "different"}])["status"] == "unresolved"
    )
    assert propose_name_repair(payload, [row, row])["status"] == "unresolved"
    assert (
        propose_name_repair(payload, [{**row, "unit_number": "001-B"}])["reason"]
        == "conflicting_unit_number"
    )
