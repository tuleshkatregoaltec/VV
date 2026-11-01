"""How a matcher outcome and the party's role become an ownership status (the live-switch contract)."""

from __future__ import annotations

from datetime import date

import pytest

from app.crm.identity import ParsedContact
from app.crm.owner_match_status import (
    decide,
    looks_like_a_lender,
    owner_match_evidence,
    review_reason,
    summarize_owner_matches,
)
from app.crm.owner_matcher import MATCHER_VERSION, MatchResult
from app.crm.ownership import _apply_evidence

SALE = {
    "family": "sale",
    "event_key": "k2",
    "event_date": "2022-05-20",
    "amount": 460000,
    "unit_number": "1410",
    "building_name": "Navitas Tower E",
    "project_name": "Navitas",
    "area_name": "Damac Hills 2",
    "size_sqft": 334.0,
}


def result(outcome: str = "matched_sale", sale: dict | None = SALE, **fields) -> MatchResult:
    return MatchResult(outcome, ("navitase", "1410"), sale, ["unit 1410 in navitase"], **fields)  # type: ignore[arg-type]


def status(outcome: str, role: str, *, later: str | None = None, name: str = "Zainab", **kw):
    return decide(
        outcome,
        party_role=role,
        contact_name=name,
        procedure_type=kw.pop("procedure_type", "Sell"),
        later_sale_date=later,
        legacy_status=kw.pop("legacy_status", "unmatched"),
        legacy_property_found=kw.pop("found", False),
    )


@pytest.mark.parametrize(
    ("outcome", "role", "later", "expected"),
    [
        ("matched_sale", "Buyer", None, "verified_current_owner"),
        ("matched_sale", "Buyer", "2024-02-01", "former_owner"),
        ("matched_sale_inferred_unit", "Buyer", None, "verified_current_owner"),
        ("matched_registry_sale", "Buyer", None, "verified_current_owner"),
        ("matched_registry_sale", "Buyer", "2024-02-01", "former_owner"),
        ("matched_registry_sale_no_unit", "Buyer", None, "probable_current_owner"),
        ("matched_sale", "Seller", None, "former_owner"),
        ("matched_sale", "", None, "probable_current_owner"),
        ("matched_sale", "Owner", None, "probable_current_owner"),
        ("matched_registry_sale_no_unit", "Seller", None, "former_owner"),
    ],
)
def test_green_rows_become_owner_statuses(outcome, role, later, expected) -> None:
    decision = status(outcome, role, later=later)
    assert decision.status == expected
    assert decision.outcome == outcome and decision.colour == "green"


@pytest.mark.parametrize(
    ("role", "later", "expected"),
    [
        ("Seller", None, "verified_current_owner"),  # DLD's Seller on a mortgage row is the owner
        ("Seller", "2024-02-01", "former_owner"),
        ("", None, "probable_current_owner"),
    ],
)
def test_a_mortgage_row_matched_to_its_sale_names_the_seller_as_the_owner(
    role, later, expected
) -> None:
    decision = status(
        "matched_sale_via_mortgage", role, later=later, procedure_type="Mortgage Registration"
    )
    assert decision.status == expected and decision.colour == "green"


def test_the_buyer_of_a_mortgage_row_is_never_called_the_owner() -> None:
    # the lender, under a name the bank pattern does not know
    decision = status("matched_sale_via_mortgage", "Buyer", procedure_type="Mortgage Registration")
    assert decision.status == "unit_linked_unverified"
    assert decision.colour == "green"


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("Buyer", "probable_current_owner"),
        ("", "probable_current_owner"),
        ("Seller", "unverified_former_owner"),
    ],
)
def test_amber_rows_stay_unverified(role, expected) -> None:
    decision = status("matched_sale_review", role)
    assert decision.status == expected and decision.colour == "amber"


def test_blue_and_red_rows() -> None:
    assert status("property_confirmed_no_sale", "Buyer").status == "unit_linked_unverified"
    assert status("property_confirmed_no_sale", "Buyer").colour == "blue"
    assert status("rejected", "Buyer").status == "conflicting_claim"
    assert status("rejected", "Buyer").colour == "red"


@pytest.mark.parametrize(
    "name",
    [
        "EMIRATES NBD BANK (P.J.S.C.)",
        "Mashreq Bank PSC",
        "ABU DHABI COMMERCIAL BANK",
        "Dubai Islamic Bank",
        "HSBC Middle East Limited",
        "Al Hilal Bank",
        "ADCB",
        "First Abu Dhabi Bank P.J.S.C",
        "FAB",
        "Ajman Bank",
        "Tamweel PJSC",
        "RAKBANK",
        "Commercial Bank of Dubai",
        "Standard Chartered Bank",
        "Amlak Finance",
        "SOME FINANCE COMPANY LLC",
        "Barclays Bank PLC",
        "Citi Bank N.A.",
    ],
)
def test_bank_names_are_lenders(name: str) -> None:
    assert looks_like_a_lender(name)


@pytest.mark.parametrize(
    "name",
    [
        "Zainab Fixture-Owner",
        "Fabian Smith",
        "Citizen Holdings",
        "Bankole Adeyemi",
        "Noor Ahmed",
        "Financial Tower LLC",
        "Ajman Real Estate",
        "Hilal Rashid",
        "",
    ],
)
def test_people_are_not_lenders_the_pattern_is_word_bounded(name: str) -> None:
    assert not looks_like_a_lender(name)


@pytest.mark.parametrize(
    "outcome", ["matched_sale_via_mortgage", "property_confirmed_no_sale", "no_evidence"]
)
def test_a_bank_buyer_on_a_financing_row_is_a_lender_whatever_the_matcher_said(outcome) -> None:
    decision = status(
        outcome, "Buyer", name="Mashreq Bank PSC", procedure_type="Mortgage Registration"
    )
    assert decision.outcome == "lender" and decision.colour == "grey"
    assert decision.status == "unmatched"


def test_a_bank_name_on_a_sale_row_or_as_seller_is_not_a_lender() -> None:
    assert status("matched_sale", "Buyer", name="Mashreq Bank PSC").outcome == "matched_sale"
    assert (
        status(
            "matched_sale_via_mortgage",
            "Seller",
            name="Mashreq Bank PSC",
            procedure_type="Mortgage Registration",
        ).outcome
        == "matched_sale_via_mortgage"
    )


@pytest.mark.parametrize(
    "legacy",
    [
        "unmatched",
        "insufficient_property_data",
        "registry_not_observed",
        "unit_linked_unverified",
        "conflicting_claim",
    ],
)
def test_a_grey_row_keeps_a_legacy_status_that_claims_no_sale(legacy: str) -> None:
    decision = status("no_evidence", "Buyer", legacy_status=legacy, found=True)
    assert decision.status == legacy and decision.keep_legacy and decision.colour == "grey"


@pytest.mark.parametrize(
    "legacy",
    ["verified_current_owner", "probable_current_owner", "former_owner", "unverified_former_owner"],
)
def test_a_grey_row_never_keeps_a_sale_linked_legacy_status(legacy: str) -> None:
    linked = status("no_evidence", "Buyer", legacy_status=legacy, found=True)
    assert linked.status == "unit_linked_unverified" and not linked.keep_legacy
    unlinked = status("no_evidence", "Buyer", legacy_status=legacy, found=False)
    assert unlinked.status == "unmatched"


# --------------------------------------------------------------------------- through _apply_evidence


def contact(**changes) -> ParsedContact:
    values = {
        "source_sheet": "Sheet1",
        "source_row_number": 2,
        "contact_name": "Zainab Fixture-Owner",
        "phone_primary": None,
        "phone_alternate": None,
        "email_primary": None,
        "area_name": "Damac Hills 2",
        "project_name": "Navitas",
        "building_name": "Navitas Tower E",
        "unit_number": "1410",
        "property_type": "Apartment",
        "transaction_date": date(2022, 5, 20),
        "transaction_price_aed": 460000,
        "party_role": "Buyer",
        "procedure_type": "Sell",
        "row_fingerprint": "fp",
    }
    values.update(changes)
    return ParsedContact(**values)


def test_the_stored_match_sets_status_sale_and_evidence_through_apply_evidence() -> None:
    candidate = contact()
    candidate.evidence["owner_match"] = owner_match_evidence(result(), later_sale_date=None)
    _apply_evidence(candidate, sales={}, rentals={})
    assert candidate.ownership_status == "verified_current_owner"
    assert candidate.latest_sale_date == date(2022, 5, 20)
    assert candidate.latest_sale_price_aed == 460000
    assert candidate.evidence["matched_sale_date"] == "2022-05-20"
    match = candidate.evidence["owner_match"]
    assert match["outcome"] == "matched_sale" and match["colour"] == "green"
    assert match["version"] == MATCHER_VERSION
    assert match["sale"]["amount_aed"] == 460000 and match["sale"]["unit"] == "1410"
    assert match["property_key"] == ["navitase", "1410"]


def test_applying_the_match_twice_gives_the_same_result() -> None:
    candidate = contact(party_role="Buyer", contact_name="Mashreq Bank PSC")
    candidate.procedure_type = "Mortgage Registration"
    candidate.evidence["owner_match"] = owner_match_evidence(
        result("matched_sale_via_mortgage"), later_sale_date=None
    )
    _apply_evidence(candidate, sales={}, rentals={})
    first = (candidate.ownership_status, dict(candidate.evidence["owner_match"]))
    _apply_evidence(candidate, sales={}, rentals={})
    assert first == (candidate.ownership_status, candidate.evidence["owner_match"])
    assert first[1]["outcome"] == "lender" and first[0] == "unmatched"
    assert first[1]["matcher_outcome"] == "matched_sale_via_mortgage"


def test_a_later_sale_makes_the_buyer_a_former_owner_with_the_later_date() -> None:
    candidate = contact()
    candidate.evidence["owner_match"] = owner_match_evidence(result(), later_sale_date="2024-02-01")
    _apply_evidence(candidate, sales={}, rentals={})
    assert candidate.ownership_status == "former_owner"
    assert candidate.later_sale_date == date(2024, 2, 1)
    assert "01 Feb 2024" in candidate.match_reason


def test_a_row_without_a_stored_match_keeps_the_legacy_assessment() -> None:
    candidate = contact()
    _apply_evidence(candidate, sales={}, rentals={})
    assert "owner_match" not in candidate.evidence


def test_a_match_from_an_older_matcher_version_is_ignored() -> None:
    candidate = contact()
    stale = owner_match_evidence(result(), later_sale_date=None)
    stale["version"] = "property-first-1"
    candidate.evidence["owner_match"] = stale
    _apply_evidence(candidate, sales={}, rentals={})
    assert candidate.ownership_status != "verified_current_owner"


# --------------------------------------------------------------------------- summary


def row(outcome: str, **source) -> tuple[dict, dict]:
    return (
        {"outcome": outcome, "colour": decide_colour(outcome)},
        {"building_name": "Navitas", **source},
    )


def decide_colour(outcome: str) -> str:
    return status(outcome, "Buyer").colour


def test_the_summary_counts_rows_by_outcome_and_units_by_their_best_row() -> None:
    items = [
        row("matched_sale", unit_number="1410"),
        row("no_evidence", unit_number="1410"),  # the same unit: best row wins
        row("matched_sale_review", unit_number="1411"),
        row("property_confirmed_no_sale", unit_number="1412"),
        row("no_evidence", unit_number="1413"),
        row("rejected", unit_number="1414"),
        row("no_evidence"),  # no identifier
        row("matched_registry_sale_no_unit", unit_number="1410", building_name="Aster"),
    ]
    summary = summarize_owner_matches(items)
    assert summary.version == MATCHER_VERSION
    assert summary.rows == {
        "matched_sale": 1,
        "no_evidence": 3,
        "matched_sale_review": 1,
        "property_confirmed_no_sale": 1,
        "rejected": 1,
        "matched_registry_sale_no_unit": 1,
    }
    assert summary.rows_without_unit == 1
    # units: Navitas 1410 (green), 1411 (amber), 1412 (blue), 1413 (grey), 1414 (red), Aster 1410
    assert summary.units.model_dump() == {
        "total": 6,
        "confirmed": 2,
        "review": 1,
        "property_only": 1,
        "not_matched": 2,
    }


def test_the_same_unit_number_in_two_buildings_is_two_units() -> None:
    summary = summarize_owner_matches(
        [
            row("matched_sale", unit_number="1"),
            row("matched_sale", unit_number="1", building_name="B"),
        ]
    )
    assert summary.units.total == 2


def test_a_summary_of_no_matches_is_empty() -> None:
    assert summarize_owner_matches([]) is None


# --------------------------------------------------------------------------- review reasons, sales


def match(outcome: str, colour: str | None = None, **fields) -> dict:
    return {
        "outcome": outcome,
        "colour": colour or decide_colour(outcome),
        "reasons": [],
        "warnings": [],
        "sale": None,
        "sale_key": "",
        **fields,
    }


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        (
            {"reasons": ["Transactions: 0 sale(s) fit", "unit differs: Transactions says 12"]},
            "unit_differs",
        ),
        ({"warnings": ["sheet_names_two_villas: matched the one"]}, "two_units_named"),
        ({"warnings": ["sheet_names_two_units ['1', '2']: matched 1"]}, "two_units_named"),
        (
            {"reasons": ["sheet_names_two_units ['1', '2']: sale confirmed, unit is not"]},
            "two_units_named",
        ),
        ({"warnings": ["share_qualifier_differs: DXBI sold 12"]}, "share_differs"),
        ({"warnings": ["size_basis_differs"]}, "size_differs"),
        (
            {"reasons": ["elimination_unverified: the sheet names no known building"]},
            "unit_unverified",
        ),
        ({"warnings": ["type_label_differs (Villa vs Flat)"]}, "type_differs"),
        ({"warnings": ["repeat_price"]}, "other"),
        ({}, "other"),
        # the first cause in priority order is the row's one reason
        (
            {
                "reasons": ["unit differs: x"],
                "warnings": [
                    "share_qualifier_differs: y",
                    "size_basis_differs",
                    "type_label_differs (a vs b)",
                ],
            },
            "unit_differs",
        ),
        ({"warnings": ["size_basis_differs", "type_label_differs (a vs b)"]}, "size_differs"),
    ],
)
def test_an_amber_row_has_one_primary_review_reason(fields, reason) -> None:
    assert review_reason(match("matched_sale_review", **fields)) == reason


def test_every_amber_row_is_counted_once_and_only_amber_rows() -> None:
    items = [
        match("matched_sale_review", reasons=["unit differs: x"]),
        match("matched_sale_review", reasons=["unit differs: x"], warnings=["size_basis_differs"]),
        match("matched_sale_review", warnings=["share_qualifier_differs: y", "size_basis_differs"]),
        match("matched_sale_review"),
        match("matched_sale", warnings=["size_basis_differs"]),  # green: a warning, not a review
        match("rejected", reasons=["unit differs: x"]),
    ]
    summary = summarize_owner_matches(
        [(item, {"unit_number": str(n)}) for n, item in enumerate(items)]
    )
    assert summary.review_reasons == {"unit_differs": 2, "share_differs": 1, "other": 1}
    assert sum(summary.review_reasons.values()) == summary.rows["matched_sale_review"] == 4


def sold(source: str, key: str, **fields) -> dict:
    return match(
        "matched_sale",
        sale={
            "source": source,
            "unit": "1",
            "building": "B",
            "date": "2022-01-01",
            "amount_aed": 1,
        },
        sale_key=key,
        **fields,
    )


def test_matched_sales_are_distinct_sales_of_green_rows_split_by_source() -> None:
    items = [
        sold("DXBI", "e1"),
        sold("DXBI", "e1"),  # the seller's row of the same sale
        sold("DXBI", "e2"),
        sold("Transactions Matched", "t1"),
        sold("Transactions Matched", "t1"),
        sold("Transactions Matched", ""),  # no key: told apart by unit, building, date, price
        sold("Transactions Matched", ""),
        {
            **sold("DXBI", "e9"),
            "outcome": "matched_sale_review",
            "colour": "amber",
        },  # not confirmed
        {**sold("DXBI", "e8"), "outcome": "broker", "colour": "grey"},
    ]
    summary = summarize_owner_matches(
        [(item, {"unit_number": str(n)}) for n, item in enumerate(items)]
    )
    assert summary.sales_matched.model_dump() == {"transactions": 2, "registry": 2, "total": 4}


def test_a_summary_without_green_rows_has_no_sales() -> None:
    summary = summarize_owner_matches([(match("no_evidence"), {"unit_number": "1"})])
    assert summary.sales_matched.model_dump() == {"transactions": 0, "registry": 0, "total": 0}
    assert summary.review_reasons == {}


# --------------------------------------------------------------------------- the date rule


def dated(procedure: str, sheet: date, outcome: str = "matched_sale") -> ParsedContact:
    candidate = contact(transaction_date=sheet, procedure_type=procedure)
    candidate.evidence["owner_match"] = owner_match_evidence(result(outcome), later_sale_date=None)
    _apply_evidence(candidate, sales={}, rentals={})
    return candidate


def test_an_ordinary_sale_over_90_days_from_the_sheet_date_goes_to_review() -> None:
    candidate = dated("Sell", date(2022, 9, 17))  # the sale is 2022-05-20: 120 days
    match = candidate.evidence["owner_match"]
    assert match["outcome"] == "matched_sale_review" and match["colour"] == "amber"
    assert match["matcher_outcome"] == "matched_sale"
    assert "date_differs: sheet 2022-09-17, sale 2022-05-20" in match["warnings"]
    assert candidate.ownership_status == "probable_current_owner"
    assert review_reason(match) == "date_differs"


def test_applying_the_date_rule_twice_gives_one_warning() -> None:
    candidate = dated("Sale", date(2022, 9, 17))
    _apply_evidence(candidate, sales={}, rentals={})
    warnings = candidate.evidence["owner_match"]["warnings"]
    assert [w for w in warnings if w.startswith("date_differs")] == [
        "date_differs: sheet 2022-09-17, sale 2022-05-20"
    ]


def test_an_off_plan_completion_two_years_after_the_sale_stays_confirmed() -> None:
    for procedure in ("Complete Delayed Sell", "Delayed Sell", "Sell - Pre registration"):
        candidate = dated(procedure, date(2024, 5, 20))
        assert candidate.evidence["owner_match"]["colour"] == "green", procedure
        assert candidate.ownership_status == "verified_current_owner"


def test_a_sale_30_days_from_the_sheet_date_stays_confirmed() -> None:
    candidate = dated("Sell", date(2022, 6, 19))
    assert candidate.evidence["owner_match"]["colour"] == "green"
    assert not any(
        w.startswith("date_differs") for w in candidate.evidence["owner_match"]["warnings"]
    )
    assert dated("Sell", date(2022, 8, 18)).evidence["owner_match"]["colour"] == "green"  # 90 days


@pytest.mark.parametrize("procedure", ["", "Mortgage Registration", "Grant", "Gift"])
def test_blank_procedures_and_financing_rows_are_left_alone(procedure: str) -> None:
    outcome = "matched_sale_via_mortgage" if procedure.startswith("Mortgage") else "matched_sale"
    assert dated(procedure, date(2025, 1, 1), outcome).evidence["owner_match"]["colour"] == "green"


def test_a_row_without_a_date_is_left_alone() -> None:
    decision = decide(
        "matched_sale",
        party_role="Buyer",
        contact_name="Zainab",
        procedure_type="Sell",
        later_sale_date=None,
        legacy_status="unmatched",
        legacy_property_found=False,
        sheet_date=None,
        sale_date="2022-05-20",
    )
    assert decision.colour == "green"


def test_a_date_review_row_is_in_review_reasons_and_not_in_matched_sales() -> None:
    items = [
        dated("Sell", date(2022, 9, 17)).evidence["owner_match"],
        dated("Sell", date(2022, 5, 20)).evidence["owner_match"],
    ]
    summary = summarize_owner_matches([(m, {"unit_number": str(n)}) for n, m in enumerate(items)])
    assert summary.review_reasons == {"date_differs": 1}
    assert summary.sales_matched.total == 1
