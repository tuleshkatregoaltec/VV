"""What the stored assessment says about owners, lists and imports, computed once per build.

Two streaming passes over ``crm_owner_assessed_claims``. The first sees every row once, for the
counts that depend on all of them: the tenant summary, each import's summary, the source-audit
totals and which names sell for a developer. The second walks the owners in slices and writes
each owner's profile (for the whole tenant and for each list), with the columns the registry
filters, counts and sorts by.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

import orjson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.import_models import CrmOwnerProfile
from app.crm.owner_assessment import OwnerAssessmentSnapshot, restore_row, summarize_assessment_rows
from app.crm.owner_signals import SignalContext, build_owner_signals
from app.crm.source_audit import SourceAuditAccumulator, source_audit_for_row

logger = logging.getLogger(__name__)

SCAN_CHUNK = 20_000
OWNER_SLICE = 3_000
INSERT_BATCH = 1_000


def row_from_json(value: Any) -> dict[str, Any]:
    return restore_row(orjson.loads(value) if isinstance(value, (str, bytes)) else value)


class Totals:
    """Tenant-wide results of the first pass."""

    def __init__(self) -> None:
        self.context = SignalContext()
        self.compact: list[dict[str, Any]] = []
        self.audit_all = SourceAuditAccumulator(None)
        self.audit_lists: dict[int, SourceAuditAccumulator] = {}
        self.rows = 0
        self.source_rows = 0
        self.capture_dates: list[datetime] = []
        self.any_match = False

    def add(self, row: dict[str, Any]) -> None:
        self.rows += 1
        self.context.add(row)
        audit = source_audit_for_row(row)
        match = (audit or {}).get("transaction_match")
        # only what summarize_assessment_rows reads, so the tenant is not held in memory whole
        self.compact.append(
            {
                "canonical_owner_key": row["canonical_owner_key"],
                "property_identity": row["property_identity"],
                "assessed_status": row["assessed_status"],
                "claim_resolver_version": row.get("claim_resolver_version"),
                "import_resolver_version": row.get("import_resolver_version"),
                "import_id": row["import_id"],
                "source_audit": (
                    {"transaction_match": {"owner_category": match.get("owner_category")}}
                    if match
                    else ({"transaction_match": None} if audit else None)
                ),
            }
        )
        if audit:
            self.source_rows += 1
            self.audit_all.add(row)
            self.audit_lists.setdefault(row["list_id"], SourceAuditAccumulator(row["list_id"])).add(
                row
            )
            if match:
                self.any_match = True
                if match.get("matched_at"):
                    self.capture_dates.append(datetime.fromisoformat(match["matched_at"]))


def _json(model: Any) -> dict[str, Any] | None:
    return model.model_dump(mode="json") if model is not None else None


async def scan(
    engine: AsyncEngine,
    organization_id: str,
    generation: int,
    now: datetime,
    *,
    degraded: bool = False,
) -> tuple[Totals, OwnerAssessmentSnapshot, dict[str, Any]]:
    """First pass: tenant-wide totals and the snapshot-level values an in-memory build had."""
    totals = Totals()
    last = 0
    while True:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            batch = (
                await db.exec(
                    text(
                        "SELECT claim_id, row FROM crm_owner_assessed_claims "
                        "WHERE organization_id = :org AND generation = :gen AND claim_id > :last "
                        "ORDER BY claim_id LIMIT :limit"
                    ),
                    params={
                        "org": organization_id,
                        "gen": generation,
                        "last": last,
                        "limit": SCAN_CHUNK,
                    },
                )
            ).all()
        if not batch:
            break
        for claim_id, value in batch:
            totals.add(row_from_json(value))
        last = batch[-1][0]
    all_source = totals.rows > 0 and totals.source_rows == totals.rows
    checked_at = min(totals.capture_dates) if all_source and totals.capture_dates else now
    if all_source:
        warehouse_status = "available" if totals.any_match else "not_requested"
    else:
        warehouse_status = "unavailable" if degraded else "available"
    stub = OwnerAssessmentSnapshot([], None, checked_at, warehouse_status)  # type: ignore[arg-type]
    summary = summarize_assessment_rows(stub, totals.compact)
    by_import: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in totals.compact:
        by_import[row["import_id"]].append(row)
    state = {
        "summary": _json(summary),
        "import_summaries": {
            str(import_id): _json(summarize_assessment_rows(stub, rows))
            for import_id, rows in by_import.items()
        },
        "source_audit": {
            "all": _json(totals.audit_all.result()),
            **{str(lid): _json(acc.result()) for lid, acc in totals.audit_lists.items()},
        },
    }
    totals.compact = []
    return totals, stub, {"checked_at": checked_at, "warehouse_status": warehouse_status, **state}


_OWNER_COLUMNS = (
    "organization_id, generation, list_id, canonical_owner_key, owner_key, profile, search_text, "
    "property_count, contact_ready_count, highest_confidence_score, next_lease_end, "
    "developer_side_seller, invalid_identity_sources, no_properties, in_rental, in_registry, "
    "in_prior, in_review, in_multi"
)
_OWNER_TYPES = (
    "organization_id varchar, generation bigint, list_id integer, canonical_owner_key varchar, "
    "owner_key varchar, profile jsonb, search_text text, property_count integer, "
    "contact_ready_count integer, highest_confidence_score integer, next_lease_end date, "
    "developer_side_seller boolean, invalid_identity_sources boolean, no_properties boolean, "
    "in_rental boolean, in_registry boolean, in_prior boolean, in_review boolean, "
    "in_multi boolean"
)
_PROPERTY_COLUMNS = (
    "organization_id, generation, list_id, canonical_owner_key, ordinal, status, ready, "
    "rental_linked, lease_end, annual_rent_aed, sale_price_aed, match_status, location_text, "
    "headline_rank, confidence"
)
_PROPERTY_TYPES = (
    "organization_id varchar, generation bigint, list_id integer, canonical_owner_key varchar, "
    "ordinal integer, status varchar, ready boolean, rental_linked boolean, lease_end date, "
    "annual_rent_aed bigint, sale_price_aed bigint, match_status varchar, location_text text, "
    "headline_rank integer, confidence integer"
)


def _insert(table: str, columns: str, types: str) -> Any:
    names = [name.strip() for name in columns.split(",")]
    select = ", ".join(f"r.{name}" for name in names)
    return text(
        f"INSERT INTO {table} ({columns}) SELECT {select} "
        f"FROM jsonb_to_recordset(CAST(:payload AS jsonb)) AS r({types})"
    )


_INSERT_OWNERS = _insert("crm_owner_registry_owners", _OWNER_COLUMNS, _OWNER_TYPES)
_INSERT_PROPERTIES = _insert("crm_owner_registry_properties", _PROPERTY_COLUMNS, _PROPERTY_TYPES)


def _profile_records(
    profiles: list[CrmOwnerProfile],
    canonical_by_read_key: dict[str, str],
    *,
    organization_id: str,
    generation: int,
    list_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from app.crm import owners

    owner_rows, property_rows = [], []
    for profile in profiles:
        canonical = canonical_by_read_key[profile.owner_key]
        flags = owners._owner_registry_summary([profile])
        owner_rows.append(
            {
                "organization_id": organization_id,
                "generation": generation,
                "list_id": list_id,
                "canonical_owner_key": canonical,
                "owner_key": profile.owner_key,
                "profile": orjson.Fragment(orjson.dumps(profile.model_dump(mode="json"))),
                "search_text": " ".join(
                    str(value or "")
                    for value in (
                        profile.contact_name,
                        profile.phone_primary,
                        profile.phone_alternate,
                        profile.email_primary,
                    )
                ).casefold(),
                "property_count": profile.property_count,
                "contact_ready_count": profile.contact_ready_count,
                "highest_confidence_score": profile.highest_confidence_score,
                "next_lease_end": profile.next_lease_end.isoformat()
                if profile.next_lease_end
                else None,
                "developer_side_seller": profile.developer_side_seller,
                "invalid_identity_sources": bool(
                    profile.history_summary
                    and profile.history_summary.invalid_identity_source_count
                ),
                "no_properties": not profile.properties,
                "in_rental": bool(flags.rental_owner_profiles),
                "in_registry": bool(flags.registry_owner_profiles),
                "in_prior": bool(flags.prior_owner_profiles),
                "in_review": bool(flags.needs_review_profiles),
                "in_multi": bool(flags.multi_property_owners),
            }
        )
        for ordinal, item in enumerate(profile.properties):
            property_rows.append(
                {
                    "organization_id": organization_id,
                    "generation": generation,
                    "list_id": list_id,
                    "canonical_owner_key": canonical,
                    "ordinal": ordinal,
                    "status": item.ownership_status,
                    "ready": owners._property_contact_ready(item, profile),
                    "rental_linked": bool(item.lead_id and item.unit_candidate_key),
                    "lease_end": item.lease_end.isoformat() if item.lease_end else None,
                    "annual_rent_aed": item.annual_rent_aed,
                    "sale_price_aed": item.latest_sale_price_aed,
                    "match_status": item.source_reference.transaction_match_status
                    if item.source_reference
                    else None,
                    "location_text": " ".join(
                        (item.area_name, item.project_name, item.building_name, item.unit_number)
                    ).casefold(),
                    "headline_rank": owners._HEADLINE_PRIORITY.get(item.ownership_status, 1),
                    "confidence": item.confidence_score,
                }
            )
    return owner_rows, property_rows


async def _insert_records(
    engine: AsyncEngine, statement: Any, records: list[dict[str, Any]]
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        for start in range(0, len(records), INSERT_BATCH):
            await db.exec(
                statement,
                params={"payload": orjson.dumps(records[start : start + INSERT_BATCH]).decode()},
            )
        await db.commit()


async def write_profiles(
    engine: AsyncEngine,
    organization_id: str,
    generation: int,
    totals: Totals,
    stub: OwnerAssessmentSnapshot,
) -> dict[str, dict[str, int]]:
    """Second pass: owner profiles, and each list's contact counts, owner by owner."""
    from app.crm import owners

    async with AsyncSession(engine, expire_on_commit=False) as db:
        canonicals = [
            row[0]
            for row in (
                await db.exec(
                    text(
                        "SELECT DISTINCT canonical_owner_key FROM crm_owner_assessed_claims "
                        "WHERE organization_id = :org AND generation = :gen ORDER BY 1"
                    ),
                    params={"org": organization_id, "gen": generation},
                )
            ).all()
        ]
        shared = {
            row[0]
            for row in (
                await db.exec(
                    text(
                        "SELECT owner_key FROM crm_owner_assessed_claims "
                        "WHERE organization_id = :org AND generation = :gen "
                        "GROUP BY owner_key HAVING count(DISTINCT canonical_owner_key) > 1"
                    ),
                    params={"org": organization_id, "gen": generation},
                )
            ).all()
        }
    list_counts: dict[str, dict[str, int]] = {}
    for start in range(0, len(canonicals), OWNER_SLICE):
        keys = canonicals[start : start + OWNER_SLICE]
        async with AsyncSession(engine, expire_on_commit=False) as db:
            stored = (
                await db.exec(
                    text(
                        "SELECT row FROM crm_owner_assessed_claims WHERE organization_id = :org "
                        "AND generation = :gen AND canonical_owner_key = ANY(:keys) ORDER BY ord"
                    ),
                    params={"org": organization_id, "gen": generation, "keys": keys},
                )
            ).all()
        rows = [row_from_json(value) for (value,) in stored]
        read_keys = owners._owner_read_keys(rows, shared_keys=shared)
        canonical_by_read_key = {read_key: canonical for canonical, read_key in read_keys.items()}
        signals = build_owner_signals(rows, context=totals.context)
        by_list: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_list[row["list_id"]].append(row)
        variants = {0: rows, **by_list}
        owner_records: list[dict[str, Any]] = []
        property_records: list[dict[str, Any]] = []
        for list_id, variant_rows in variants.items():
            profiles = owners._assessed_profiles(
                variant_rows, snapshot=stub, read_keys=read_keys, signals=signals
            )
            owner_part, property_part = _profile_records(
                profiles,
                canonical_by_read_key,
                organization_id=organization_id,
                generation=generation,
                list_id=list_id,
            )
            owner_records += owner_part
            property_records += property_part
            if list_id:
                counts = list_counts.setdefault(
                    str(list_id),
                    {
                        "total_contacts": 0,
                        "contact_ready": 0,
                        "needs_review": 0,
                        "former_owners": 0,
                    },
                )
                for name, value in owners._assessed_list_counts(variant_rows).items():
                    counts[name] += value
        await _insert_records(engine, _INSERT_OWNERS, owner_records)
        await _insert_records(engine, _INSERT_PROPERTIES, property_records)
    return list_counts
