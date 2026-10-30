"""The persisted history projection is part of the owner matching contract."""

import io
from copy import deepcopy
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import UploadFile

from app.crm import imports, owner_queries, owner_repository
from app.crm.owner_assessment import _candidate, get_owner_assessment
from app.crm.ownership import _amount_match_source, _canonical_source_location, _source_size_decimal


async def test_upload_history_roundtrip_retains_raw_policy_and_decimal_evidence(
    pg_session, monkeypatch
):
    monkeypatch.setattr(imports, "_llm_mapping", AsyncMock(side_effect=lambda profile: profile))
    monkeypatch.setattr(imports, "prepare_file_context", AsyncMock())
    source_frames = {}
    source_locations = {}
    location_fields = ("area_name", "project_name", "building_name", "unit_number", "property_type")

    async def capture_source_frames(_db, *, candidates, **_kwargs):
        source_frames.update(
            {row.source_row_number: deepcopy(_amount_match_source(row)) for row in candidates}
        )
        source_locations.update(
            {
                row.source_row_number: {
                    field: _canonical_source_location(row).get(field) or ""
                    for field in location_fields
                }
                for row in candidates
            }
        )

    monkeypatch.setattr(imports, "_enrich_workspaces", capture_source_frames)
    monkeypatch.setattr(imports, "_rental_evidence", AsyncMock(return_value={}))
    monkeypatch.setattr(imports, "save_drop_log", AsyncMock(return_value=True))
    monkeypatch.setattr(
        owner_queries,
        "fetch_registry_places",
        AsyncMock(
            return_value=[
                {
                    "building_label": "Alpha Tower",
                    "location_id": 1,
                    "project_label": "Alpha",
                    "area_label": "Business Bay",
                    "building_key": "alphatower",
                    "area_key": "businessbaylegal",
                    "match_rank": 1,
                }
            ]
        ),
    )
    monkeypatch.setattr(owner_queries, "fetch_canonical_building_keys", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        owner_queries, "fetch_assessment_building_aliases", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        owner_queries, "fetch_assessment_source_fingerprint", AsyncMock(return_value="test-release")
    )
    targets = [
        dict(
            sale_key=f"sale-{unit}",
            sale_amount_aed="1000002.25",
            unit_number=str(unit),
            unit_key=str(unit),
            building_name="Alpha Tower",
            project_name="Alpha",
            area_name="Business Bay",
            property_type="Apartment",
            transaction_date=date(2024, 1, 1),
            size_sqft="1076.391041671",
        )
        for unit in range(101, 113)
    ]
    later = targets[0] | {
        "sale_key": "later",
        "sale_amount_aed": "2000000",
        "transaction_date": date(2025, 1, 1),
    }
    wrong_project = targets[0] | {
        "sale_key": "wrong-project",
        "unit_number": "901",
        "unit_key": "901",
        "building_name": "Tower 1",
        "project_name": "Beta",
    }
    conflicting_villa = targets[0] | {
        "sale_key": "wrong-villa",
        "unit_number": "305",
        "unit_key": "305",
        "building_name": "Sun",
        "project_name": "Arabian Ranches 3",
        "area_name": "Arabian Ranches 3",
        "property_type": "Villa",
    }
    registry = [*targets, later, wrong_project, conflicting_villa]
    monkeypatch.setattr(
        owner_queries, "fetch_transaction_signatures", AsyncMock(return_value=registry)
    )
    monkeypatch.setattr(
        owner_queries, "fetch_property_identity_candidates", AsyncMock(return_value=registry)
    )
    monkeypatch.setattr(owner_queries, "fetch_unit_sales", AsyncMock(return_value=registry))
    monkeypatch.setattr(owner_queries, "fetch_assessment_sales", AsyncMock(return_value=registry))
    lines = [
        "NameEn,BuildingNameEn,Project,Master Project,UnitNumber,Building No,PropertyTypeEn,Regis,ProcedureValue,ProcedurePartyTypeNameEn,ProcedureNameEn,Size"
    ]
    lines += [
        f"Example {unit},Alpha Tower,Alpha,Business Bay Legal,{unit},,Apartment,2024-01-01,1000000.50,Buyer,Sale,100"
        for unit in range(101, 113)
    ]
    lines += [
        "Project Review,Tower 1,Alpha,Business Bay,901,,Apartment,2024-01-01,1000000.50,Buyer,Sale,100",
        "Villa Review,Sun,Arabian Ranches 3,Arabian Ranches 3,305,R3 Sun-V-302,Land,2024-01-01,1000000.50,Buyer,Sale,100",
    ]
    org = str(uuid4())
    response = await imports.process_contact_import(
        pg_session,
        upload=UploadFile(
            file=io.BytesIO("\n".join(lines).encode()), filename="new-owner-sheet.csv"
        ),
        name="New owners",
        user_id=str(uuid4()),
        organization_id=org,
    )
    assert response.status == "completed" and response.summary.candidate_rows == 14
    pg_session.expire_all()
    rows = await owner_repository.list_owner_history_rows(pg_session, organization_id=org)
    assert len(rows) == 14
    parsed = [_candidate(row) for row in rows]
    for row in parsed:
        assert _amount_match_source(row) == source_frames[row.source_row_number]
        assert {
            field: _canonical_source_location(row).get(field) or "" for field in location_fields
        } == source_locations[row.source_row_number]
    qualified = [
        row for row in parsed if row.unit_number in {str(unit) for unit in range(101, 113)}
    ]
    assert len(qualified) == 12
    for row in qualified:
        assert _amount_match_source(row)["amount_aed"] == "1000000.50"
        assert row.transaction_price_aed == 1000000  # Legacy BIGINT remains display-only.
        assert _source_size_decimal(row) == Decimal("1076.39104167100")
        assert row.evidence["inferred_size_unit"]["independent_units"] == 11
        assert row.evidence["original_identifiers"]["unit_number"] == row.unit_number
        assert (
            row.evidence["amount_first_match"]["selected_event_key"]
            == f"sale:sale-{row.unit_number}"
        )
        assert row.evidence["owner_match_policy"] == "owner-qualified-1"
        assert row.evidence["source_area_field"] == "master_project"
        assert (
            row.evidence["source_registry_location_resolution"]["resolved_fields"]["area_name"]
            == "Business Bay"
        )
    villa = next(
        row
        for row in parsed
        if row.evidence["original_identifiers"].get("building_number") == "R3 Sun-V-302"
    )
    assert villa.evidence["original_identifiers"]["unit_number"] == "305"
    assert villa.evidence["original_property_fields"]["property_type"] == "Land"
    assert villa.evidence["amount_first_match"]["status"] == "unmatched"
    snapshot = await get_owner_assessment(pg_session, organization_id=org)
    by_unit = {row["unit_number"]: row for row in snapshot.rows}
    assert by_unit["101"]["assessed_status"] == "former_owner"
    assert all(
        by_unit[str(unit)]["assessed_status"] == "verified_current_owner"
        for unit in range(102, 113)
    )
    assert by_unit["901"]["project_name"] == "Alpha"
    assert by_unit["901"]["assessed_status"] not in {
        "verified_current_owner",
        "probable_current_owner",
        "former_owner",
    }
    assert by_unit["305"]["assessed_status"] not in {
        "verified_current_owner",
        "probable_current_owner",
        "former_owner",
    }
