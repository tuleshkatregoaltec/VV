"""A reviewed source snapshot must never silently become registry verification."""

import copy
import io
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, UploadFile
from pydantic import ValidationError

from app.crm import owner_assessment, owners, source_audit
from app.crm.owner_projection import _property_identity


def payload_data():
    return {
        "schema_version": "owner-source-audit/1",
        "dataset_id": "reviewed-fixture",
        "original_filename": "reviewed.xlsx",
        "source_sha256": "a" * 64,
        "cleaned_sha256": "b" * 64,
        "references": [
            {
                "reference_id": "plot:1",
                "source_key": ["District", "Plot 1"],
                "disposition": "provisional_named_party_multiple_phones",
                "review_required": False,
                "decision_basis": "Reviewed same named buyer with several source phones.",
                "owner_candidate_groups": [[2, 3, 4]],
                "previous_nonbank_candidate_rows": [],
            }
        ],
        "rows": [
            {
                "cleaned_row_number": number,
                "original_rows": [number],
                "reference_id": "plot:1",
                "recorded_at": "2020-01-01",
                "amount_aed": "1234567.89",
                "size_sqm": "123.456789",
                "project": "District",
                "building_name": "",
                "building_number": "",
                "unit_number": "",
                "land_number": "1",
                "dm_sub_number": "2",
                "property_type": "Land",
                "party_role": "Buyer",
                "contact_name": "Named Buyer",
                "phone": phone,
                "country": "UAE",
                "source_values": ["original", number, None],
            }
            for number, phone in [(2, "+971501234567"), (3, "+971501234568"), (4, "+971501234569")]
        ],
    }


def parsed(data=None):
    return source_audit.SourceAuditPayload.model_validate_json(json.dumps(data or payload_data()))


def history_rows(payload=None):
    now = datetime.now(timezone.utc)
    claims = list(
        source_audit.source_claims(
            payload or parsed(),
            import_id=11,
            list_id=22,
            organization_id="tenant",
            now=now,
        )
    )
    return [
        {
            **claim.model_dump(),
            "id": index,
            "source_filename": "reviewed.xlsx",
            "source_list_name": "Reviewed source",
        }
        for index, claim in enumerate(claims, 1)
    ]


@pytest.mark.parametrize(
    "tamper",
    [
        "unknown_reference",
        "duplicate_cleaned_row",
        "duplicate_original_row",
        "foreign_candidate",
        "seller_candidate",
        "review_flag",
        "verified_disposition",
        "infinite_amount",
        "empty_group",
        "missing_history",
        "unexpected_label",
        "placeholder_buyer",
    ],
)
def test_untrusted_audit_cannot_change_the_partition_or_assert_verification(tamper):
    data = payload_data()
    if tamper == "unknown_reference":
        data["rows"][0]["reference_id"] = "unknown"
    elif tamper == "duplicate_cleaned_row":
        data["rows"][1]["cleaned_row_number"] = 2
    elif tamper == "duplicate_original_row":
        data["rows"][1]["original_rows"] = [2]
    elif tamper == "foreign_candidate":
        data["references"][0]["owner_candidate_groups"] = [[999]]
    elif tamper == "seller_candidate":
        data["rows"][0]["party_role"] = "Seller"
    elif tamper == "review_flag":
        data["references"][0]["review_required"] = True
    elif tamper == "verified_disposition":
        data["references"][0]["disposition"] = "verified_current_owner"
    elif tamper == "infinite_amount":
        data["rows"][0]["amount_aed"] = "NaN"
    elif tamper == "empty_group":
        data["references"][0]["owner_candidate_groups"] = [[]]
    elif tamper == "missing_history":
        extra = copy.deepcopy(data["references"][0])
        extra.update(reference_id="absent", owner_candidate_groups=[[100]])
        data["references"].append(extra)
    elif tamper == "unexpected_label":
        data["rows"][0]["ownership_status"] = "verified_current_owner"
    elif tamper == "placeholder_buyer":
        data["rows"][0]["contact_name"] = "unknown"
    with pytest.raises(ValidationError):
        parsed(data)


def test_reviewed_multiple_phone_group_keeps_all_rows_and_one_scoped_party():
    rows = history_rows()
    assert len(rows) == 3
    assert len({row["owner_key"] for row in rows}) == 1
    for row in rows:
        evidence = row["evidence"]["source_audit"]
        assert evidence["amount_aed"] == "1234567.89"
        assert evidence["size_sqm"] == "123.456789"
        assert row["latest_sale_date"] is None
        assert row["ownership_status"] == "probable_current_owner"
        assert _property_identity(row) == ("source_audit", "11:plot:1")
    snapshot = owner_assessment._source_snapshot(rows, datetime.now(timezone.utc))
    profiles = owners._assessed_profiles(snapshot.rows, snapshot=snapshot)
    assert len(profiles) == 1
    assert len(profiles[0].phone_numbers) == 3
    assert profiles[0].property_count == 1
    assert snapshot.summary.source_event_count == 3
    assert snapshot.summary.warehouse_status == "not_requested"
    assert snapshot.summary.verified_current_count == 0


def test_coowners_and_audited_scoped_references_do_not_merge():
    data = payload_data()
    data["references"][0].update(
        disposition="possible_coowners_shares_unknown",
        owner_candidate_groups=[[2], [3]],
    )
    data["rows"][1]["contact_name"] = "Second Buyer"
    # Retain an unselected historical seller without creating another owner profile.
    data["rows"][2]["party_role"] = "Seller"
    other = copy.deepcopy(data["references"][0])
    other.update(
        reference_id="plot:1:other-extent",
        owner_candidate_groups=[[5]],
        disposition="latest_recorded_buyer_candidate",
    )
    data["references"].append(other)
    extra = copy.deepcopy(data["rows"][0])
    extra.update(
        cleaned_row_number=5,
        original_rows=[5],
        reference_id=other["reference_id"],
        contact_name="Other Buyer",
        phone="",
    )
    data["rows"].append(extra)
    snapshot = owner_assessment._source_snapshot(
        history_rows(parsed(data)), datetime.now(timezone.utc)
    )
    assert len(snapshot.rows) == 4
    assert snapshot.summary.identifiable_property_count == 2
    profiles = owners._assessed_profiles(snapshot.rows, snapshot=snapshot)
    assert len(profiles) == 3
    assert sum(profile.property_count for profile in profiles) == 3
    summary = source_audit.aggregate_source_audit(snapshot.rows)
    assert summary.reference_count == 2
    assert summary.owner_candidate_reference_count == 2
    assert summary.source_row_count == 4


class MemoryCache:
    async def get(self, key):
        return None

    async def set(self, key, value, **kwargs):
        return None


async def test_source_only_assessment_and_tokens_never_request_the_warehouse(monkeypatch):
    rows = history_rows()
    monkeypatch.setattr(owner_assessment, "_recent", None)
    monkeypatch.setattr(owner_assessment, "_source_revision", AsyncMock(return_value="snapshot"))
    monkeypatch.setattr(owner_assessment, "_source_rows", AsyncMock(return_value=rows))
    monkeypatch.setattr(
        owner_assessment.owner_repository, "owner_sources_only", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(owner_assessment, "_cache_client", lambda: MemoryCache())
    warehouse = AsyncMock(side_effect=AssertionError("Source-only mode must never query warehouse"))
    monkeypatch.setattr(owner_assessment, "_warehouse_revision", warehouse)
    monkeypatch.setattr(owner_assessment, "_fresh_sales", warehouse)
    snapshot = await owner_assessment.get_owner_assessment(None, organization_id="tenant")
    assert snapshot.warehouse_status == "not_requested"
    warehouse.assert_not_called()
    from app.crm import owner_store

    monkeypatch.setattr(
        owner_store.owner_repository, "owner_sources_only", AsyncMock(return_value=True)
    )
    assert await owner_store._tokens(None, "tenant") == ("snapshot", "not_requested")
    warehouse.assert_not_called()


async def test_source_import_enforces_payload_size_before_parsing_or_database(monkeypatch):
    monkeypatch.setattr(source_audit, "MAX_SOURCE_AUDIT_BYTES", 10)
    upload = UploadFile(file=io.BytesIO(b"x" * 11), filename="audit.json")
    with pytest.raises(HTTPException) as error:
        await source_audit.process_source_audit_import(
            None,
            upload=upload,
            name="",
            user_id="u",
            organization_id="tenant",
        )
    assert error.value.status_code == 413


def test_every_reviewed_disposition_retains_history_and_reconciles_reference_partition():
    from typing import get_args

    data = payload_data()
    template = data["rows"][0]
    data["rows"], data["references"] = [], []
    for index, disposition in enumerate(get_args(source_audit.Disposition), 2):
        reference = f"ref:{index}"
        row = {
            **template,
            "cleaned_row_number": index,
            "original_rows": [index],
            "reference_id": reference,
        }
        data["rows"].append(row)
        data["references"].append(
            {
                "reference_id": reference,
                "source_key": [reference],
                "disposition": disposition,
                "review_required": disposition in source_audit.REVIEW_DISPOSITIONS,
                "decision_basis": "Reviewed fixture disposition.",
                "owner_candidate_groups": [[index]]
                if disposition in source_audit.CANDIDATE_DISPOSITIONS
                else [],
                "previous_nonbank_candidate_rows": [],
            }
        )
    payload = parsed(data)
    summary = source_audit.audit_summary(payload)
    assert summary.reference_count == 11
    assert summary.owner_candidate_reference_count == 5
    assert summary.bank_reference_count == 1
    assert summary.review_reference_count == 3
    assert summary.excluded_nonownership_reference_count == 1
    assert summary.excluded_scope_reference_count == 1
    rows = history_rows(payload)
    snapshot = owner_assessment._source_snapshot(rows, datetime.now(timezone.utc))
    assert snapshot.summary.source_event_count == 11
    assert sum(row["assessed_status"] == "probable_current_owner" for row in rows) == 5
    assert source_audit.aggregate_source_audit(rows) == summary


async def test_mixed_imports_send_only_ordinary_claims_to_registry(monkeypatch):
    source_rows = history_rows()
    normal = {
        **copy.deepcopy(source_rows[0]),
        "id": 100,
        "import_id": 99,
        "property_key": "tower|101",
        "building_name": "Tower",
        "unit_number": "101",
        "evidence": {},
        "party_role": "Buyer",
        "ownership_status": "unit_linked_unverified",
        "owner_key": "ordinary",
        "match_reason": "Original unverified source",
    }
    monkeypatch.setattr(
        owner_assessment, "_source_rows", AsyncMock(return_value=[*source_rows, normal])
    )
    checked = []

    async def ordinary_only(valid):
        checked.extend(row["id"] for row, _ in valid)
        return {}

    monkeypatch.setattr(owner_assessment, "_fresh_sales", ordinary_only)
    snapshot = await owner_assessment._build(None, "tenant")
    assert checked == [100]
    assert len(snapshot.rows) == 4
    assert all(
        row["assessed_status"] == "probable_current_owner"
        for row in snapshot.rows
        if source_audit.source_audit_for_row(row)
    )


async def test_import_is_atomic_and_keeps_reviewed_mapping_without_enrichment(monkeypatch):
    class Database:
        def __init__(self):
            self.records = []
            self.commit = AsyncMock()
            self.rollback = AsyncMock()

        def add(self, record):
            record.id = len(self.records) + 1
            self.records.append(record)

        def add_all(self, records):
            for record in records:
                self.add(record)

        async def flush(self):
            pass

    db = Database()
    monkeypatch.setattr(
        source_audit.import_repository, "find_import_by_digest", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        source_audit.import_repository,
        "find_import_list",
        AsyncMock(side_effect=lambda *args: db.records[1]),
    )
    response = await source_audit._execute_source_audit_import(
        db,
        upload=UploadFile(
            file=io.BytesIO(json.dumps(payload_data()).encode()), filename="audit.json"
        ),
        name="Reviewed import",
        user_id="user",
        organization_id="tenant",
    )
    assert response.status == "completed"
    assert response.summary.source_audit.source_row_count == 3
    assert len(db.records) == 5  # Import + list + every retained source row.
    assert db.records[0].mapping["mode"] == "source_only"
    assert db.records[0].mapping["source_sha256"] == "a" * 64
    assert len(db.records[0].sha256) == 64
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    # Repeating the exact payload returns its persisted import before adding rows.
    monkeypatch.setattr(
        source_audit.import_repository,
        "find_import_by_digest",
        AsyncMock(return_value=db.records[0]),
    )
    repeated = await source_audit._execute_source_audit_import(
        db,
        upload=UploadFile(
            file=io.BytesIO(json.dumps(payload_data()).encode()), filename="audit.json"
        ),
        name="Renamed request",
        user_id="user",
        organization_id="tenant",
    )
    assert repeated.id == response.id
    assert len(db.records) == 5
    db.commit.assert_awaited_once()


def test_plot_reference_and_source_area_remain_visible_without_inventing_a_unit():
    data = payload_data()
    for row in data["rows"]:
        row["source_values"] = [None, None, "Master District"] + [None] * 14
    rows = history_rows(parsed(data))
    assert all(row["area_name"] == "Master District" and row["unit_number"] == "" for row in rows)
    snapshot = owner_assessment._source_snapshot(rows, datetime.now(timezone.utc))
    assert snapshot.summary.legacy_source_event_count == 0
    profile = owners._assessed_profiles(snapshot.rows, snapshot=snapshot)[0]
    reference = profile.properties[0].source_reference
    assert reference.reference_id == "plot:1"
    assert reference.land_number == "1"
    assert reference.dm_sub_number == "2"
    assert reference.size_sqm == "123.456789"
    assert profile.properties[0].unit_number == ""


def matched_history_rows():
    rows = history_rows()
    rows.append(copy.deepcopy(rows[0]))
    for index, row in enumerate(rows):
        row["id"] = index + 1
        audit = row["evidence"]["source_audit"]
        audit["reference_id"] = f"plot:{index + 1}"
        audit["owner_candidate"] = index == 0
        audit["transaction_match"] = {
            "status": "matched" if index < 2 else "excluded",
            "property_key": f"registry-property:{index + 1}" if index < 2 else None,
            "owner_category": ["current", "former", None, None][index],
            "canonical_owner_key": "supported-owner" if index < 2 else f"excluded:{index}",
            "latest_sale_date": "2024-01-01",
            "later_sale_date": "2024-01-01" if index == 1 else None,
            "reason": "Supported acquisition followed by sale"
            if index == 1
            else "Captured evidence",
        }
        if index == 2:
            row["party_role"] = "Seller"
            row["contact_name"] = "Seller without acquisition"
        if index == 3:
            row["contact_name"] = "Example Bank"
    return rows


def test_matched_history_exposes_supported_former_and_preserves_reference_denominator():
    snapshot = owner_assessment._source_snapshot(matched_history_rows(), datetime.now(timezone.utc))
    profiles = owners._assessed_profiles(snapshot.rows, snapshot=snapshot)
    assert snapshot.warehouse_status == "available"
    assert snapshot.summary.owner_property_count == 2
    assert snapshot.summary.unresolved_count == 0
    assert snapshot.summary.source_event_count == 4
    assert len(profiles) == 1
    assert profiles[0].property_count == 2
    assert {item.ownership_status for item in profiles[0].properties} == {
        "probable_current_owner",
        "former_owner",
    }
    assert all(item.ownership_status != "verified_current_owner" for item in profiles[0].properties)
    summary = source_audit.aggregate_source_audit(snapshot.rows)
    assert summary.mode == "source_transaction_matched"
    assert summary.reference_count == 4
    assert summary.matched_reference_count == summary.matched_registry_property_count == 2
    assert summary.current_owner_association_count == summary.former_owner_association_count == 1
    assert summary.excluded_match_reference_count == 2


async def test_import_detail_uses_committed_matching_summary_without_losing_source_partition(
    monkeypatch,
):
    from app.crm import imports
    from app.crm.import_models import CrmContactImport

    original = source_audit.audit_summary(parsed()).model_dump()
    record = CrmContactImport(
        id=11,
        organization_id="tenant",
        created_by_user_id="user",
        name="Reviewed workbook",
        created_at=datetime.now(timezone.utc),
        original_filename="reviewed.xlsx",
        sha256="a" * 64,
        size_bytes=123,
        status="completed",
        mapping={"mode": "source_transaction_matched"},
        summary={
            "source_audit": original,
            "transaction_matching": {
                "matched_reference_count": 1,
                "matched_property_count": 1,
                "unmatched_reference_count": 0,
                "ambiguous_reference_count": 0,
                "excluded_reference_count": 0,
                "current_association_count": 1,
                "former_association_count": 2,
            },
        },
    )
    monkeypatch.setattr(imports.import_repository, "find_import_list", AsyncMock(return_value=None))
    response = await imports._import_response(None, record)
    assert response.summary.source_audit.mode == "source_transaction_matched"
    assert response.summary.source_audit.matched_reference_count == 1
    assert response.summary.source_audit.matched_registry_property_count == 1
    assert response.summary.source_audit.former_owner_association_count == 2
    assert response.summary.source_audit.reference_count == original["reference_count"]
    assert response.summary.source_audit.disposition_counts == original["disposition_counts"]
    assert record.summary["source_audit"]["mode"] == "source_only"


def test_former_with_anchored_acquisition_but_only_workbook_successor_stays_unverified():
    rows = matched_history_rows()
    match = rows[1]["evidence"]["source_audit"]["transaction_match"]
    match.update(acquisition_sale_keys=["acquisition"], later_sale_date=None)
    snapshot = owner_assessment._source_snapshot(rows, datetime.now(timezone.utc))
    profiles = owners._assessed_profiles(snapshot.rows, snapshot=snapshot)
    former = next(
        p for owner in profiles for p in owner.properties if p.ownership_status == "former_owner"
    )
    assert former.source_reference.transaction_match_status == "matched"
    assert former.source_reference.ownership_evidence_basis == "workbook_only"
