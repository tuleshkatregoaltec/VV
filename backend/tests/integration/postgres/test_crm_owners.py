from datetime import datetime, timezone
from uuid import uuid4

from app.crm import imports, owners, workspaces
from app.crm.import_models import (
    CrmContactImport,
    CrmContactList,
    CrmOwnerBulkUpdate,
    CrmPropertyContactClaim,
)
from app.crm.models import CrmSavedLead


async def test_registry_excludes_invalid_property_keys_and_import_delete_preserves_agent_work(
    pg_session,
):
    now = datetime.now(timezone.utc)
    org, user = str(uuid4()), str(uuid4())
    record = CrmContactImport(
        organization_id=org,
        created_by_user_id=user,
        name="Owner audit",
        original_filename="owners.csv",
        sha256=uuid4().hex,
        size_bytes=100,
        status="completed",
        mapping={"sheets": []},
        created_at=now,
    )
    pg_session.add(record)
    await pg_session.flush()
    contact_list = CrmContactList(
        organization_id=org,
        created_by_user_id=user,
        source_import_id=record.id,
        name="Owner audit",
        created_at=now,
        updated_at=now,
    )
    pg_session.add(contact_list)
    await pg_session.flush()
    for row, status in enumerate(["verified_current_owner", "former_owner"], 1):
        pg_session.add(
            CrmPropertyContactClaim(
                organization_id=org,
                import_id=record.id,
                list_id=contact_list.id,
                source_sheet="Owners",
                source_row_number=row,
                row_fingerprint=str(row),
                owner_key="owner",
                property_key="property",
                contact_name="Owner Example",
                ownership_status=status,
                confidence_score=95,
                match_reason="Registry evidence",
                evidence={"legacy": {"arbitrary": [1, None, "retained"]}},
                created_at=now,
                updated_at=now,
            )
        )
    saved = CrmSavedLead(
        user_id=user,
        organization_id=org,
        lead_id="lead",
        unit_candidate_key="candidate",
        snapshot={"legacy": {"retained": True}},
        created_at=now,
        updated_at=now,
    )
    pg_session.add(saved)
    await pg_session.commit()
    arguments = dict(
        organization_id=org,
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
    registry = await owners.get_owner_registry(pg_session, **arguments)
    assert registry.total == 1
    assert registry.owners[0].property_count == 0
    assert registry.owners[0].properties == []
    assert registry.owners[0].history_summary.invalid_identity_source_count == 2
    assert registry.summary.prior_owner_profiles == 0
    assert registry.summary.needs_review_profiles == 1
    assert (
        await owners.get_owner_registry(
            pg_session, **{**arguments, "organization_id": str(uuid4())}
        )
    ).total == 0
    await workspaces.bulk_update_owner_workspaces(
        pg_session,
        payload=CrmOwnerBulkUpdate(
            owner_keys=["owner"], pipeline_status="contacted", note="Keep agent note"
        ),
        user_id=user,
        organization_id=org,
    )
    renamed = await imports.rename_contact_import(
        pg_session, import_id=record.id, name="Renamed owner audit", organization_id=org
    )
    assert renamed.name == "Renamed owner audit"
    saved_id = saved.id
    await imports.delete_contact_import(pg_session, import_id=record.id, organization_id=org)
    pg_session.expire_all()
    assert await imports.list_contact_imports(pg_session, organization_id=org) == []
    assert (await owners.get_owner_registry(pg_session, **arguments)).total == 0
    remaining = await workspaces.list_owner_workspaces(
        pg_session, user_id=user, organization_id=org
    )
    assert remaining[0].pipeline_status == "contacted"
    assert remaining[0].last_note == "Keep agent note"
    assert (await pg_session.get(CrmSavedLead, saved_id)).snapshot == {"legacy": {"retained": True}}


async def test_registry_filters_owners_by_unit_count_and_next_lease_end(pg_session, monkeypatch):
    """The Owners tabs '3+ units' and 'Next event ≤ 90 days' page through the whole file."""
    from datetime import date, timedelta

    async def sales(candidates):
        return {
            candidate.property_key: [
                {
                    "sale_key": f"sale-{candidate.unit_number}",
                    "transaction_date": date(2025, 1, 1),
                    "sale_amount_aed": 1_000_000,
                }
            ]
            for _, candidate in candidates
        }

    monkeypatch.setattr("app.crm.owner_assessment._fresh_sales", sales)
    now = datetime.now(timezone.utc)
    today = date.today()
    org, user = str(uuid4()), str(uuid4())
    record = CrmContactImport(
        organization_id=org,
        created_by_user_id=user,
        name="Tabs",
        original_filename="tabs.csv",
        sha256=uuid4().hex,
        size_bytes=100,
        status="completed",
        mapping={"sheets": []},
        created_at=now,
    )
    pg_session.add(record)
    await pg_session.flush()
    contact_list = CrmContactList(
        organization_id=org,
        created_by_user_id=user,
        source_import_id=record.id,
        name="Tabs",
        created_at=now,
        updated_at=now,
    )
    pg_session.add(contact_list)
    await pg_session.flush()
    rows = [
        # (owner, property, lease end)
        ("three_units", "p1", None),
        ("three_units", "p2", None),
        ("three_units", "p3", None),
        ("lease_soon", "p4", today + timedelta(days=30)),
        ("lease_later", "p5", today + timedelta(days=120)),
    ]
    for row, (owner_key, property_key, lease_end) in enumerate(rows, 1):
        pg_session.add(
            CrmPropertyContactClaim(
                organization_id=org,
                import_id=record.id,
                list_id=contact_list.id,
                source_sheet="Owners",
                source_row_number=row,
                row_fingerprint=str(row),
                owner_key=owner_key,
                property_key=f"tower|{row}",
                area_name="Business Bay",
                building_name="Tower",
                unit_number=str(row),
                phone_primary={
                    "three_units": "+971501234561",
                    "lease_soon": "+971501234562",
                    "lease_later": "+971501234563",
                }[owner_key],
                party_role="Buyer",
                procedure_type="Sale",
                transaction_date=date(2025, 1, 1),
                transaction_price_aed=1_000_000,
                lead_id=f"lease-{row}",
                unit_candidate_key=f"unit-{row}",
                contact_name=owner_key,
                ownership_status="verified_current_owner",
                confidence_score=95,
                match_reason="Registry evidence",
                lease_end=lease_end,
                evidence={},
                created_at=now,
                updated_at=now,
            )
        )
    await pg_session.commit()
    arguments = dict(
        organization_id=org,
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

    everyone = await owners.get_owner_registry(pg_session, **arguments)
    assert everyone.total == 3

    multi = await owners.get_owner_registry(pg_session, **arguments, min_properties=3)
    assert multi.total == 1
    assert [o.owner_key for o in multi.owners] == ["three_units"]

    soon = await owners.get_owner_registry(pg_session, **arguments, next_event_days=90)
    assert soon.total == 1
    assert [o.owner_key for o in soon.owners] == ["lease_soon"]


async def test_assessment_projection_and_revision_follow_import_metadata_without_claim_edits(
    pg_session,
):
    """Correcting a declared size unit must invalidate an already cached source projection."""
    from app.crm import owner_assessment, owner_repository

    now = datetime.now(timezone.utc)
    org, user = str(uuid4()), str(uuid4())
    source = CrmContactImport(
        organization_id=org,
        created_by_user_id=user,
        name="Synthetic projection",
        original_filename="synthetic.csv",
        sha256=uuid4().hex,
        size_bytes=100,
        status="completed",
        mapping={
            "resolver_version": "before",
            "sheets": [{"sheet_name": "Owners", "field_map": {"size_sqft": "Size"}}],
        },
        created_at=now,
    )
    pg_session.add(source)
    await pg_session.flush()
    contact_list = CrmContactList(
        organization_id=org,
        created_by_user_id=user,
        source_import_id=source.id,
        name="Synthetic list",
        created_at=now,
        updated_at=now,
    )
    pg_session.add(contact_list)
    await pg_session.flush()
    context = {"locations": ["Synthetic Tower"], "nested": [None, {"flag": True}]}
    claim = CrmPropertyContactClaim(
        organization_id=org,
        import_id=source.id,
        list_id=contact_list.id,
        source_sheet="Owners",
        source_row_number=2,
        row_fingerprint="synthetic",
        owner_key="synthetic-owner",
        property_key="synthetictower|101",
        contact_name="Synthetic Buyer",
        building_name="Synthetic Tower",
        unit_number="101",
        ownership_status="unmatched",
        confidence_score=20,
        match_reason="Synthetic",
        evidence={
            "resolver_version": "claim-version",
            "source_fields": {"size_sqft": "92.90304", "unused_private_field": "excluded"},
            "file_context": context,
            "unit_hierarchy_resolution": {"confidence": 75},
            "duplicate_count": 2,
            "event_family": "sale",
        },
        created_at=now,
        updated_at=now,
    )
    pg_session.add(claim)
    await pg_session.commit()
    first_revision = await owner_assessment._source_revision(pg_session, org)
    first = (await owner_assessment._source_rows(pg_session, org, first_revision))[0]
    assert first["evidence"]["file_context"] == context
    assert first["evidence"]["unit_hierarchy_resolution"] == {"confidence": 75}
    assert first["evidence"]["duplicate_count"] == 2
    assert first["evidence"]["source_size_unit"] == "unknown"
    assert "unused_private_field" not in first["evidence"]["source_fields"]
    assert first["claim_resolver_version"] == "claim-version"
    source.mapping = {
        "resolver_version": "after",
        "sheets": [{"sheet_name": "Owners", "field_map": {"size_sqft": "AreaSqm"}}],
    }
    source.original_filename = "corrected-synthetic.csv"
    await pg_session.commit()
    second_revision = await owner_assessment._source_revision(pg_session, org)
    assert second_revision != first_revision
    second = (await owner_assessment._source_rows(pg_session, org, second_revision))[0]
    assert second["evidence"]["source_size_unit"] == "sqm"
    assert second["source_filename"] == "corrected-synthetic.csv"
    assert second["import_resolver_version"] == "after"
    assert claim.updated_at == now
    contact_list.name = "Renamed synthetic list"
    await pg_session.commit()
    third_revision = await owner_assessment._source_revision(pg_session, org)
    assert third_revision != second_revision
    third = (await owner_repository.list_owner_history_rows(pg_session, organization_id=org))[0]
    assert third["source_list_name"] == "Renamed synthetic list"
    from datetime import timedelta

    newer = CrmPropertyContactClaim(
        **{
            **claim.model_dump(exclude={"id"}),
            "row_fingerprint": "synthetic-newer",
            "source_row_number": 3,
            "updated_at": now + timedelta(hours=1),
        }
    )
    pg_session.add(newer)
    await pg_session.commit()
    before_older_edit = await owner_assessment._source_revision(pg_session, org)
    await owner_assessment._source_rows(pg_session, org, before_older_edit)
    claim.confidence_score = 21
    await pg_session.commit()
    after_older_edit = await owner_assessment._source_revision(pg_session, org)
    assert after_older_edit != before_older_edit
    assert claim.updated_at == now < newer.updated_at
    refreshed = await owner_assessment._source_rows(pg_session, org, after_older_edit)
    assert next(row for row in refreshed if row["id"] == claim.id)["confidence_score"] == 21
    await pg_session.delete(claim)
    await pg_session.commit()
    assert await owner_assessment._source_revision(pg_session, org) != after_older_edit
    await pg_session.delete(newer)
    await pg_session.commit()
    assert await owner_repository.list_owner_history_rows(pg_session, organization_id=org) == []
