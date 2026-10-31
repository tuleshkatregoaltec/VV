"""Reviewed source snapshots: preserve decisions without requesting registry evidence."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException, UploadFile
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.exc import IntegrityError

from app.crm import import_repository
from app.crm.import_models import (
    CrmContactImport,
    CrmContactImportResponse,
    CrmContactImportSummary,
    CrmContactList,
    CrmPropertyContactClaim,
    CrmSourceAuditSummary,
)

MAX_SOURCE_AUDIT_BYTES = 100 * 1024 * 1024
Disposition = Literal[
    "latest_recorded_buyer_candidate",
    "probable_owner_with_possible_financing",
    "possible_mortgage_or_bank_acquisition",
    "same_latest_party_buyer_seller",
    "excluded_whole_building_or_project_context",
    "property_extent_requires_review",
    "excluded_possible_nonownership_transaction",
    "latest_seller_only",
    "provisional_named_party_multiple_phones",
    "latest_buyer_candidate_rounding_variants",
    "possible_coowners_shares_unknown",
]
CANDIDATE_DISPOSITIONS = {
    "latest_recorded_buyer_candidate",
    "probable_owner_with_possible_financing",
    "provisional_named_party_multiple_phones",
    "latest_buyer_candidate_rounding_variants",
    "possible_coowners_shares_unknown",
}
REVIEW_DISPOSITIONS = {
    "same_latest_party_buyer_seller",
    "property_extent_requires_review",
    "latest_seller_only",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SourceAuditReference(_StrictModel):
    reference_id: str = Field(min_length=1, max_length=200)
    source_key: list[str] = Field(min_length=1, max_length=20)
    disposition: Disposition
    review_required: StrictBool
    decision_basis: str = Field(min_length=1, max_length=4000)
    owner_candidate_groups: list[list[StrictInt]]
    previous_nonbank_candidate_rows: list[StrictInt]


class SourceAuditRow(_StrictModel):
    cleaned_row_number: int = Field(gt=0, strict=True)
    original_rows: list[StrictInt] = Field(min_length=1)
    reference_id: str = Field(min_length=1, max_length=200)
    recorded_at: date
    amount_aed: str = Field(max_length=100)
    size_sqm: str | None = Field(max_length=100)
    project: str = Field(max_length=1000)
    building_name: str = Field(max_length=1000)
    building_number: str = Field(max_length=200)
    unit_number: str = Field(max_length=200)
    land_number: str = Field(max_length=200)
    dm_sub_number: str = Field(max_length=200)
    property_type: str = Field(max_length=200)
    party_role: str = Field(max_length=200)
    contact_name: str = Field(max_length=1000)
    phone: str = Field(max_length=200)
    country: str = Field(max_length=200)
    source_values: list[str | int | float | bool | None] = Field(max_length=200)

    @field_validator("amount_aed", "size_sqm")
    @classmethod
    def finite_decimal(cls, value):
        if value is None:
            return value
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Source amounts and sizes must be decimal strings") from exc
        if not number.is_finite():
            raise ValueError("Source amounts and sizes must be finite")
        return value


class SourceAuditPayload(_StrictModel):
    schema_version: Literal["owner-source-audit/1"]
    dataset_id: str = Field(min_length=1, max_length=200)
    original_filename: str = Field(min_length=1, max_length=1000)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cleaned_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    references: list[SourceAuditReference] = Field(min_length=1, max_length=100000)
    rows: list[SourceAuditRow] = Field(min_length=1, max_length=250000)

    @model_validator(mode="after")
    def consistent_partition(self):
        references = {ref.reference_id: ref for ref in self.references}
        rows = {row.cleaned_row_number: row for row in self.rows}
        if len(references) != len(self.references) or len(rows) != len(self.rows):
            raise ValueError("Duplicate reference or cleaned row identifier")
        original_rows: set[int] = set()
        observed: set[str] = set()
        for row in self.rows:
            if row.reference_id not in references:
                raise ValueError("A source row refers to an unknown reference")
            observed.add(row.reference_id)
            for number in row.original_rows:
                if type(number) is not int or number <= 0 or number in original_rows:
                    raise ValueError("Original row identifiers must be positive and unique")
                original_rows.add(number)
        if observed != references.keys():
            raise ValueError("Every reference must retain source history")
        for ref in self.references:
            if ref.review_required != (ref.disposition in REVIEW_DISPOSITIONS):
                raise ValueError("Review flag contradicts reference disposition")
            if bool(ref.owner_candidate_groups) != (ref.disposition in CANDIDATE_DISPOSITIONS):
                raise ValueError("Only owner candidate references may select owner groups")
            selected: set[int] = set()
            for group in ref.owner_candidate_groups:
                if not group:
                    raise ValueError("Owner candidate groups cannot be empty")
                for number in group:
                    row = rows.get(number)
                    if type(number) is not int or number in selected or not row:
                        raise ValueError("Owner candidate rows must exist and be unique")
                    if row.reference_id != ref.reference_id or row.party_role.casefold() != "buyer":
                        raise ValueError("Owner candidates must be buyer rows of their reference")
                    if row.contact_name.strip().casefold() in {"", "unknown", "none", "n/a", "-"}:
                        raise ValueError("Owner candidates must name a source party")
                    selected.add(number)
            previous: set[int] = set()
            for number in ref.previous_nonbank_candidate_rows:
                row = rows.get(number)
                if type(number) is not int or number in previous or not row:
                    raise ValueError("Previous candidate rows must exist and be unique")
                if row.reference_id != ref.reference_id or row.party_role.casefold() != "buyer":
                    raise ValueError("Previous candidates must be buyer rows of their reference")
                previous.add(number)
        return self


def audit_summary(payload: SourceAuditPayload) -> CrmSourceAuditSummary:
    counts = Counter(ref.disposition for ref in payload.references)
    return CrmSourceAuditSummary(
        import_count=1,
        reference_count=len(payload.references),
        owner_candidate_reference_count=sum(counts[key] for key in CANDIDATE_DISPOSITIONS),
        bank_reference_count=counts["possible_mortgage_or_bank_acquisition"],
        excluded_nonownership_reference_count=counts["excluded_possible_nonownership_transaction"],
        review_reference_count=sum(counts[key] for key in REVIEW_DISPOSITIONS),
        excluded_scope_reference_count=counts["excluded_whole_building_or_project_context"],
        source_row_count=len(payload.rows),
        disposition_counts=dict(counts),
    )


def source_audit_for_row(row: dict[str, Any]) -> dict[str, Any] | None:
    return row.get("source_audit") or (row.get("evidence") or {}).get("source_audit")


def source_claims(payload, *, import_id, list_id, organization_id, now):
    from app.crm.identity import _normalize_phone, _owner_key

    references = {ref.reference_id: ref for ref in payload.references}
    source_rows = {row.cleaned_row_number: row for row in payload.rows}
    group_keys = {}
    for ref in payload.references:
        scope = f"source-audit:{import_id}:{ref.reference_id}"
        for index, group in enumerate(ref.owner_candidate_groups):
            representative = source_rows[group[0]]
            phone = next(
                (
                    _normalize_phone(source_rows[number].phone)
                    for number in group
                    if _normalize_phone(source_rows[number].phone)
                ),
                None,
            )
            key = _owner_key(
                contact_name=representative.contact_name,
                phone_primary=phone,
                phone_alternate=None,
                email_primary=None,
                property_key=scope,
            )
            if (
                ref.disposition == "provisional_named_party_multiple_phones"
                or len(ref.owner_candidate_groups) > 1
            ):
                key = hashlib.sha256(f"{scope}:group:{index}".encode()).hexdigest()
            for number in group:
                group_keys[number] = key
    groups = {
        number: f"group:{index}"
        for ref in payload.references
        for index, group in enumerate(ref.owner_candidate_groups)
        for number in group
    }
    for row in payload.rows:
        ref = references[row.reference_id]
        group = groups.get(row.cleaned_row_number)
        scope = f"source-audit:{import_id}:{row.reference_id}"
        # Group membership comes only from the reviewed mapping, never from shared phones.
        owner_token = group or f"history:{row.cleaned_row_number}"
        owner_key = (
            group_keys.get(row.cleaned_row_number)
            or hashlib.sha256(f"{scope}:{owner_token}".encode()).hexdigest()
        )
        candidate = group is not None
        reason = (
            "Reviewed source-only owner candidate, as of the supplied snapshot; "
            "DXBI/registry ownership has not been checked. "
            if candidate
            else "Source history retained without a current-owner claim. "
        ) + ref.decision_basis
        amount = Decimal(row.amount_aed)
        legacy_amount = int(amount) if -(2**63) <= amount < 2**63 else None
        evidence = {
            "resolver_version": payload.schema_version,
            "event_family": "source_record",
            "source_audit": {
                "mode": "source_only",
                "dataset_id": payload.dataset_id,
                "reference_id": ref.reference_id,
                "source_key": ref.source_key,
                "disposition": ref.disposition,
                "review_required": ref.review_required,
                "decision_basis": ref.decision_basis,
                "owner_candidate": candidate,
                "candidate_group": group,
                "canonical_owner_key": owner_key,
                "original_rows": row.original_rows,
                "previous_nonbank_candidate_rows": ref.previous_nonbank_candidate_rows,
                "amount_aed": row.amount_aed,
                "size_sqm": row.size_sqm,
                "source_values": row.source_values,
                "building_number": row.building_number,
                "land_number": row.land_number,
                "dm_sub_number": row.dm_sub_number,
                "country": row.country,
            },
            "source_fields": {"size_sqm": row.size_sqm, "property_type": row.property_type},
            "source_size_unit": "sqm",
            "source_identifiers": {
                "building_number": row.building_number,
                "unit_number": row.unit_number,
                "land_number": row.land_number,
                "dm_sub_number": row.dm_sub_number,
            },
        }
        yield CrmPropertyContactClaim(
            organization_id=organization_id,
            import_id=import_id,
            list_id=list_id,
            source_sheet="Reviewed source",
            source_row_number=row.cleaned_row_number,
            row_fingerprint=hashlib.sha256(
                f"{scope}:{row.cleaned_row_number}".encode()
            ).hexdigest(),
            owner_key=owner_key,
            property_key=scope,
            contact_name=row.contact_name,
            phone_primary=row.phone.strip() or None,
            area_name=str(row.source_values[2] or "") if len(row.source_values) >= 3 else "",
            project_name=row.project,
            building_name=row.building_name,
            unit_number=row.unit_number,
            property_type=row.property_type,
            transaction_date=row.recorded_at,
            transaction_price_aed=legacy_amount,
            party_role=row.party_role,
            ownership_status="probable_current_owner"
            if candidate
            else (
                "unverified_former_owner"
                if row.party_role.casefold() == "seller"
                else "unit_linked_unverified"
            ),
            confidence_score=60 if candidate else 0,
            match_reason=reason,
            evidence=evidence,
            created_at=now,
            updated_at=now,
        )


async def process_source_audit_import(db, *, upload: UploadFile, name, user_id, organization_id):
    data = await upload.read(MAX_SOURCE_AUDIT_BYTES + 1)
    if len(data) > MAX_SOURCE_AUDIT_BYTES:
        raise HTTPException(status_code=413, detail="The source audit exceeds 100 MB")
    try:
        payload = SourceAuditPayload.model_validate_json(data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail="Invalid source audit: " + str(exc).splitlines()[0]
        ) from exc
    digest = hashlib.sha256(data).hexdigest()
    existing = await import_repository.find_import_by_digest(db, organization_id, digest)
    if existing:
        return await _response(db, existing)
    now = datetime.now(timezone.utc)
    summary = CrmContactImportSummary(
        total_rows=len(payload.rows),
        candidate_rows=len(payload.rows),
        distinct_properties=len(payload.references),
        source_audit=audit_summary(payload),
        probable_current_owners=sum(len(ref.owner_candidate_groups) for ref in payload.references),
        valid_contacts=sum(bool(row.phone.strip()) for row in payload.rows),
    )
    record = CrmContactImport(
        organization_id=organization_id,
        created_by_user_id=user_id,
        name=name.strip()[:200] or Path(payload.original_filename).stem[:200],
        original_filename=Path(payload.original_filename).name,
        sha256=digest,
        size_bytes=len(data),
        status="completed",
        created_at=now,
        completed_at=now,
        mapping={
            "mode": "source_only",
            "dataset_id": payload.dataset_id,
            "schema_version": payload.schema_version,
            "resolver_version": payload.schema_version,
            "source_sha256": payload.source_sha256,
            "cleaned_sha256": payload.cleaned_sha256,
            "payload_sha256": digest,
        },
        summary=summary.model_dump(mode="json"),
    )
    try:
        db.add(record)
        await db.flush()
        contact_list = CrmContactList(
            organization_id=organization_id,
            created_by_user_id=user_id,
            source_import_id=record.id,
            name=record.name,
            description="Reviewed source-only snapshot; registry evidence not requested.",
            created_at=now,
            updated_at=now,
        )
        db.add(contact_list)
        await db.flush()
        batch = []
        for claim in source_claims(
            payload,
            import_id=record.id,
            list_id=contact_list.id,
            organization_id=organization_id,
            now=now,
        ):
            batch.append(claim)
            if len(batch) == 1000:
                db.add_all(batch)
                await db.flush()
                batch = []
        db.add_all(batch)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await import_repository.find_import_by_digest(db, organization_id, digest)
        if existing:
            return await _response(db, existing)
        raise
    except Exception:
        await db.rollback()
        raise
    from app.crm.owner_cache import _invalidate_owner_summary_cache

    _invalidate_owner_summary_cache(organization_id)
    return await _response(db, record)


async def _response(db, record) -> CrmContactImportResponse:
    contact_list = await import_repository.find_import_list(db, record)
    return CrmContactImportResponse(
        id=record.id,
        list_id=contact_list.id if contact_list else None,
        name=record.name,
        original_filename=record.original_filename,
        status=record.status,
        summary=CrmContactImportSummary.model_validate(record.summary),
        created_at=record.created_at,
        completed_at=record.completed_at,
    )


def aggregate_source_audit(rows, list_id=None):
    """Count persisted validated source references, including excluded history."""
    references = {}
    import_ids = set()
    source_count = 0
    matches = {}
    associations = {}
    for row in rows:
        audit = source_audit_for_row(row)
        if not audit or (list_id is not None and row["list_id"] != list_id):
            continue
        references[(row["import_id"], audit["reference_id"])] = audit["disposition"]
        import_ids.add(row["import_id"])
        source_count += 1
        match = audit.get("transaction_match")
        if match:
            identity = (row["import_id"], audit["reference_id"])
            matches[identity] = match
            category = match.get("owner_category")
            if category in {"current", "former"}:
                associations[
                    (identity, match.get("canonical_owner_key") or audit["canonical_owner_key"])
                ] = category
    if not references:
        return None
    counts = Counter(references.values())
    match_counts = Counter(match.get("status") for match in matches.values())
    association_counts = Counter(associations.values())
    return CrmSourceAuditSummary(
        mode="source_transaction_matched" if matches else "source_only",
        matched_reference_count=match_counts["matched"],
        matched_registry_property_count=len(
            {
                match["property_key"]
                for match in matches.values()
                if match.get("status") == "matched" and match.get("property_key")
            }
        ),
        unmatched_reference_count=match_counts["unmatched"],
        ambiguous_reference_count=match_counts["ambiguous"],
        excluded_match_reference_count=match_counts["excluded"],
        current_owner_association_count=association_counts["current"],
        former_owner_association_count=association_counts["former"],
        import_count=len(import_ids),
        reference_count=len(references),
        owner_candidate_reference_count=sum(counts[key] for key in CANDIDATE_DISPOSITIONS),
        bank_reference_count=counts["possible_mortgage_or_bank_acquisition"],
        excluded_nonownership_reference_count=counts["excluded_possible_nonownership_transaction"],
        review_reference_count=sum(counts[key] for key in REVIEW_DISPOSITIONS),
        excluded_scope_reference_count=counts["excluded_whole_building_or_project_context"],
        source_row_count=source_count,
        disposition_counts=dict(counts),
    )
