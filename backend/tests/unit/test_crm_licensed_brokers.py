"""Licensed brokers are not owners: the two rules, their evidence and what they change."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.crm import owner_match_stage as stage
from app.crm.brokers import (
    BROKER_SIGNAL,
    BrokerIndex,
    annotate_broker_contacts,
    broker_contact_evidence,
    broker_phone,
    broker_row,
)
from app.crm.identity import ParsedContact, _identity_text, usable_channels
from app.crm.owner_match_status import decide, owner_match_evidence, summarize_owner_matches
from app.crm.owner_matcher import MatchResult, SalesIndex
from app.crm.owner_places import PlaceIndex
from app.crm.owner_signals import build_owner_signals
from app.crm.ownership import _apply_evidence

BROKER = "Mohanad Nagi Elwadia"
PHONE = "0504264267"
EMAIL = "Broker@Example.com"


def index(*records: dict) -> BrokerIndex:
    result = BrokerIndex()
    for record in records:
        row = broker_row(record)
        assert row is not None
        result.add(row["broker_number"], row["name_key"], row["phones"], row["emails"])
    return result


BROKERS = index(
    {
        "broker_number": "689",
        "name_en": BROKER,
        "phone": "971|50-4264267",
        "mobile": "",
        "email": EMAIL,
        "card_expiry_date": "2019-10-25T00:00:00",  # expired cards still count
    },
    {"broker_number": "7", "name_en": "Another Broker", "mobile": "971567995941"},
)


def contact(**changes) -> ParsedContact:
    values = {
        "source_sheet": "Sheet1",
        "source_row_number": 2,
        "contact_name": BROKER,
        "phone_primary": PHONE,
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


def matched(candidate: ParsedContact, brokers: BrokerIndex | None) -> ParsedContact:
    """The row after the stage's broker marks and the stored verdict (matched_sale) are applied."""
    if brokers is not None:
        annotate_broker_contacts([candidate], brokers)
    result = MatchResult("matched_sale", ("navitase", "1410"), SALE, ["unit 1410"])
    candidate.evidence["owner_match"] = owner_match_evidence(result, later_sale_date=None)
    _apply_evidence(candidate, sales={}, rentals={})
    return candidate


# --------------------------------------------------------------------------- normalization


@pytest.mark.parametrize(
    "written", ["971|50-4264267", "0504264267", "971504264267", "+971 50 426 4267", "50-4264267"]
)
def test_a_broker_phone_is_normalized_like_a_sheet_phone(written: str) -> None:
    assert broker_phone(written) == broker_phone("0504264267") == "+971504264267"


def test_a_broker_record_becomes_a_table_row() -> None:
    row = broker_row(
        {
            "broker_number": "689",
            "name_en": "Mohanad  Nagi-Elwadia",
            "phone": "971|",
            "mobile": "971|50-4264267",
            "email": " Broker@Example.com ",
            "card_expiry_date": "2027-10-25T00:00:00",
        }
    )
    assert row is not None
    assert row["name_key"] == _identity_text("Mohanad Nagi Elwadia") == "mohanadnagielwadia"
    assert row["phones"] == ["+971504264267"] and row["emails"] == ["broker@example.com"]
    assert row["card_expiry_date"] == date(2027, 10, 25)
    assert broker_row({"broker_number": "", "name_en": "x"}) is None


# --------------------------------------------------------------------------- rule 1: the broker


def test_a_name_and_phone_of_the_same_broker_is_a_broker_not_an_owner() -> None:
    candidate = matched(contact(), BROKERS)
    match = candidate.evidence["owner_match"]
    assert match["outcome"] == "broker" and match["colour"] == "grey"
    assert match["matcher_outcome"] == "matched_sale"  # what the matcher saw is kept
    assert candidate.ownership_status == "unmatched" and candidate.confidence_score == 10
    assert candidate.match_reason == "Licensed broker, not an owner."
    assert "matched_sale_date" not in candidate.evidence
    assert candidate.latest_sale_date is None  # no sale is credited to a broker
    assert candidate.evidence["broker_contact"]["is_broker"] is True
    assert not candidate.has_valid_contact


def test_a_name_and_email_of_the_same_broker_is_a_broker() -> None:
    candidate = matched(contact(phone_primary=None, email_primary="BROKER@example.com"), BROKERS)
    assert candidate.evidence["owner_match"]["outcome"] == "broker"


def test_the_alternate_phone_counts_and_an_expired_card_still_counts() -> None:
    candidate = matched(
        contact(phone_primary="0501111111", phone_alternate="971|50-4264267"), BROKERS
    )
    assert candidate.evidence["owner_match"]["outcome"] == "broker"


def test_a_broker_beats_whatever_the_matcher_said_and_applying_twice_changes_nothing() -> None:
    candidate = matched(contact(), BROKERS)
    first = (candidate.ownership_status, dict(candidate.evidence["owner_match"]))
    _apply_evidence(candidate, sales={}, rentals={})
    assert first == (candidate.ownership_status, candidate.evidence["owner_match"])
    for outcome in ("rejected", "no_evidence", "property_confirmed_no_sale", "matched_sale_review"):
        decision = decide(
            outcome,
            party_role="Buyer",
            contact_name=BROKER,
            procedure_type="Sell",
            later_sale_date=None,
            legacy_status="unmatched",
            legacy_property_found=False,
            is_broker=True,
        )
        assert (decision.outcome, decision.colour, decision.status) == (
            "broker",
            "grey",
            "unmatched",
        )


def test_a_broker_row_is_counted_as_broker_and_kept_out_of_the_unit_tiers() -> None:
    broker = matched(contact(), BROKERS).evidence["owner_match"]
    owner = matched(
        contact(contact_name="Zainab Fixture-Owner", phone_primary="0509999999"), BROKERS
    )
    summary = summarize_owner_matches(
        [
            (broker, {"building_name": "Navitas", "unit_number": "1410"}),
            (owner.evidence["owner_match"], {"building_name": "Navitas", "unit_number": "1410"}),
            (broker, {"building_name": "Navitas", "unit_number": "1411"}),  # only a broker's row
        ]
    )
    assert summary is not None
    assert summary.rows == {"broker": 2, "matched_sale": 1}
    # unit 1410 is confirmed by the owner's row; unit 1411 has only the broker's: not matched
    assert summary.units.model_dump() == {
        "total": 2,
        "confirmed": 1,
        "review": 0,
        "property_only": 0,
        "not_matched": 1,
    }
    assert summary.sales_matched.total == 1  # the broker's row ties no sale


# --------------------------------------------------------------------------- rule 2: a broker's number


def test_a_brokers_phone_under_another_name_leaves_the_owner_an_owner_without_that_contact() -> (
    None
):
    candidate = matched(contact(contact_name="Zainab Fixture-Owner"), BROKERS)
    assert candidate.evidence["owner_match"]["outcome"] == "matched_sale"
    assert candidate.ownership_status == "verified_current_owner"
    assert candidate.evidence["broker_contact"] == {
        "is_broker": False,
        "phones": ["+971504264267"],
        "emails": [],
        "usable_contact": False,
    }
    assert not candidate.has_valid_contact  # so no contact-ready count, no workspace


def test_the_owners_own_second_number_still_makes_the_row_contact_ready() -> None:
    candidate = matched(
        contact(contact_name="Zainab Fixture-Owner", phone_alternate="0509999999"), BROKERS
    )
    assert candidate.evidence["broker_contact"]["usable_contact"] is True
    assert candidate.has_valid_contact
    assert usable_channels(PHONE, "0509999999", None, candidate.evidence["broker_contact"]) == (
        ["+971509999999"],
        [],
    )


def test_the_owner_profile_carries_the_broker_signal_and_no_broker_phone() -> None:
    def row(phone: str | None, mark) -> dict:
        return {
            "canonical_owner_key": "o1",
            "contact_name": "Zainab Fixture-Owner",
            "party_role": "Buyer",
            "phone_primary": phone,
            "property_identity": ("navitase", "1410"),
            "broker_contact": mark,
        }

    mark = broker_contact_evidence("Zainab Fixture-Owner", PHONE, None, None, BROKERS)
    (profile,) = build_owner_signals([row(PHONE, mark)]).values()
    assert BROKER_SIGNAL in profile["role_signals"]
    (plain,) = build_owner_signals([row("0509999999", None)]).values()
    assert BROKER_SIGNAL not in plain["role_signals"]


def test_a_broker_phone_shared_by_many_owners_is_not_their_shared_phone() -> None:
    rows = [
        {
            "canonical_owner_key": f"o{i}",
            "contact_name": f"Owner Number{'x' * i}",
            "phone_primary": PHONE,
            "property_identity": ("b", str(i)),
            "broker_contact": broker_contact_evidence(f"Owner{i}", PHONE, None, None, BROKERS),
        }
        for i in range(6)
    ]
    signals = build_owner_signals(rows)
    assert all(s["relationship_role"] == "unknown" for s in signals.values())


# --------------------------------------------------------------------------- rule 3 and no table


def test_a_name_alone_is_not_evidence() -> None:
    candidate = matched(contact(phone_primary="0509999999"), BROKERS)
    assert candidate.evidence["owner_match"]["outcome"] == "matched_sale"
    assert "broker_contact" not in candidate.evidence
    assert candidate.has_valid_contact


def test_an_empty_broker_table_changes_nothing() -> None:
    candidate = matched(contact(), BrokerIndex())
    assert candidate.evidence["owner_match"]["outcome"] == "matched_sale"
    assert "broker_contact" not in candidate.evidence and candidate.has_valid_contact


def test_a_phone_of_one_broker_with_the_name_of_another_is_not_a_broker_row() -> None:
    candidate = matched(contact(contact_name="Another Broker"), BROKERS)  # PHONE is broker 689's
    assert candidate.evidence["owner_match"]["outcome"] == "matched_sale"
    assert candidate.evidence["broker_contact"]["is_broker"] is False


def test_the_marks_are_cleared_when_the_index_no_longer_has_the_broker() -> None:
    candidate = matched(contact(), BROKERS)
    annotate_broker_contacts([candidate], BrokerIndex())
    assert "broker_contact" not in candidate.evidence


async def test_the_stage_marks_rows_when_given_an_index_and_leaves_them_otherwise(
    monkeypatch,
) -> None:
    index = SalesIndex([], PlaceIndex([], {}, {}), [])
    monkeypatch.setattr(stage, "load_sales_index", AsyncMock(return_value=index))
    fresh, stored = contact(), contact()
    stored.evidence["broker_contact"] = {"is_broker": True, "phones": ["x"], "emails": []}
    await stage.run_owner_matching([fresh], BROKERS)
    assert fresh.evidence["broker_contact"]["is_broker"] is True
    await stage.run_owner_matching([stored])  # no index: the stored marks stay
    assert stored.evidence["broker_contact"]["phones"] == ["x"]
    await stage.run_owner_matching([stored], BrokerIndex())  # an empty table: no rule applies
    assert "broker_contact" not in stored.evidence
