import pytest

from app.crm.identity import _normalize_phone
from app.crm.import_parsing import (
    _heuristic_mapping,
    _inspect_csv,
    _parse_csv,
    _summary,
    _unique_headers,
)
from app.crm.owner_signals import build_owner_signals


@pytest.mark.parametrize("value", ["+9715012345678901", "0000000000", "1111111111", "123"])
def test_placeholder_or_concatenated_numbers_cannot_support_contact_identity(value):
    assert _normalize_phone(value) is None


@pytest.mark.parametrize("value", ["050 123 4567", "+971501234567", "00971501234567"])
def test_formatting_variants_keep_one_usable_contact_identity(value):
    assert _normalize_phone(value) == "+971501234567"


def _row(key="a", name="Example Person", unit="1", phone="+971501234567"):
    return {
        "canonical_owner_key": key,
        "contact_name": name,
        "phone_primary": phone,
        "property_identity": ("area", f"building|{unit}"),
    }


def test_many_properties_do_not_establish_a_brokerage_role():
    rows = [_row(unit=str(unit)) for unit in range(66)]
    signal = build_owner_signals(rows + rows)["a"]
    assert signal["relationship_role"] == "unknown"
    assert "66 identifiable properties" in signal["role_signals"][0]


def test_repeated_sources_do_not_inflate_shared_phone_evidence():
    signal = build_owner_signals([_row()] * 100)["a"]
    assert signal == {
        "relationship_role": "unknown",
        "role_signals": [],
        "developer_side_seller": False,
    }


def test_shared_phone_is_a_review_signal_not_confirmed_profession():
    rows = [_row(key=str(i), name=f"Example Person {i}") for i in range(5)]
    signals = build_owner_signals(rows)
    assert all(s["relationship_role"] == "possible_intermediary" for s in signals.values())
    assert all("5 distinct names" in s["role_signals"][0] for s in signals.values())


def test_company_name_does_not_establish_developer_or_broker_role():
    signal = build_owner_signals([_row(name="Example Development LLC")])["a"]
    assert signal["relationship_role"] == "organization"
    assert "has not been verified" in signal["role_signals"][0]


def _sale(key, name, unit, building, procedure="Complete Delayed Sell", role="Seller"):
    return _row(key=key, name=name, unit=f"{building}-{unit}") | {
        "party_role": role,
        "procedure_type": procedure,
        "building_name": building,
    }


def test_a_person_selling_off_plan_units_for_a_developer_is_not_a_former_owner():
    # One signatory's rows carry a different phone per buyer, so the name splits into several
    # identities; all of them are the developer side, however few units each holds.
    name = "Example Signatory"
    rows = [_sale(f"id-{unit % 5}", name, unit, f"Tower {unit % 4}") for unit in range(60)]
    signals = build_owner_signals(rows)
    for key in {f"id-{n}" for n in range(5)}:
        assert signals[key]["developer_side_seller"] is True
        assert signals[key]["relationship_role"] == "possible_intermediary"
        assert any("developer-side seller" in s for s in signals[key]["role_signals"])


@pytest.mark.parametrize(
    ("units", "buildings", "procedure"),
    [
        (49, 4, "Complete Delayed Sell"),  # too few units
        (60, 2, "Delayed Sell"),  # one project's own resales
        (60, 4, "Sell"),  # ordinary resales: a real investor's history
    ],
)
def test_an_investor_selling_their_own_units_stays_a_former_owner(units, buildings, procedure):
    rows = [
        _sale("a", "Example Investor", u, f"Tower {u % buildings}", procedure) for u in range(units)
    ]
    signal = build_owner_signals(rows)["a"]
    assert signal["developer_side_seller"] is False
    assert signal["relationship_role"] == "unknown"


def test_a_developer_company_stays_an_organization():
    rows = [_sale("a", "Example Developments LLC", u, f"Tower {u % 4}") for u in range(60)]
    signal = build_owner_signals(rows)["a"]
    assert signal["relationship_role"] == "organization"
    assert signal["developer_side_seller"] is False


def test_explicit_area_units_are_not_silently_treated_as_square_feet():
    headers = _unique_headers(["NameEn", "Area (sq.m)", "Size (sq.ft)"])
    mapping, _, _ = _heuristic_mapping(headers, filename="Owners.xlsx", sheet_name="Sheet1")
    assert mapping["size_sqm"] == "Area (sq.m)"
    assert mapping["size_sqft"] == "Size (sq.ft)"


@pytest.mark.parametrize("header", ["Size", "Property Size"])
def test_unlabelled_size_is_retained_without_inventing_a_unit(header):
    headers = _unique_headers(["NameEn", header])
    mapping, _, warnings = _heuristic_mapping(headers, filename="Owners.xlsx", sheet_name="Sheet1")
    assert mapping["size_unknown"] == header
    assert "size_sqft" not in mapping
    assert "size_sqm" not in mapping
    assert any("no stated unit" in warning for warning in warnings)


def test_mapping_a_generic_size_column_does_not_invent_square_feet():
    data = b"NameEn,Building,UnitNumber,Size\nExample Person,Example Tower,101,100\n"
    profiles = _inspect_csv(data, "owners.csv")
    profiles[0].field_map.pop("size_unknown")
    profiles[0].field_map["size_sqft"] = "Size"
    candidates, total = _parse_csv(data, "owners.csv", profiles)
    assert total == len(candidates) == 1
    assert candidates[0].evidence["source_size_unit"] == "unknown"
    assert candidates[0].evidence["source_fields"]["size_sqft"] == "100"


@pytest.mark.parametrize("role,ready", [("Buyer", 1), ("Seller", 0)])
def test_possible_seller_stays_visible_without_automatic_contact_readiness(role, ready):
    data = (
        "NameEn,Building,UnitNumber,Mobile,PartyRole\n"
        f"Example Person,Example Tower,101,0501234567,{role}\n"
    ).encode()
    candidates, total = _parse_csv(data, "owners.csv", _inspect_csv(data, "owners.csv"))
    candidates[0].ownership_status = "probable_current_owner"
    candidates[0].confidence_score = 55 if role == "Seller" else 75
    candidates[0].lead_id = "lease"
    summary = _summary(candidates, total_rows=total)
    assert summary.probable_current_owners == 1
    assert summary.contact_ready == ready
