"""Every owner surface consumes the assessed identity, never a saved green label."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.crm import owners, renewal_leads, workspaces
from app.crm.import_models import CrmOwnerHistorySummary, CrmOwnerNote, CrmOwnerWorkspace
from app.crm.models import CrmLeadWorkspace
from app.crm.owner_assessment import OwnerAssessmentSnapshot

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)


def event(id=1, **changes):
    row = dict(
        id=id,
        owner_key=f"alias-{id}",
        canonical_owner_key="person",
        property_key="tower|101",
        property_identity=("businessbay", "tower|101"),
        import_id=1,
        list_id=1,
        source_sheet="Owners",
        source_row_number=id,
        source_filename="owners.csv",
        source_list_name="Owners",
        contact_name="Example Owner",
        phone_primary="0501234567",
        phone_alternate=None,
        email_primary=None,
        area_name="Business Bay",
        project_name="Tower",
        building_name="Tower",
        unit_number="101",
        property_type="Apartment",
        party_role="Buyer",
        procedure_type="Sale",
        transaction_date=date(2025, 1, 1),
        transaction_price_aed=1_000_000,
        ownership_status="verified_current_owner",
        assessed_status="verified_current_owner",
        confidence_score=95,
        assessed_confidence_score=95,
        match_reason="Saved match",
        assessed_reason="Current registry support",
        latest_sale_date=date(2025, 1, 1),
        latest_sale_price_aed=1_000_000,
        later_sale_date=None,
        lead_id="lease",
        unit_candidate_key="unit",
        lease_end=date.today() + timedelta(days=10),
        annual_rent_aed=90_000,
        supported_former=False,
        evidence={},
        created_at=NOW,
        updated_at=NOW,
        claim_resolver_version="test",
        import_resolver_version="test",
    )
    return row | changes


def snapshot(rows):
    return OwnerAssessmentSnapshot(
        rows=rows,
        summary=CrmOwnerHistorySummary(
            source_event_count=len(rows),
            identifiable_property_count=0,
            owner_property_count=0,
            verified_current_count=0,
            probable_current_count=0,
            former_count=0,
            unresolved_count=0,
            invalid_identity_source_count=0,
            legacy_source_event_count=0,
            resolver_versions={},
            checked_at=NOW,
            warehouse_status="available",
            assessment_version="test-assessment",
        ),
        checked_at=NOW,
        warehouse_status="available",
    )


def install_snapshot(monkeypatch, rows):
    value = snapshot(rows)
    for module in (owners, renewal_leads, workspaces):
        monkeypatch.setattr(module, "get_owner_assessment", AsyncMock(return_value=value))
    monkeypatch.setattr(
        owners, "_enrich_owner_profile_registry", AsyncMock(side_effect=lambda profile: profile)
    )
    return value


async def registry(**changes):
    arguments = dict(
        organization_id="org",
        list_id=None,
        scope="all",
        status=None,
        search=None,
        lease_window=None,
        portfolio_only=False,
        min_rent_aed=None,
        max_rent_aed=None,
        min_value_aed=None,
        max_value_aed=None,
        limit=20,
        offset=0,
    )
    return await owners.get_owner_registry(None, **(arguments | changes))


async def test_aliases_have_one_profile_and_identical_assessment_on_list_and_click(monkeypatch):
    rows = [
        event(1, assessed_status="conflicting_claim", assessed_reason="Competing buyer"),
        event(2, assessed_status="conflicting_claim", assessed_reason="Competing buyer"),
        event(
            3,
            property_identity=None,
            property_key="source:3",
            assessed_status="insufficient_property_data",
        ),
    ]
    install_snapshot(monkeypatch, rows)
    listed = await registry()
    clicked = await owners.get_owner_profile(None, organization_id="org", owner_key="alias-2")
    assert listed.total == 1
    assert listed.owners[0] == clicked
    assert clicked.owner_key == "alias-1"
    assert clicked.property_count == 1
    assert clicked.contact_ready_count == 0
    assert clicked.properties[0].ownership_status == "conflicting_claim"
    assert clicked.history_summary.invalid_identity_source_count == 1
    assert clicked.history_summary.checked_at == NOW
    assert clicked.history_summary.warehouse_status == "available"
    assert rows[0]["ownership_status"] == "verified_current_owner"
    # An empty page still reports the full filtered result count.
    assert (await registry(offset=1)).total == 1
    assert (await registry(offset=1)).owners == []


async def test_ready_requires_valid_channel_and_valid_property_and_reconciles_summary(monkeypatch):
    install_snapshot(
        monkeypatch,
        [
            event(1, canonical_owner_key="good"),
            event(
                2, canonical_owner_key="bad-channel", phone_primary="123", email_primary="invalid"
            ),
            event(
                3,
                canonical_owner_key="bad-property",
                property_identity=None,
                assessed_status="insufficient_property_data",
            ),
        ],
    )
    all_owners = await registry()
    ready = await registry(scope="rental_ready")
    assert all_owners.total == 3
    assert ready.total == all_owners.summary.rental_owner_profiles == 1
    assert ready.owners[0].owner_key == "alias-1"
    assert ready.owners[0].phone_primary == "+971501234567"
    invalid = next(item for item in all_owners.owners if item.owner_key == "alias-3")
    assert invalid.property_count == invalid.contact_ready_count == 0


async def test_review_filter_includes_invalid_association_on_otherwise_verified_person(monkeypatch):
    install_snapshot(
        monkeypatch,
        [
            event(1),
            event(2, property_identity=None, assessed_status="insufficient_property_data"),
            event(
                3, list_id=2, canonical_owner_key="other", assessed_status="probable_current_owner"
            ),
        ],
    )
    all_owners = await registry()
    review = await registry(scope="needs_review")
    assert review.total == all_owners.summary.needs_review_profiles == 2
    scoped = await registry(scope="needs_review", list_id=1)
    assert scoped.total == scoped.summary.needs_review_profiles == 1
    assert scoped.owners[0].property_count == 1


async def test_ambiguous_legacy_key_cannot_merge_distinct_people(monkeypatch):
    install_snapshot(
        monkeypatch,
        [
            event(1, owner_key="legacy", canonical_owner_key="one"),
            event(2, owner_key="legacy", canonical_owner_key="two"),
        ],
    )
    listed = await registry()
    assert {owner.owner_key for owner in listed.owners} == {"one", "two"}
    with pytest.raises(HTTPException) as error:
        await owners.get_owner_profile(None, organization_id="org", owner_key="legacy")
    assert error.value.status_code == 409


async def test_renewal_uses_canonical_assessment_and_rejects_stale_green_claims(monkeypatch):
    monkeypatch.setattr(
        "app.crm.workspace_repository.list_lead_workspaces_for_candidates",
        AsyncMock(return_value=[]),
    )
    install_snapshot(monkeypatch, [event(1), event(2)])
    result = await renewal_leads._owners_by_candidate(
        None, candidate_keys=["unit"], user_id="user", organization_id="org"
    )
    assert result["unit"].phone == "+971501234567"
    for status in (
        "former_owner",
        "unverified_former_owner",
        "conflicting_claim",
        "unit_linked_unverified",
    ):
        install_snapshot(monkeypatch, [event(1, assessed_status=status)])
        assert (
            await renewal_leads._owners_by_candidate(
                None, candidate_keys=["unit"], user_id="user", organization_id="org"
            )
            == {}
        )
    install_snapshot(monkeypatch, [event(1, property_identity=None)])
    assert (
        await renewal_leads._owners_by_candidate(
            None, candidate_keys=["unit"], user_id="user", organization_id="org"
        )
        == {}
    )


async def test_imported_workspace_retracts_owner_and_green_without_changing_saved_work(monkeypatch):
    install_snapshot(monkeypatch, [event(1, assessed_status="former_owner")])
    workspace = CrmLeadWorkspace(
        id=1,
        user_id="user",
        organization_id="org",
        lead_id="lease",
        unit_candidate_key="unit",
        owner_name="Stale name",
        owner_phone="0501234567",
        owner_source="owner_import",
        pipeline_status="contact_ready",
        highlight_color="green",
        tags=["Imported owner"],
        created_at=NOW,
        updated_at=NOW,
    )
    monkeypatch.setattr(
        "app.crm.workspace_repository.list_lead_workspaces_for_candidates",
        AsyncMock(return_value=[workspace]),
    )
    result = await workspaces._assessed_workspace_summary(None, workspace)
    assert result.owner_name is None and result.owner_phone is None
    assert result.pipeline_status == "new" and result.highlight_color == "none"
    assert workspace.owner_name == "Stale name" and workspace.pipeline_status == "contact_ready"
    workspace.owner_source = "manual"
    result = await workspaces._assessed_workspace_summary(None, workspace)
    assert result.owner_name == "Stale name" and result.pipeline_status == "contact_ready"


async def test_alias_workspace_notes_remain_visible_and_persisted_keys_unchanged(monkeypatch):
    install_snapshot(monkeypatch, [event(1), event(2)])
    saved = [
        CrmOwnerWorkspace(
            id=id,
            user_id="user",
            organization_id="org",
            owner_key=f"alias-{id}",
            pipeline_status="contacted",
            created_at=NOW,
            updated_at=NOW + timedelta(seconds=id),
        )
        for id in (1, 2)
    ]
    notes = [
        CrmOwnerNote(
            id=id,
            workspace_id=id,
            user_id="user",
            organization_id="org",
            body=f"Note {id}",
            created_at=NOW + timedelta(seconds=id),
            updated_at=NOW,
        )
        for id in (1, 2)
    ]
    monkeypatch.setattr(
        "app.crm.workspace_repository.list_owner_workspaces", AsyncMock(return_value=saved)
    )
    monkeypatch.setattr(
        "app.crm.workspace_repository.list_owner_notes", AsyncMock(return_value=notes)
    )
    result = await workspaces.list_owner_workspaces(None, user_id="user", organization_id="org")
    assert len(result) == 1 and result[0].owner_key == "alias-1"
    assert result[0].note_count == 2 and result[0].last_note == "Note 2"
    assert [workspace.owner_key for workspace in saved] == ["alias-1", "alias-2"]


def stored_claim(row):
    from app.crm.import_models import CrmPropertyContactClaim

    return CrmPropertyContactClaim(
        **{
            name: value
            for name, value in row.items()
            if name in CrmPropertyContactClaim.model_fields
        },
        row_fingerprint=f"row-{row['id']}",
    )


async def test_import_properties_use_all_context_and_fetch_source_metadata_for_page_only(
    monkeypatch,
):
    from app.crm import imports

    # The selected file has over 50 disposal events. Its supported present buyer
    # appears only in a different file, so source pagination cannot choose the owner.
    source = [
        event(
            id,
            canonical_owner_key=f"seller-{id}",
            contact_name=f"Seller {id}",
            party_role="Seller",
            assessed_status="former_owner",
            transaction_date=date(2026, 1, 1),
        )
        for id in range(1, 61)
    ]
    buyer = event(
        61, import_id=2, list_id=2, canonical_owner_key="buyer", contact_name="Present Buyer"
    )
    invalid = event(
        62,
        property_identity=None,
        property_key="source:62",
        assessed_status="insufficient_property_data",
    )
    assessed = install_snapshot(monkeypatch, source + [buyer, invalid])
    monkeypatch.setattr(imports, "get_owner_assessment", AsyncMock(return_value=assessed))
    monkeypatch.setattr(
        "app.crm.import_repository.get_import_for_org", AsyncMock(return_value=object())
    )

    async def page_claims(db, org, ids):
        return [stored_claim(row) for row in source if row["id"] in ids]

    fetch = AsyncMock(side_effect=page_claims)
    monkeypatch.setattr("app.crm.owner_repository.list_claims_by_ids", fetch)
    result = await imports.list_import_properties(
        None, import_id=1, organization_id="org", search="Seller", limit=1, offset=0
    )
    assert result.total == 1
    assert result.rows[0].current_owner == "Present Buyer"
    assert result.rows[0].rows == 60
    assert result.rows[0].records_truncated
    assert len(result.rows[0].records) == len(fetch.call_args.args[2]) == 50
    assert {item.status for item in result.rows[0].records} == {"former_owner"}
    assert all(row["ownership_status"] == "verified_current_owner" for row in source)


async def test_contact_list_page_status_count_and_sources_use_shared_assessment(monkeypatch):
    from app.crm.import_models import CrmContactList

    rows = [event(1, assessed_status="former_owner"), event(2, assessed_status="former_owner")]
    install_snapshot(monkeypatch, rows)
    contact_list = CrmContactList(
        id=1,
        organization_id="org",
        created_by_user_id="user",
        source_import_id=1,
        name="Owners",
        created_at=NOW,
        updated_at=NOW,
    )
    monkeypatch.setattr(
        "app.crm.owner_repository.get_contact_list", AsyncMock(return_value=contact_list)
    )
    fetch = AsyncMock(return_value=[stored_claim(rows[1])])
    monkeypatch.setattr("app.crm.owner_repository.list_claims_by_ids", fetch)
    result = await owners.get_contact_list(
        None,
        list_id=1,
        organization_id="org",
        status="former_owner",
        search=None,
        limit=20,
        offset=0,
    )
    assert result.total == result.list.total_contacts == result.list.former_owners == 1
    assert result.list.contact_ready == 0
    assert result.contacts[0].owner_key == "alias-1"
    assert result.contacts[0].ownership_status == "former_owner"
    assert result.contacts[0].duplicate_count == 2
    assert result.contacts[0].source_rows == ["Owners:1", "Owners:2"]
    assert fetch.call_args.args[2] == [2]


async def test_import_enrichment_does_not_reclassify_legacy_manual_workspace(monkeypatch):
    from app.crm.identity import ParsedContact

    install_snapshot(monkeypatch, [event(1)])
    workspace = CrmLeadWorkspace(
        id=1,
        user_id="user",
        organization_id="org",
        lead_id="lease",
        unit_candidate_key="unit",
        owner_name="Agent confirmed owner",
        owner_phone="+971509876543",
        owner_source=None,
        pipeline_status="contacted",
        tags=[],
        created_at=NOW,
        updated_at=NOW,
    )
    monkeypatch.setattr(
        "app.crm.workspace_repository.list_lead_workspaces_for_candidates",
        AsyncMock(return_value=[workspace]),
    )
    candidate = ParsedContact(
        source_sheet="Owners",
        source_row_number=1,
        contact_name="Imported Owner",
        phone_primary="+971501234567",
        phone_alternate=None,
        email_primary=None,
        area_name="Business Bay",
        project_name="Tower",
        building_name="Tower",
        unit_number="101",
        property_type="Apartment",
        party_role="Buyer",
        procedure_type="Sale",
        transaction_date=date(2025, 1, 1),
        transaction_price_aed=1_000_000,
        row_fingerprint="source",
        ownership_status="verified_current_owner",
        lead_id="lease",
        unit_candidate_key="unit",
    )
    db = SimpleNamespace(add=lambda value: None)
    await workspaces._enrich_workspaces(
        db, candidates=[candidate], user_id="user", organization_id="org", list_name="Owners"
    )
    result = await workspaces._assessed_workspace_summary(None, workspace)
    assert workspace.owner_source == "manual"
    assert "Imported owner" in workspace.tags
    assert result.owner_name == "Agent confirmed owner"
    assert result.owner_phone == "+971509876543"


async def test_registry_tabs_filter_people_without_changing_clicked_portfolio_counts(monkeypatch):
    install_snapshot(
        monkeypatch,
        [
            event(1),
            event(
                2,
                property_key="tower|102",
                property_identity=("businessbay", "tower|102"),
                unit_number="102",
                assessed_status="former_owner",
                lead_id=None,
                unit_candidate_key=None,
            ),
            event(
                3,
                property_key="tower|103",
                property_identity=("businessbay", "tower|103"),
                unit_number="103",
                assessed_status="unit_linked_unverified",
                lead_id=None,
                unit_candidate_key=None,
            ),
        ],
    )
    clicked = await owners.get_owner_profile(None, organization_id="org", owner_key="alias-1")
    assert clicked.property_count == 3 and clicked.contact_ready_count == 1
    for scope in ("all", "rental_ready", "registry", "needs_review"):
        listed = await registry(scope=scope, min_properties=3)
        assert listed.total == 1
        assert listed.owners[0] == clicked
    # The prior-owner tab counts historical properties in that tab; opening
    # the person still shows their complete portfolio across all statuses.
    assert (await registry(scope="prior_owners", min_properties=3)).total == 0
    prior = await registry(scope="prior_owners", min_properties=1)
    assert prior.total == 1 and prior.owners[0].property_count == 1
    assert prior.owners[0].properties[0].ownership_status == "former_owner"
    reopened = await owners.get_owner_profile(None, organization_id="org", owner_key="alias-1")
    assert reopened.property_count == 3
    # Cosmetic detail enrichment must never mutate the cached registry profile.
    clicked.properties[0].registry_bedrooms = "2"
    assert (await registry()).owners[0].properties[0].registry_bedrooms is None


async def test_retracted_rental_link_cannot_display_verified_owner_on_previous_lead(monkeypatch):
    from app.crm.import_models import CrmContactList

    assessed = event(1, lead_id=None, unit_candidate_key=None)
    install_snapshot(monkeypatch, [assessed])
    original = stored_claim(event(1))
    contact_list = CrmContactList(
        id=1,
        organization_id="org",
        created_by_user_id="user",
        source_import_id=1,
        name="Owners",
        created_at=NOW,
        updated_at=NOW,
    )
    monkeypatch.setattr(
        "app.crm.owner_repository.list_lead_claims_with_lists",
        AsyncMock(return_value=[(original, contact_list)]),
    )
    assert (
        await owners.list_lead_imported_contacts(None, lead_id="lease", organization_id="org") == []
    )


async def test_possible_latest_seller_stays_reviewable_without_ready_or_automatic_green(
    monkeypatch,
):
    from app.crm.import_models import CrmContactList

    rows = [
        event(
            1,
            transaction_date=date(2020, 1, 1),
            event_assessed_status="former_owner",
            assessed_status="probable_current_owner",
            assessed_confidence_score=55,
            event_assessed_confidence_score=99,
        ),
        event(
            2,
            list_id=2,
            party_role="Seller",
            event_assessed_status="probable_current_owner",
            assessed_status="probable_current_owner",
            assessed_confidence_score=55,
        ),
    ]
    install_snapshot(monkeypatch, rows)
    listed = await registry()
    clicked = await owners.get_owner_profile(None, organization_id="org", owner_key="alias-1")
    assert listed.owners[0] == clicked
    assert clicked.properties[0].imported_party_role == "Seller"
    assert clicked.highest_ownership_status == "probable_current_owner"
    assert clicked.contact_ready_count == listed.summary.rental_owner_profiles == 0
    assert (await registry(scope="rental_ready")).total == 0
    historical_file = await registry(scope="rental_ready", list_id=1)
    assert historical_file.total == historical_file.summary.rental_owner_profiles == 0
    assert (await registry(scope="needs_review")).total == listed.summary.needs_review_profiles == 1
    contact_list = CrmContactList(
        id=1,
        organization_id="org",
        created_by_user_id="user",
        source_import_id=1,
        name="Owners",
        created_at=NOW,
        updated_at=NOW,
    )
    assert owners._assessed_list_summary(contact_list, rows).contact_ready == 0

    saved = CrmOwnerWorkspace(
        id=1,
        user_id="user",
        organization_id="org",
        owner_key="alias-1",
        pipeline_status="contact_ready",
        highlight_color="green",
        created_at=NOW,
        updated_at=NOW,
    )
    monkeypatch.setattr(
        "app.crm.workspace_repository.list_owner_workspaces", AsyncMock(return_value=[saved])
    )
    monkeypatch.setattr("app.crm.workspace_repository.list_owner_notes", AsyncMock(return_value=[]))
    workspace = (
        await workspaces.list_owner_workspaces(None, user_id="user", organization_id="org")
    )[0]
    assert workspace.pipeline_status == "researching" and workspace.highlight_color == "none"
    assert saved.pipeline_status == "contact_ready" and saved.highlight_color == "green"
    lookup = AsyncMock()
    monkeypatch.setattr("app.crm.workspace_repository.list_lead_workspaces_for_candidates", lookup)
    await workspaces._enrich_workspaces(
        None,
        candidates=[
            SimpleNamespace(
                unit_candidate_key="unit",
                lead_id="lease",
                has_valid_contact=True,
                ownership_status="probable_current_owner",
                party_role="Seller",
            )
        ],
        user_id="user",
        organization_id="org",
        list_name="Owners",
    )
    lookup.assert_not_awaited()


async def test_current_buyer_support_represents_profile_even_when_paired_seller_row_is_later(
    monkeypatch,
):
    install_snapshot(
        monkeypatch,
        [
            event(
                1,
                event_assessed_status="probable_current_owner",
                assessed_status="probable_current_owner",
                assessed_confidence_score=65,
            ),
            event(
                2,
                party_role="Seller",
                event_assessed_status="probable_current_owner",
                assessed_status="probable_current_owner",
                assessed_confidence_score=55,
                transaction_date=date(2025, 1, 2),
            ),
        ],
    )
    listed = await registry(scope="rental_ready")
    assert listed.total == listed.summary.rental_owner_profiles == 1
    assert listed.owners[0].contact_ready_count == 1
    assert listed.owners[0].properties[0].imported_party_role == "Buyer"
    assert listed.owners[0].properties[0].confidence_score == 65


async def test_verified_renewal_buyer_is_not_blocked_by_its_tentative_same_sale_seller(monkeypatch):
    monkeypatch.setattr(
        "app.crm.workspace_repository.list_lead_workspaces_for_candidates",
        AsyncMock(return_value=[]),
    )
    buyer = event(
        1,
        canonical_owner_key="buyer",
        contact_name="Verified Buyer",
        event_assessed_status="verified_current_owner",
        sale_anchor_key="sale-1",
        sale_anchor_date=date(2025, 1, 1),
    )
    seller = event(
        2,
        canonical_owner_key="seller",
        contact_name="Possible Seller",
        party_role="Seller",
        assessed_status="probable_current_owner",
        event_assessed_status="probable_current_owner",
        assessed_confidence_score=55,
        sale_anchor_key="sale-1",
        sale_anchor_date=date(2025, 1, 1),
    )
    old_seller_buyer = event(
        3,
        canonical_owner_key="seller",
        contact_name="Possible Seller",
        assessed_status="probable_current_owner",
        event_assessed_status="former_owner",
    )

    async def resolve(rows):
        install_snapshot(monkeypatch, rows)
        return await renewal_leads._owners_by_candidate(
            None, candidate_keys=["unit"], user_id="user", organization_id="org"
        )

    paired = await resolve([buyer, seller, old_seller_buyer])
    assert paired["unit"].name == "Verified Buyer"
    assert await resolve([seller]) == {}
    for competing in (
        seller | {"sale_anchor_key": "different-sale"},
        seller | {"transaction_date": date(2025, 1, 2)},
        seller | {"party_role": "Buyer"},
        seller
        | {"assessed_status": "conflicting_claim", "event_assessed_status": "conflicting_claim"},
    ):
        assert await resolve([buyer, competing]) == {}
    assert (
        await resolve([buyer, seller, seller | {"id": 4, "canonical_owner_key": "second-seller"}])
        == {}
    )


MATCH = {
    "version": "property-first-2",
    "matcher_outcome": "matched_sale",
    "outcome": "matched_sale",
    "colour": "green",
    "property_key": ["tower", "101"],
    "sale": {
        "unit": "101",
        "building": "Tower",
        "project": "",
        "area": "Business Bay",
        "amount_aed": 1_000_000,
        "date": "2025-01-01",
        "sqft": 700.5,
        "source": "DXBI",
    },
    "reasons": ["unit 101 in tower"],
    "warnings": ["repeat_price"],
    "later_sale_date": None,
}


def matched_rows():
    """Three imported rows: green, a grey lender, and one with no verdict (an older import)."""
    return [
        event(1, match_outcome="matched_sale", match_colour="green", canonical_owner_key="a"),
        event(2, match_outcome="lender", match_colour="grey", canonical_owner_key="b"),
        event(3, match_outcome=None, match_colour=None, canonical_owner_key="c"),
    ]


async def contact_list(monkeypatch, rows, **filters):
    from app.crm.import_models import CrmContactList

    install_snapshot(monkeypatch, rows)
    monkeypatch.setattr(
        "app.crm.owner_repository.get_contact_list",
        AsyncMock(
            return_value=CrmContactList(
                id=1,
                organization_id="org",
                created_by_user_id="user",
                source_import_id=1,
                name="Owners",
                created_at=NOW,
                updated_at=NOW,
            )
        ),
    )

    async def page_claims(db, org, ids):
        return [
            stored_claim(row | {"evidence": {"owner_match": MATCH}})
            for row in rows
            if row["id"] in ids
        ]

    monkeypatch.setattr(
        "app.crm.owner_repository.list_claims_by_ids", AsyncMock(side_effect=page_claims)
    )
    arguments = dict(list_id=1, organization_id="org", status=None, search=None, limit=20, offset=0)
    return await owners.get_contact_list(None, **(arguments | filters))


async def test_a_contact_row_carries_the_stored_match_verdict(monkeypatch):
    result = await contact_list(monkeypatch, matched_rows()[:1])
    (row,) = result.contacts
    assert row.match_outcome == "matched_sale" and row.match_colour == "green"
    assert row.match_reasons == ["unit 101 in tower"]
    assert row.match_warnings == ["repeat_price"]
    assert row.matched_sale is not None
    assert row.matched_sale.amount_aed == 1_000_000 and row.matched_sale.source == "DXBI"
    assert row.matched_sale.sqft == 700.5


async def test_a_row_with_no_verdict_has_empty_match_fields(monkeypatch):
    from app.crm.import_models import CrmContactClaimResponse

    row = CrmContactClaimResponse.model_validate(
        owners._claim_response(stored_claim(event(3))).model_dump()
    )
    assert row.match_outcome is None and row.match_colour is None
    assert row.matched_sale is None and row.match_reasons == []


async def test_the_colour_filter_takes_several_colours(monkeypatch):
    rows = matched_rows()
    assert (await contact_list(monkeypatch, rows, match_colour=["green"])).total == 1
    assert (await contact_list(monkeypatch, rows, match_colour=["green", "grey"])).total == 2
    assert (await contact_list(monkeypatch, rows, match_colour=["red"])).total == 0
    assert (await contact_list(monkeypatch, rows)).total == 3


async def test_the_outcome_filter_separates_lenders_from_other_grey_rows(monkeypatch):
    rows = matched_rows()
    result = await contact_list(monkeypatch, rows, match_outcome=["lender"])
    assert result.total == 1 and result.contacts[0].id == 2
    both = await contact_list(monkeypatch, rows, match_outcome=["lender", "matched_sale"])
    assert both.total == 2


async def test_colour_and_outcome_filters_combine(monkeypatch):
    rows = matched_rows()
    result = await contact_list(
        monkeypatch, rows, match_colour=["grey"], match_outcome=["matched_sale"]
    )
    assert result.total == 0


async def test_an_owner_who_still_holds_a_property_is_not_headlined_as_former(monkeypatch):
    # The same person owns 101 today and sold 102. Their headline (list chip and panel chip)
    # must say what they hold now; "former" applies to 102 only. Seen live: an owner with 29
    # transaction-matched current properties and 3 sold ones was shown as "Former owner".
    install_snapshot(
        monkeypatch,
        [
            event(1),
            event(
                2,
                property_key="tower|102",
                property_identity=("businessbay", "tower|102"),
                unit_number="102",
                assessed_status="former_owner",
                assessed_confidence_score=99,
                lead_id=None,
                unit_candidate_key=None,
            ),
        ],
    )
    clicked = await owners.get_owner_profile(None, organization_id="org", owner_key="alias-1")
    assert clicked.highest_ownership_status == "verified_current_owner"
    listed = await registry(scope="current_owners")
    assert listed.owners[0].highest_ownership_status == clicked.highest_ownership_status
    # Someone who has sold everything is still a former owner.
    sold = await registry(scope="prior_owners")
    assert sold.owners[0].highest_ownership_status == "former_owner"
