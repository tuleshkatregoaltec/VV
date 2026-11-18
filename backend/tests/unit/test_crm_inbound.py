from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.crm.import_models import CrmPropertyContactClaim
from app.crm.inbound import _ownership_enrichment
from app.crm.inbound_imports import _best_header, _file_rows, _preview_file
from app.crm.inbound_models import CrmInboundEnquiry, InboundEnquiryCreate
from app.crm.inbound_policy import (
    _belongs_in_inbox,
    _deterministic_criteria,
    _lead_priority,
    _normalize_consent,
    _normalize_intent,
    _qualification_complete,
    _redact,
)
from app.crm.matching_policy import (
    _bedroom_fit,
    _budget_fit,
    _listing_budget_band,
    _listing_budget_fit,
    _listing_type_matches,
    _location_fit,
    _property_fit,
    _violates_strict_fields,
)


def _owner_claim(
    *,
    property_key: str,
    status: str,
    phone: str | None = None,
    lease_end: date | None = None,
) -> CrmPropertyContactClaim:
    now = datetime.now(timezone.utc)
    return CrmPropertyContactClaim(
        organization_id="org",
        import_id=1,
        list_id=1,
        source_sheet="Owners",
        source_row_number=1,
        row_fingerprint=f"row-{property_key}",
        owner_key="owner-1",
        property_key=property_key,
        contact_name="Maya Example",
        phone_primary=phone,
        ownership_status=status,
        confidence_score=98,
        match_reason="Registry evidence",
        lease_end=lease_end,
        created_at=now,
        updated_at=now,
    )


def _inbound_enquiry(intent: str) -> CrmInboundEnquiry:
    now = datetime.now(timezone.utc)
    return CrmInboundEnquiry(
        organization_id="org",
        contact_id=1,
        created_by_user_id="user",
        record_kind="opportunity" if intent != "unknown" else "unqualified_contact",
        intent=intent,
        status="new",
        source="Campaign",
        enquiry_date=now,
        created_at=now,
        updated_at=now,
    )


def test_deterministic_extraction_understands_common_campaign_message():
    criteria = _deterministic_criteria(
        {},
        "Looking to buy a 2 bedroom apartment in JBR with a budget up to 3m",
    )

    assert criteria["locations"] == ["JBR"]
    assert criteria["bedrooms_min"] == 2
    assert criteria["bedrooms_max"] == 2
    assert criteria["budget_max_aed"] == 3_000_000
    assert _normalize_intent("", "Looking to buy a 2 bedroom in JBR") == "buy"


@pytest.mark.parametrize(
    ("column", "intent"),
    [
        ("Buy", "buy"),
        ("buying", "buy"),
        (" RENT ", "rent"),
        ("Tenant", "rent"),
        ("Sell", "sell"),
        ("seller.", "sell"),
        ("Let", "let"),
        ("Landlord", "let"),
    ],
)
def test_a_plain_intent_column_is_read(column, intent):
    # Portal and CRM exports put one word in the Intent column; it must not file the lead as
    # an unqualified contact (hidden from Leads).
    assert _normalize_intent(column, "") == intent


def test_a_plain_word_in_free_text_notes_still_does_not_force_intent():
    assert _normalize_intent("", "buy") is None
    assert _normalize_intent("Maybe", "") is None


def test_ambiguous_message_does_not_force_intent():
    assert (
        _normalize_intent(
            "",
            "The form did not ask whether the person wants to buy, sell, rent, or let",
        )
        is None
    )


def test_redaction_removes_contact_identity_before_ai_extraction():
    redacted = _redact(
        "Call Jane Example on +971 50 123 4567 or jane@example.com, Emirates ID 784123456789012",
        ["Jane Example"],
    )

    assert "Jane Example" not in redacted
    assert "jane@example.com" not in redacted
    assert "501234567" not in redacted.replace(" ", "")
    assert "784123456789012" not in redacted
    assert "[REDACTED]" in redacted
    assert "[EMAIL]" in redacted
    assert "[PHONE]" in redacted
    assert "[ID]" in redacted


def test_header_detection_skips_export_title_and_blank_preamble():
    rows = [
        ("Meta campaign export", None, None),
        (None, None, None),
        ("Lead Name", "Mobile Number", "Requirements"),
        ("Maya", "+971501234567", "2 bed JBR"),
    ]

    index, _, mapping = _best_header(rows)

    assert index == 2
    assert mapping == {"full_name": 0, "phone": 1, "notes": 2}


def test_csv_mapping_preserves_source_row_and_header_audit():
    rows, audit = _file_rows(
        b"Campaign leads,,\n\nLead Name,Mobile,Looking For,Requirements\nMaya,0501234567,Buyer,2 bed JBR\n",
        "summer-campaign.csv",
    )

    assert len(rows) == 1
    assert rows[0][1] == 4
    assert rows[0][2]["full_name"] == "Maya"
    assert rows[0][2]["intent"] == "Buyer"
    assert audit["sheets"][0]["header_row"] == 3


def test_match_scoring_distinguishes_exact_flexible_and_outside():
    criteria = {
        "locations": ["JBR"],
        "bedrooms_min": 2,
        "budget_min_aed": 2_500_000,
        "budget_max_aed": 3_000_000,
    }

    assert _location_fit(criteria, "Jumeirah Beach Residence (JBR)")[0] == 20
    assert _bedroom_fit(criteria, "2 Bed")[0] == 10
    assert _budget_fit(criteria, 2_900_000)[0] == 15
    assert _budget_fit(criteria, 3_150_000)[0] == 9
    assert _budget_fit(criteria, 4_000_000)[0] == 0


def test_listing_budget_band_is_thirty_percent_below_and_twenty_percent_above():
    # Agreed on the matching call: a buyer's budget is a band, not just a ceiling.
    assert _listing_budget_band({"budget_max_aed": 3_000_000}) == (2_100_000, 3_600_000)
    assert _listing_budget_band({"budget_min_aed": 2_000_000, "budget_max_aed": 3_000_000}) == (
        1_400_000,
        3_600_000,
    )
    assert _listing_budget_band({}) is None


def test_listing_far_below_or_above_budget_is_disqualified():
    # A 2M villa must never be offered to a 20M buyer just because it is "under budget".
    assert _listing_budget_fit({"budget_max_aed": 20_000_000}, 2_000_000) is None
    criteria = {"budget_max_aed": 3_000_000}
    assert _listing_budget_fit(criteria, 2_000_000) is None
    assert _listing_budget_fit(criteria, 3_700_000) is None
    assert _listing_budget_fit(criteria, 2_200_000) is not None
    assert _listing_budget_fit(criteria, 3_500_000) is not None


def test_listing_budget_points_rank_by_closeness_to_budget():
    # Budget carries 25 points and closer prices rank higher, so listings no longer tie at 85.
    criteria = {"budget_max_aed": 3_000_000}
    on_budget = _listing_budget_fit(criteria, 3_000_000)[0]
    near_below = _listing_budget_fit(criteria, 2_900_000)[0]
    far_below = _listing_budget_fit(criteria, 2_300_000)[0]
    over = _listing_budget_fit(criteria, 3_300_000)[0]
    assert on_budget == 25
    assert on_budget > near_below > far_below
    assert on_budget > over
    assert (
        _listing_budget_fit({"budget_min_aed": 2_500_000, "budget_max_aed": 3_000_000}, 2_700_000)[
            0
        ]
        == 25
    )


def test_listing_with_a_different_property_type_is_disqualified():
    # Someone who asks for a villa should never be shown apartments.
    assert not _listing_type_matches({"property_type": "Villa"}, "Apartment")
    assert not _listing_type_matches({"property_type": "Villa"}, "")
    assert _listing_type_matches({"property_type": "Villa"}, "Villas")
    assert _listing_type_matches({"property_type": "Residential Flats"}, "Apartment")
    assert _listing_type_matches({}, "Apartment")


def _listing(price: int, property_type: str = "Villa", period: str | None = None):
    from app.listings.models import ListingCardResponse

    return ListingCardResponse(
        listing_id=f"L-{price}-{property_type}",
        listing_mode="rent" if period else "sale",
        asset_class="residential",
        title="Listing",
        property_type=property_type,
        price_value=price,
        price_period=period,
        bedrooms="4",
        area_name="Dubai Hills Estate",
    )


def test_listing_lane_drops_wrong_type_and_out_of_band_prices():
    from app.crm.matching import _score_listing

    buyer = {
        "locations": ["Dubai Hills Estate"],
        "property_type": "Villa",
        "bedrooms_min": 4,
        "budget_max_aed": 20_000_000,
    }
    assert _score_listing(buyer, [], "buy", _listing(19_000_000, "Apartment")) is None
    assert _score_listing(buyer, [], "buy", _listing(2_000_000)) is None
    assert _score_listing(buyer, [], "buy", _listing(19_500_000)) is not None


def test_listing_lane_scores_differ_by_price_closeness():
    from app.crm.matching import _score_listing

    buyer = {
        "locations": ["Dubai Hills Estate"],
        "property_type": "Villa",
        "bedrooms_min": 4,
        "budget_max_aed": 10_000_000,
    }
    close = _score_listing(buyer, [], "buy", _listing(9_800_000))[0]
    far = _score_listing(buyer, [], "buy", _listing(7_500_000))[0]
    assert close > far


def test_listing_lane_compares_monthly_rent_as_annual():
    from app.crm.matching import _score_listing

    tenant = {
        "locations": ["Dubai Hills Estate"],
        "property_type": "Villa",
        "budget_max_aed": 600_000,
    }
    assert _score_listing(tenant, [], "rent", _listing(50_000, period="monthly")) is not None
    assert _score_listing(tenant, [], "rent", _listing(90_000, period="monthly")) is None


def test_generic_residential_owner_types_do_not_block_apartment_inventory():
    for imported_type in ("Unit", "Residential", "Residential Flats", "Flat"):
        assert _property_fit({"property_type": imported_type}, "Apartment") == 10


def test_missing_requirements_never_award_match_points():
    assert _location_fit({}, "JBR")[0] == 0
    assert _budget_fit({}, 3_000_000)[0] == 0
    assert _bedroom_fit({}, "2 Bed")[0] == 0


def test_matching_requires_agent_qualified_minimum_brief():
    now = datetime.now(timezone.utc)
    enquiry = CrmInboundEnquiry(
        organization_id="org",
        contact_id=1,
        created_by_user_id="user",
        record_kind="opportunity",
        intent="buy",
        status="qualified",
        source="Manual",
        enquiry_date=now,
        criteria={"locations": ["JBR"], "budget_max_aed": 3_000_000},
        created_at=now,
        updated_at=now,
    )

    assert _qualification_complete(enquiry)
    enquiry.status = "contacted"
    assert not _qualification_complete(enquiry)


def test_qualified_but_untouched_opportunity_remains_in_operational_inbox():
    enquiry = _inbound_enquiry("buy")
    enquiry.status = "qualified"
    enquiry.first_response_due_at = datetime.now(timezone.utc) - timedelta(hours=1)

    assert _belongs_in_inbox(enquiry)

    enquiry.first_contact_at = datetime.now(timezone.utc)
    assert not _belongs_in_inbox(enquiry)

    enquiry.next_follow_up = date.today()
    assert _belongs_in_inbox(enquiry)

    enquiry.status = "won"
    assert not _belongs_in_inbox(enquiry)
    enquiry.status = "qualified"
    enquiry.intent = "unknown"
    assert not _qualification_complete(enquiry)


def test_import_preview_masks_contacts_and_does_not_persist_anything():
    preview = _preview_file(
        b"Lead Name,Mobile,Email,Requirements\nMaya,0501234567,maya@example.com,2 bed JBR\n",
        "real-leads.csv",
    )

    assert preview.total_rows == 1
    assert preview.sheets[0].field_map["phone"] == "Mobile"
    assert preview.sheets[0].sample_rows[0]["phone"] == "Present"
    assert preview.sheets[0].sample_rows[0]["email"] == "Present"


def test_hard_criteria_exclude_matches_while_flexible_fields_only_reduce_score():
    assert _violates_strict_fields(
        ["locations"],
        location_points=0,
        budget_points=15,
        bedroom_points=10,
        property_points=10,
    )
    assert not _violates_strict_fields(
        [],
        location_points=0,
        budget_points=0,
        bedroom_points=0,
        property_points=0,
    )


def test_exact_contact_owner_match_prioritizes_buyer_and_seller_leads():
    enrichment = _ownership_enrichment(
        [
            (
                _owner_claim(
                    property_key="tower-a|101",
                    status="verified_current_owner",
                    phone="971501234567",
                ),
                "phone",
            ),
            (
                _owner_claim(
                    property_key="tower-b|202",
                    status="former_owner",
                    phone="971501234567",
                ),
                "phone",
            ),
        ]
    )

    assert enrichment.verification == "contact_exact"
    assert enrichment.current_owner
    assert enrichment.former_owner
    assert enrichment.multiple_property_owner
    assert enrichment.known_property_count == 2
    assert _lead_priority(_inbound_enquiry("buy"), enrichment).band == "high"
    assert _lead_priority(_inbound_enquiry("sell"), enrichment).band == "high"


def test_rental_owner_signal_is_reported_and_prioritized():
    enrichment = _ownership_enrichment(
        [
            (
                _owner_claim(
                    property_key="tower-a|101",
                    status="probable_current_owner",
                    phone="971501234567",
                    lease_end=date(2026, 10, 1),
                ),
                "phone",
            )
        ]
    )

    assert enrichment.rental_owner
    assert enrichment.rental_property_count == 1
    # Ownership raises the follow-up order, but an unqualified contact is not
    # labelled high priority until the person's intent is known.
    assert _lead_priority(_inbound_enquiry("unknown"), enrichment).band == "medium"


def test_name_only_owner_match_remains_verification_required():
    enrichment = _ownership_enrichment(
        [
            (
                _owner_claim(
                    property_key="tower-a|101",
                    status="former_owner",
                ),
                "name",
            )
        ]
    )

    assert enrichment.verification == "name_only"
    assert enrichment.former_owner
    assert _lead_priority(_inbound_enquiry("sell"), enrichment).band == "medium"
    assert _lead_priority(_inbound_enquiry("unknown"), enrichment).band == "medium"


def test_unmatched_contact_keeps_standard_priority():
    enrichment = _ownership_enrichment([])

    priority = _lead_priority(_inbound_enquiry("buy"), enrichment)

    assert not enrichment.matched
    assert priority.band == "standard"


def test_priority_blends_ticket_size_with_verified_ownership():
    enrichment = _ownership_enrichment(
        [
            (
                _owner_claim(
                    property_key="tower-a|101",
                    status="verified_current_owner",
                    phone="971501234567",
                ),
                "phone",
            ),
            (
                _owner_claim(
                    property_key="tower-b|202",
                    status="former_owner",
                    phone="971501234567",
                ),
                "phone",
            ),
        ]
    )
    smaller = _inbound_enquiry("buy")
    smaller.criteria = {"budget_max_aed": 2_000_000}
    larger = _inbound_enquiry("buy")
    larger.criteria = {"budget_max_aed": 12_000_000}

    smaller_priority = _lead_priority(smaller, enrichment)
    larger_priority = _lead_priority(larger, enrichment)

    assert larger_priority.score > smaller_priority.score
    assert larger_priority.opportunity_value_aed == 12_000_000
    assert larger_priority.band == "high"


def test_name_only_match_is_never_presented_as_high_priority():
    enrichment = _ownership_enrichment(
        [(_owner_claim(property_key="tower-a|101", status="verified_current_owner"), "name")]
    )
    enquiry = _inbound_enquiry("buy")
    enquiry.criteria = {"budget_max_aed": 50_000_000}

    priority = _lead_priority(enquiry, enrichment)

    assert priority.band == "medium"
    assert "verify identity" in " ".join(priority.reasons).lower()


def test_new_lead_requires_only_a_name():
    # The New Lead form asks for name and phone, but the API itself only insists on a name;
    # everything else in the brief is optional so an agent can save a lead mid-call.
    with pytest.raises(ValidationError):
        InboundEnquiryCreate(intent="buy", record_kind="opportunity")
    with pytest.raises(ValidationError):
        InboundEnquiryCreate(full_name="", intent="buy", record_kind="opportunity")

    lead = InboundEnquiryCreate(full_name="Test Lead", intent="buy", record_kind="opportunity")

    assert lead.phone is None
    assert lead.criteria == {}
    assert lead.source == "Manual"


def test_new_lead_criteria_keep_every_lead_type_field():
    # Seller, tenant and landlord fields have no dedicated columns; they must survive in the
    # free-form criteria rather than be silently discarded by validation.
    criteria = {
        "unit": "Marina Heights #3301",
        "expected_rent_aed": 120000,
        "available": "January",
        "furnishing": "Furnished",
        "cheques": "4",
        "move_in": "December",
        "occupancy": "Vacant",
        "mortgage": "None",
        "locations": ["JVC"],
    }

    lead = InboundEnquiryCreate(
        full_name="Test Lead", intent="let", record_kind="opportunity", criteria=criteria
    )

    assert lead.criteria == criteria


@pytest.mark.parametrize(
    ("intent", "criteria"),
    [
        ("buy", {"locations": ["JVC"], "budget_max_aed": 1500000}),
        ("rent", {"locations": ["JVC"], "budget_max_aed": 65000}),
        ("sell", {"building": "Bloom Towers A", "unit_number": "1204"}),
        ("let", {"building": "Marina Heights", "unit_number": "3301"}),
    ],
)
def test_new_lead_form_required_fields_are_enough_to_qualify(intent, criteria):
    # The New Lead form's required fields are exactly what matching needs, so a qualified lead
    # created from it can be matched; a free-text seller "unit" never could be.
    enquiry = _inbound_enquiry(intent)
    enquiry.criteria = criteria
    enquiry.status = "qualified"

    assert _qualification_complete(enquiry)

    if intent in {"sell", "let"}:
        enquiry.criteria = {"unit": f"{criteria['building']} #{criteria['unit_number']}"}
        assert not _qualification_complete(enquiry)


def _stored_match(
    state: str, generated_at: datetime, updated_at: datetime, version: str | None = None
):
    from app.crm.inbound_models import CrmInboundMatch
    from app.crm.matching import _ALGORITHM_VERSION

    return CrmInboundMatch(
        algorithm_version=version or _ALGORITHM_VERSION,
        enquiry_id=1,
        organization_id="org",
        target_type="listing",
        target_key=f"{state}-{generated_at.isoformat()}",
        score=85,
        title="Listing",
        subtitle="",
        state=state,
        generated_at=generated_at,
        updated_at=updated_at,
    )


def test_matches_rerun_when_the_brief_changed_after_the_last_run():
    # A budget change marks suggested matches stale but keeps saved ones; the next load must
    # re-run matching instead of showing the old list because a saved match still exists.
    from app.crm.matching import _needs_refresh

    run = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
    edit = run + timedelta(minutes=5)
    saved = _stored_match("saved", run, run)
    assert _needs_refresh([])
    assert not _needs_refresh([saved, _stored_match("suggested", run, run)])
    assert _needs_refresh([saved, _stored_match("stale", run, edit)])
    assert not _needs_refresh(
        [
            _stored_match("suggested", edit + timedelta(seconds=1), edit),
            _stored_match("stale", run, edit),
        ]
    )


def test_matches_scored_by_an_older_algorithm_rerun_on_next_load():
    # After a scoring change, leads must not keep showing results scored by the old rules
    # (a 15m listing for a 19m buyer still reading "Within stated budget").
    from app.crm.matching import _ALGORITHM_VERSION, _needs_refresh

    run = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
    assert _ALGORITHM_VERSION != "inbound-v1"
    assert _needs_refresh([_stored_match("suggested", run, run, version="inbound-v1")])
    assert not _needs_refresh([_stored_match("suggested", run, run)])


def test_listing_details_show_the_property_type():
    # Agents check the type at a glance (Villa vs Apartment) without opening the listing.
    from app.crm.matching import _listing_subtitle

    listing = _listing(2_490_000, "Apartment")
    listing.tower_name = "Cayan Tower"
    assert _listing_subtitle(listing) == "Cayan Tower · Apartment · AED 2,490,000"
    listing.property_type = None
    assert _listing_subtitle(listing) == "Cayan Tower · AED 2,490,000"


def test_a_price_just_under_budget_never_reads_zero_percent():
    criteria = {"budget_max_aed": 2_500_000}
    assert _listing_budget_fit(criteria, 2_490_000)[1] == "Within 1% of budget"
    assert _listing_budget_fit(criteria, 2_470_000)[1] == "1% below budget"
    assert _listing_budget_fit(criteria, 2_510_000)[1] == "Within 1% of budget"


def test_listing_search_uses_the_portal_type_name_as_chosen():
    # The Wants dropdown offers the portal's own type names; the listing search matches them
    # exactly, so a chosen name must reach it unchanged. Imported synonyms still map to Apartment.
    from app.crm.matching_policy import _listing_property_type

    assert _listing_property_type("Co-working space") == "Co-working space"
    assert _listing_property_type("Hotel & Hotel Apartment") == "Hotel & Hotel Apartment"
    assert _listing_property_type("Residential Flats") == "Apartment"
    assert _listing_property_type("Villas") == "Villa"
    assert _listing_property_type("") is None


def test_listing_search_asks_for_the_bedroom_values_listings_use():
    # Listings record studios as "studio" and large homes as "7" or "7+"; a studio buyer saved
    # as 0 was searched as "0" and never saw a listing.
    from app.crm.matching_policy import _listing_bedrooms

    assert _listing_bedrooms({"bedrooms_min": 0, "bedrooms_max": 0}) == ["studio"]
    assert _listing_bedrooms({"bedrooms_min": 2, "bedrooms_max": 2}) == ["2"]
    assert _listing_bedrooms({"bedrooms_min": 7}) == ["7", "7+"]
    assert _listing_bedrooms({}) is None


def test_units_on_record_use_the_budget_band():
    # A 20,000 budget still showed 40 "Near fit" units: unknown or far-off prices were not
    # held to the budget. Units now follow the same band as portal listings.
    from app.crm.matching import _score_unit

    buyer = {
        "locations": ["Dubai Marina"],
        "property_type": "Apartment",
        "bedrooms_min": 2,
        "budget_max_aed": 2_500_000,
    }
    unit = dict(bedrooms="2 Bed", property_type="Apartment", places=("Dubai Marina", "", ""))
    assert _score_unit(buyer, [], price=1_000_000, fixed=27, **unit) is None
    assert _score_unit(buyer, [], price=3_200_000, fixed=27, **unit) is None
    on_budget = _score_unit(buyer, [], price=2_500_000, fixed=27, **unit)
    lower = _score_unit(buyer, [], price=1_900_000, fixed=27, **unit)
    assert on_budget[1][1] == "Within stated budget"
    assert on_budget[0] > lower[0]


def test_a_unit_with_no_price_is_shown_only_for_review():
    # It cannot be checked against the budget, so it is never Near or Exact: the agent verifies it.
    from app.crm.matching import _score_unit

    buyer = {
        "locations": ["Dubai Marina"],
        "property_type": "Apartment",
        "bedrooms_min": 2,
        "budget_max_aed": 2_500_000,
    }
    score, reasons, _ = _score_unit(
        buyer,
        [],
        price=None,
        fixed=27,
        bedrooms="2 Bed",
        property_type="Apartment",
        places=("Dubai Marina", "", ""),
    )
    assert 50 <= score < 65
    assert "Price unknown, verify" in reasons


def _company_listing(
    price: int, property_type: str = "Apartment", bedrooms: int | None = 2, mode="sale"
):
    from app.crm.models import CrmCompanyListing

    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    return CrmCompanyListing(
        organization_id="org",
        reference=f"SYN-{price}",
        agent_name="Sara Ali",
        agent_phone="+971500000001",
        mode=mode,
        title="Marina Gate 2 · Unit 1504",
        property_type=property_type,
        bedrooms=bedrooms,
        price_aed=price,
        area_name="Dubai Marina",
        building_name="Marina Gate 2",
        unit_number="1504",
        listed_at=now - timedelta(days=12),
        created_at=now,
        updated_at=now,
    )


def test_company_listings_follow_the_portal_listing_rules():
    # Company listings are matched first, with the same type, bedroom and budget-band rules.
    from app.crm.matching import _score_company_listing

    buyer = {
        "locations": ["Dubai Marina"],
        "property_type": "Apartment",
        "bedrooms_min": 2,
        "bedrooms_max": 2,
        "budget_max_aed": 2_500_000,
    }
    assert _score_company_listing(buyer, [], "buy", _company_listing(2_450_000, "Villa")) is None
    assert _score_company_listing(buyer, [], "buy", _company_listing(1_000_000)) is None
    close = _score_company_listing(buyer, [], "buy", _company_listing(2_450_000))
    far = _score_company_listing(buyer, [], "buy", _company_listing(1_900_000))
    assert close[0] > far[0]
    assert close[0] >= 85


def test_a_company_listing_names_the_agent_who_holds_it():
    # The agent asks the colleague with the mandate, so the card says who that is.
    from app.crm.matching import _score_company_listing

    buyer = {
        "locations": ["Dubai Marina"],
        "property_type": "Apartment",
        "budget_max_aed": 2_500_000,
    }
    reasons = _score_company_listing(buyer, [], "buy", _company_listing(2_500_000))[1]
    assert "Listed by Sara Ali · +971500000001" in reasons
    assert not any("availability requires confirmation" in r for r in reasons)


def test_company_rents_are_yearly_and_studios_match_studio_tenants():
    from app.crm.matching import _score_company_listing

    tenant = {
        "locations": ["Dubai Marina"],
        "property_type": "Apartment",
        "bedrooms_min": 0,
        "bedrooms_max": 0,
        "budget_max_aed": 80_000,
    }
    studio = _company_listing(80_000, bedrooms=0, mode="rent")
    scored = _score_company_listing(tenant, [], "rent", studio)
    assert scored is not None
    assert "Exact bedroom match" in scored[1]


def test_company_listings_need_the_requested_bedrooms_like_portal_listings():
    # Portal listings are searched with the exact bedroom count; company listings must not let
    # a 1-bed through for a 4-bed buyer just because it scores fewer points.
    from app.crm.matching import _score_company_listing

    buyer = {
        "locations": ["Dubai Marina"],
        "property_type": "Apartment",
        "bedrooms_min": 4,
        "bedrooms_max": 4,
        "budget_max_aed": 2_500_000,
    }
    assert _score_company_listing(buyer, [], "buy", _company_listing(2_450_000, bedrooms=1)) is None
    assert _score_company_listing(buyer, [], "buy", _company_listing(2_450_000, bedrooms=4))
    any_size = {**buyer, "bedrooms_min": None, "bedrooms_max": None}
    assert _score_company_listing(any_size, [], "buy", _company_listing(2_450_000, bedrooms=1))


def test_pocket_listings_are_matched_and_marked_off_market():
    # A pocket listing is not advertised; it is the agency's exclusive stock, so it is matched and
    # the card says so, letting the agent pitch it as off-market.
    from app.crm.matching import _score_company_listing

    buyer = {
        "locations": ["Dubai Marina"],
        "property_type": "Apartment",
        "budget_max_aed": 2_500_000,
    }
    pocket = _company_listing(2_500_000)
    pocket.status = "pocket"
    reasons = _score_company_listing(buyer, [], "buy", pocket)[1]
    assert "Off-market (pocket listing)" in reasons
    live = _score_company_listing(buyer, [], "buy", _company_listing(2_500_000))[1]
    assert "Off-market (pocket listing)" not in live


def test_imported_consent_counts_only_a_clear_yes():
    """WhatsApp promotions go only to leads with consent "provided"; a spreadsheet's "Yes" must
    count, and anything unclear must never be read as agreement."""
    for yes in ("Yes", "Y", "TRUE", "1", "Opt-in", "agreed", "provided"):
        assert _normalize_consent(yes) == "provided", yes
    for no in ("No", "false", "0", "Opted out", "withdrawn", "Unsubscribed"):
        assert _normalize_consent(no) == "withdrawn", no
    for unclear in ("maybe", "ask later", "", None, "yes?no"):
        assert _normalize_consent(unclear) == "unknown", unclear
