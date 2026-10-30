from datetime import date

import pytest

from app.crm.import_events import IMPORT_RESOLVER_VERSION
from app.crm.owner_history import _property_identity, project_owner_history


def _event(number=1, **changes):
    row = dict(
        id=number,
        owner_key="owner",
        property_key="aspecttower|602",
        import_id=number,
        area_name="Business Bay",
        project_name="Executive Towers",
        building_name="Aspect Tower",
        unit_number="602",
        party_role="Buyer",
        procedure_type="Sell",
        event_family="sale",
        ownership_status="verified_current_owner",
        confidence_score=98,
        match_reason="Exact sale",
        transaction_date=date(2020, 1, 1),
        latest_sale_date=date(2020, 1, 1),
        later_sale_date=None,
        claim_resolver_version=IMPORT_RESOLVER_VERSION,
        import_resolver_version=None,
    )
    return {**row, **changes}


def test_source_events_are_not_properties_and_later_import_disposal_is_current():
    original = _event()
    repeated = _event(2)
    disposal = _event(
        3,
        party_role="Seller",
        transaction_date=date(2024, 1, 1),
        ownership_status="former_owner",
        confidence_score=80,
        later_sale_date=date(2024, 1, 1),
    )
    summary, statuses = project_owner_history([original, repeated], [original, repeated, disposal])
    assert summary.source_event_count == 2
    assert summary.identifiable_property_count == summary.owner_property_count == 1
    assert summary.former_count == 1
    assert summary.verified_current_count == 0
    assert next(iter(statuses.values()))[0] == "former_owner"


@pytest.mark.parametrize(
    "key,unit",
    [
        ("", "602"),
        ("source:abc", "602"),
        ("|602", "602"),
        ("null|602", "602"),
        ("aspecttower|null", "null"),
        ("aspecttower|unknown", "unknown"),
        ("property", "602"),
        ("aspecttower|602", ""),
        ("aspecttower|602", "603"),
    ],
)
def test_invalid_identity_never_becomes_a_holding_despite_observed_verified_label(key, unit):
    row = _event(property_key=key, unit_number=unit)
    summary, statuses = project_owner_history([row], [row])
    assert summary.source_event_count == summary.invalid_identity_source_count == 1
    assert summary.owner_property_count == summary.identifiable_property_count == 0
    assert summary.verified_current_count == 0
    assert statuses == {}


def test_cadastral_identity_requires_the_exact_resolved_plot_key():
    row = _event(property_key="dld-land:1:12:0", unit_number="", cadastral_key="dld-land:1:12:0")
    assert _property_identity(row) == ("land", "dld-land:1:12:0")
    assert _property_identity({**row, "cadastral_key": None}) is None


def test_legacy_coverage_uses_import_version_when_claim_version_is_missing():
    rows = [
        _event(1, claim_resolver_version=None, import_resolver_version=IMPORT_RESOLVER_VERSION),
        _event(2, claim_resolver_version=None),
        _event(3, claim_resolver_version="owner-context-8"),
    ]
    summary, _ = project_owner_history(rows, rows)
    assert summary.legacy_source_event_count == 2
    assert summary.resolver_versions == {
        IMPORT_RESOLVER_VERSION: 1,
        "legacy": 1,
        "owner-context-8": 1,
    }


def test_later_other_owner_sale_prevents_old_confident_buyer_from_remaining_current():
    old = _event()
    new = _event(
        2,
        owner_key="other-owner",
        transaction_date=date(2024, 1, 1),
        latest_sale_date=date(2024, 1, 1),
        confidence_score=80,
        ownership_status="probable_current_owner",
    )
    summary, statuses = project_owner_history([old], [old, new])
    assert summary.former_count == 1
    assert (
        statuses[("other-owner", ("businessbay", "aspecttower|602"))][0] == "probable_current_owner"
    )


def test_same_day_buyers_and_same_owner_acquisition_disposal_require_review():
    buyer = _event()
    another = _event(2, owner_key="different-contact", confidence_score=60)
    summary, statuses = project_owner_history([buyer, another], [buyer, another])
    assert summary.unresolved_count == 2
    assert summary.owner_property_count == 2
    assert summary.identifiable_property_count == 1
    assert {status for status, _ in statuses.values()} == {"conflicting_claim"}
    seller = _event(
        3, ownership_status="former_owner", party_role="Seller", later_sale_date=date(2020, 1, 1)
    )
    summary, _ = project_owner_history([buyer, seller], [buyer, seller])
    assert summary.unresolved_count == 1


def test_reacquisition_after_disposal_recovers_current_evidence():
    sold = _event(1, ownership_status="former_owner", later_sale_date=date(2022, 1, 1))
    reacquired = _event(2, transaction_date=date(2024, 1, 1), latest_sale_date=date(2024, 1, 1))
    summary, _ = project_owner_history([sold, reacquired], [sold, reacquired])
    assert summary.verified_current_count == 1
    assert summary.former_count == 0


def test_old_buyer_cannot_use_distant_latest_sale_as_a_new_acquisition():
    row = _event(latest_sale_date=date(2024, 1, 1))
    summary, _ = project_owner_history([row], [row])
    assert summary.former_count == 1
    assert summary.verified_current_count == 0


def test_near_registration_date_offset_does_not_invent_a_later_disposal():
    row = _event(latest_sale_date=date(2020, 1, 2), ownership_status="probable_current_owner")
    summary, _ = project_owner_history([row], [row])
    assert summary.probable_current_count == 1
    assert summary.former_count == 0


def test_incompatible_projects_cannot_demote_or_confirm_each_others_owner():
    old = _event()
    other = _event(
        2,
        project_name="Different Project",
        owner_key="another-owner",
        transaction_date=date(2024, 1, 1),
        latest_sale_date=date(2024, 1, 1),
    )
    summary, _ = project_owner_history([old, other], [old, other])
    assert summary.unresolved_count == 2
    assert summary.former_count == summary.verified_current_count == 0


def test_legacy_financing_label_does_not_establish_a_sale_acquisition():
    row = _event(event_family="financing", procedure_type="Mortgage")
    summary, _ = project_owner_history([row], [row])
    assert summary.unresolved_count == 1
    assert summary.verified_current_count == 0


def test_changed_contact_key_disposal_cannot_leave_old_buyer_current():
    old = _event()
    seller = _event(
        2,
        owner_key="changed-phone-key",
        party_role="Seller",
        ownership_status="former_owner",
        transaction_date=date(2024, 1, 1),
        later_sale_date=date(2024, 1, 1),
        latest_sale_date=None,
    )
    summary, statuses = project_owner_history([old], [old, seller])
    assert summary.unresolved_count == 1
    assert summary.verified_current_count == summary.former_count == 0
    assert statuses[("owner", ("businessbay", "aspecttower|602"))][0] == "conflicting_claim"


def test_financing_seller_former_label_is_not_a_disposal():
    buyer = _event()
    financing = _event(
        2,
        party_role="Seller",
        procedure_type="Mortgage",
        event_family="financing",
        ownership_status="former_owner",
        transaction_date=date(2024, 1, 1),
        latest_sale_date=None,
        later_sale_date=date(2024, 1, 1),
    )
    summary, _ = project_owner_history([buyer, financing], [buyer, financing])
    assert summary.verified_current_count == 1
    assert summary.former_count == 0


def test_area_scopes_and_owner_keys_are_not_merged_by_display_name():
    rows = [_event(), _event(2, area_name="Dubai Marina", owner_key="other-contact")]
    summary, _ = project_owner_history(rows, rows)
    assert summary.identifiable_property_count == summary.owner_property_count == 2
    assert summary.verified_current_count == 2


def test_legacy_aliases_of_the_exact_party_keep_events_but_share_one_association():
    rows = [
        _event(
            1, owner_key="old-stored-key", contact_name="Alex Example", phone_primary="050 123 4567"
        ),
        _event(
            2,
            owner_key="new-stored-key",
            contact_name="ALEX  EXAMPLE",
            phone_primary="+971501234567",
        ),
    ]
    summary, _ = project_owner_history(rows, rows)
    assert summary.source_event_count == 2
    assert summary.owner_property_count == summary.verified_current_count == 1
    assert summary.unresolved_count == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"contact_name": "Another Person"},
        {"phone_primary": "+971509999999"},
    ],
)
def test_same_phone_different_name_and_same_name_different_phone_stay_separate(changes):
    original = _event(1, contact_name="Alex Example", phone_primary="+971501234567")
    other = {**original, "id": 2, "owner_key": "different-key", **changes}
    summary, _ = project_owner_history([original, other], [original, other])
    assert summary.owner_property_count == 2
    assert summary.unresolved_count == 2


def test_contactless_alias_requires_the_same_valid_scoped_property():
    first = _event(1, owner_key="legacy", contact_name="Alex Example", phone_primary="N/A")
    same = _event(2, owner_key="new", contact_name="Alex Example")
    different = _event(
        3,
        owner_key="another",
        contact_name="Alex Example",
        property_key="aspecttower|603",
        unit_number="603",
    )
    summary, _ = project_owner_history([first, same, different], [first, same, different])
    assert summary.source_event_count == 3
    assert summary.owner_property_count == summary.identifiable_property_count == 2


def test_placeholder_name_never_creates_an_alias_even_with_contact():
    rows = [
        _event(1, owner_key="legacy", contact_name="N/A", phone_primary="+971501234567"),
        _event(2, owner_key="new", contact_name="N/A", phone_primary="+971501234567"),
    ]
    summary, _ = project_owner_history(rows, rows)
    assert summary.owner_property_count == 2
