"""Every owner surface consumes the assessed identity, never a saved green label."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from owner_store_support import install_rows

from app.crm import owner_assessment, owner_store, owners, renewal_leads, workspaces
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


class DB:
    """The session of the running test, for helpers that do not take it as an argument."""

    session = None


async def install_snapshot(monkeypatch, rows):
    value = snapshot(rows)
    from app.crm.owner_store import open_store

    async def renewal_store(db, organization_id):
        return await open_store(DB.session, organization_id)

    monkeypatch.setattr(renewal_leads, "open_store", renewal_store)
    monkeypatch.setattr(
        owners, "_enrich_owner_profile_registry", AsyncMock(side_effect=lambda profile: profile)
    )
    await install_rows(DB.session, monkeypatch, rows)
    return value


@pytest.fixture(autouse=True)
def _session(pg_session, monkeypatch):
    # These cases install published projections directly, with their source evidence assumed.
    monkeypatch.setattr(
        renewal_leads.renewal_repository, "has_imported_unit_keys", AsyncMock(return_value=True)
    )
    DB.session = pg_session
    yield
    DB.session = None


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
    return await owners.get_owner_registry(DB.session, **(arguments | changes))


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
    await install_snapshot(monkeypatch, rows)
    listed = await registry()
    clicked = await owners.get_owner_profile(DB.session, organization_id="org", owner_key="alias-2")
    assert listed.total == 1
    assert listed.owners[0] == clicked
    assert clicked.owner_key == "alias-1"
    assert clicked.property_count == 1
    assert clicked.contact_ready_count == 0
    assert clicked.properties[0].ownership_status == "conflicting_claim"
    assert clicked.history_summary.invalid_identity_source_count == 1
    assert clicked.history_summary.checked_at is not None
    assert clicked.history_summary.warehouse_status == "available"
    assert rows[0]["ownership_status"] == "verified_current_owner"
    # An empty page still reports the full filtered result count.
    assert (await registry(offset=1)).total == 1
    assert (await registry(offset=1)).owners == []


async def test_ready_requires_valid_channel_and_valid_property_and_reconciles_summary(monkeypatch):
    await install_snapshot(
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
    await install_snapshot(
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
    await install_snapshot(
        monkeypatch,
        [
            event(1, owner_key="legacy", canonical_owner_key="one"),
            event(2, owner_key="legacy", canonical_owner_key="two"),
        ],
    )
    listed = await registry()
    assert {owner.owner_key for owner in listed.owners} == {"one", "two"}
    with pytest.raises(HTTPException) as error:
        await owners.get_owner_profile(DB.session, organization_id="org", owner_key="legacy")
    assert error.value.status_code == 409


async def test_renewal_uses_canonical_assessment_and_rejects_stale_green_claims(monkeypatch):
    monkeypatch.setattr(
        "app.crm.workspace_repository.list_lead_workspaces_for_candidates",
        AsyncMock(return_value=[]),
    )
    await install_snapshot(monkeypatch, [event(1), event(2)])
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
        await install_snapshot(monkeypatch, [event(1, assessed_status=status)])
        assert (
            await renewal_leads._owners_by_candidate(
                None, candidate_keys=["unit"], user_id="user", organization_id="org"
            )
            == {}
        )
    await install_snapshot(monkeypatch, [event(1, property_identity=None)])
    assert (
        await renewal_leads._owners_by_candidate(
            None, candidate_keys=["unit"], user_id="user", organization_id="org"
        )
        == {}
    )


async def test_renewal_projection_scopes_tenant_generation_and_unit(pg_session, monkeypatch):
    await install_rows(
        pg_session, monkeypatch, [event(contact_name="Other tenant")], organization_id="other"
    )
    await install_rows(
        pg_session,
        monkeypatch,
        [event(contact_name="Current owner"), event(2, unit_candidate_key="other-unit")],
    )
    store = await owner_store.open_store(pg_session, "org")
    await owner_store._write(
        pg_session.bind,
        "org",
        store.state.generation + 1000,
        [event(contact_name="Unpublished owner")],
    )
    rows = await store.renewal_rows(["unit"])
    assert len(rows) == 1 and rows[0]["contact_name"] == "Current owner"
    assert rows[0]["transaction_date"] == date(2025, 1, 1)
    assert rows[0]["property_identity"] == ("businessbay", "tower|101")
    assert rows[0]["event_assessed_status"] == "verified_current_owner"
    assert "evidence" not in rows[0]  # large warehouse payloads do not enter the request


async def test_renewal_projection_preserves_exact_eligibility_and_competitors(
    pg_session, monkeypatch
):
    await install_rows(
        pg_session,
        monkeypatch,
        [
            event(),  # legacy rows without an event status use their assessed status
            event(
                2,
                canonical_owner_key="seller",
                party_role="Seller",
                assessed_status="probable_current_owner",
                event_assessed_status="probable_current_owner",
            ),
            event(
                3,
                canonical_owner_key="competitor",
                assessed_status="conflicting_claim",
                event_assessed_status="conflicting_claim",
                phone_primary=None,
                lead_id=None,
            ),
            event(4, assessed_status="former_owner"),
            event(5, event_assessed_status="former_owner"),
            event(6, event_assessed_status=None),  # explicit null must not use the legacy fallback
            event(7, property_identity=None),
            event(8, assessed_status="unit_linked_unverified"),
        ],
    )
    store = await owner_store.open_store(pg_session, "org")
    projected = {row["id"]: row for row in await store.renewal_rows(["unit", "unit"])}
    assert set(projected) == {1, 2, 3}
    assert projected[1]["event_assessed_status"] == "verified_current_owner"
    assert projected[2]["party_role"] == "Seller"
    assert projected[3]["lead_id"] is None
    assert (
        await renewal_leads._owners_by_candidate(
            pg_session, candidate_keys=["unit"], user_id="sql-prefilter", organization_id="org"
        )
        == {}
    )


@pytest.mark.parametrize("owner", ["known", "unknown"])
async def test_large_renewal_filter_reuses_published_rows(pg_session, monkeypatch, owner):
    rows = [
        event(),
        event(2, unit_candidate_key="former", assessed_status="former_owner"),
        event(3, unit_candidate_key="conflict", assessed_status="conflicting_claim"),
        event(4, unit_candidate_key="ambiguous", canonical_owner_key="one"),
        event(5, unit_candidate_key="ambiguous", canonical_owner_key="two"),
        event(6, unit_candidate_key="event-former", event_assessed_status="former_owner"),
        event(7, unit_candidate_key="clear"),
        event(8, unit_candidate_key="import-only"),
        event(9, unit_candidate_key="unreachable", phone_primary=None),
    ]
    await install_rows(pg_session, monkeypatch, rows)
    user = f"renewal-{owner}"
    for tenant, agent, key, name in (
        ("org", user, "unit", "My manual owner"),
        ("org", user, "clear", None),
        ("org", f"other-{user}", "unit", "Other agent's owner"),
        ("other", user, "unit", "Other tenant's owner"),
    ):
        pg_session.add(
            CrmLeadWorkspace(
                organization_id=tenant,
                user_id=agent,
                lead_id=f"lease-{key}",
                unit_candidate_key=key,
                owner_source="manual",
                owner_name=name,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    await pg_session.commit()
    rebuild = AsyncMock(side_effect=AssertionError("Renewals must reuse the published assessment"))
    monkeypatch.setattr(owner_assessment, "_build", rebuild)
    monkeypatch.setattr(owner_assessment, "_scoped_assessment", rebuild)
    monkeypatch.setattr(owner_store, "_build_exclusively", rebuild)
    keys = [row["unit_candidate_key"] for row in rows] + [
        f"unit-{index}" for index in range(owner_assessment.SCOPED_CACHE_MAX_ROWS + 1)
    ]
    monkeypatch.setattr(
        renewal_leads.renewal_repository, "list_imported_unit_keys", AsyncMock(return_value=keys)
    )
    leases = AsyncMock(
        return_value=renewal_leads.CrmRenewalsResponse(
            leads=[], total=0, limit=50, offset=0, as_of=date.today()
        )
    )
    monkeypatch.setattr(renewal_leads, "list_renewals", leases)
    await renewal_leads.list_owner_renewals(
        pg_session,
        user_id=user,
        organization_id="org",
        window=None,
        area=None,
        property_type=None,
        project=None,
        building=None,
        limit=50,
        offset=0,
        owner=owner,
    )
    assert leases.await_args.kwargs["unit_keys"] == ["import-only", "unit"]
    assert leases.await_args.kwargs.get("exclude_units", False) == (owner == "unknown")
    resolved = await renewal_leads._owners_by_candidate(
        pg_session,
        candidate_keys=["unit", "clear", "import-only"],
        user_id=user,
        organization_id="org",
    )
    assert set(resolved) == {"unit", "import-only"}
    assert resolved["unit"].name == "My manual owner"
    assert resolved["unit"].source == "workspace"
    assert resolved["import-only"].source == "owner_import"
    rebuild.assert_not_awaited()


@pytest.mark.parametrize("owner", ["known", "unknown"])
@pytest.mark.parametrize(
    "change",
    [
        "source",
        "warehouse",
        "unavailable",
        "source_during_read",
        "warehouse_during_read",
        "generation",
    ],
)
async def test_stale_renewal_projection_fails_before_listing_leases(
    pg_session, monkeypatch, owner, change
):
    from dataclasses import replace

    await install_rows(pg_session, monkeypatch, [event()])
    store = await owner_store.open_store(pg_session, "org")
    if change == "unavailable":
        store.state = replace(store.state, warehouse_status="unavailable")
    elif change == "generation":
        # A same-input publication discards the reader's old rows: an empty SELECT
        # must be a retry, never proof that every known owner has disappeared.
        await install_rows(pg_session, monkeypatch, [event(contact_name="New generation")])
    else:
        tokens = (
            ("changed", "test-evidence")
            if change.startswith("source")
            else ("test-revision", "changed")
        )
        current = ("test-revision", "test-evidence")
        token_read = (
            AsyncMock(side_effect=[current, tokens])
            if change.endswith("during_read")
            else AsyncMock(return_value=tokens)
        )
        monkeypatch.setattr(owner_store, "_tokens", token_read)
    monkeypatch.setattr(renewal_leads, "open_store", AsyncMock(return_value=store))
    monkeypatch.setattr(
        renewal_leads.renewal_repository,
        "list_imported_unit_keys",
        AsyncMock(return_value=["unit"]),
    )
    leases = AsyncMock(
        side_effect=AssertionError("Staleness must not alter the known/unknown split")
    )
    monkeypatch.setattr(renewal_leads, "list_renewals", leases)
    with pytest.raises(HTTPException) as error:
        await renewal_leads.list_owner_renewals(
            pg_session,
            user_id="user",
            organization_id="org",
            window=None,
            area=None,
            property_type=None,
            project=None,
            building=None,
            limit=50,
            offset=0,
            owner=owner,
        )
    assert error.value.status_code == 503
    leases.assert_not_awaited()


async def test_imported_workspace_retracts_owner_and_green_without_changing_saved_work(monkeypatch):
    await install_snapshot(monkeypatch, [event(1, assessed_status="former_owner")])
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
    await install_snapshot(monkeypatch, [event(1), event(2)])
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
    result = await workspaces.list_owner_workspaces(
        DB.session, user_id="user", organization_id="org"
    )
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
    await install_snapshot(monkeypatch, source + [buyer, invalid])
    monkeypatch.setattr(
        "app.crm.import_repository.get_import_for_org", AsyncMock(return_value=object())
    )

    async def page_claims(db, org, ids):
        return [stored_claim(row) for row in source if row["id"] in ids]

    fetch = AsyncMock(side_effect=page_claims)
    monkeypatch.setattr("app.crm.owner_repository.list_claims_by_ids", fetch)
    result = await imports.list_import_properties(
        DB.session, import_id=1, organization_id="org", search="Seller", limit=1, offset=0
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
    await install_snapshot(monkeypatch, rows)
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
        DB.session,
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

    await install_snapshot(monkeypatch, [event(1)])
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
    await install_snapshot(
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
    clicked = await owners.get_owner_profile(DB.session, organization_id="org", owner_key="alias-1")
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
    reopened = await owners.get_owner_profile(
        DB.session, organization_id="org", owner_key="alias-1"
    )
    assert reopened.property_count == 3
    # Cosmetic detail enrichment must never mutate the cached registry profile.
    clicked.properties[0].registry_bedrooms = "2"
    assert (await registry()).owners[0].properties[0].registry_bedrooms is None


async def test_retracted_rental_link_cannot_display_verified_owner_on_previous_lead(monkeypatch):
    from app.crm.import_models import CrmContactList

    assessed = event(1, lead_id=None, unit_candidate_key=None)
    await install_snapshot(monkeypatch, [assessed])
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
        await owners.list_lead_imported_contacts(DB.session, lead_id="lease", organization_id="org")
        == []
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
    await install_snapshot(monkeypatch, rows)
    listed = await registry()
    clicked = await owners.get_owner_profile(DB.session, organization_id="org", owner_key="alias-1")
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
        await workspaces.list_owner_workspaces(DB.session, user_id="user", organization_id="org")
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
    await install_snapshot(
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
        await install_snapshot(monkeypatch, rows)
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

    await install_snapshot(monkeypatch, rows)
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
    return await owners.get_contact_list(DB.session, **(arguments | filters))


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
    await install_snapshot(
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
    clicked = await owners.get_owner_profile(DB.session, organization_id="org", owner_key="alias-1")
    assert clicked.highest_ownership_status == "verified_current_owner"
    listed = await registry(scope="current_owners")
    assert listed.owners[0].highest_ownership_status == clicked.highest_ownership_status
    # Someone who has sold everything is still a former owner.
    sold = await registry(scope="prior_owners")
    assert sold.owners[0].highest_ownership_status == "former_owner"


async def test_tabs_report_the_whole_portfolio_beside_the_count_in_view(monkeypatch):
    # The Current owners list counts current properties only; the panel counts everything.
    # Both carry the other number so the screens can say "1 current · 2 in total".
    await install_snapshot(
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
        ],
    )
    listed = (await registry(scope="current_owners")).owners[0]
    assert (listed.property_count, listed.total_property_count) == (1, 2)
    clicked = await owners.get_owner_profile(DB.session, organization_id="org", owner_key="alias-1")
    assert (clicked.property_count, clicked.current_property_count) == (2, 1)
    assert clicked.total_property_count is None


async def test_a_developer_side_seller_is_left_out_of_former_owners(monkeypatch):
    rows = [
        event(
            n,
            owner_key=f"signatory-{n}",
            canonical_owner_key="signatory",
            contact_name="Example Signatory",
            property_key=f"tower{n % 4}|{n}",
            property_identity=("area", f"tower{n % 4}|{n}"),
            building_name=f"Tower {n % 4}",
            unit_number=str(n),
            party_role="Seller",
            procedure_type="Complete Delayed Sell",
            assessed_status="former_owner",
            lead_id=None,
            unit_candidate_key=None,
        )
        for n in range(1, 61)
    ]
    await install_snapshot(monkeypatch, rows)
    prior = await registry(scope="prior_owners")
    assert prior.total == 0 and prior.summary.prior_owner_profiles == 0
    # Still findable, labelled for what it is.
    everyone = await registry(scope="all", search="Example Signatory")
    assert everyone.total == 1
    assert everyone.owners[0].relationship_role == "possible_intermediary"
