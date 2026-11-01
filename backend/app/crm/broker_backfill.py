"""Apply the licensed-broker rules to claims that are already stored.

A rematch would run the property matcher again (hours for every import). The broker rules need
only the row's own name and contact, and the stored verdict already holds the matcher's outcome,
so this re-decides just the rows whose broker marks changed and refreshes every import summary
(which also fills the review-reason and matched-sale counts) from the stored evidence.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import import_repository
from app.crm.brokers import (
    BrokerIndex,
    annotate_broker_contacts,
    broker_contact_evidence,
    load_broker_index,
)
from app.crm.identity import ParsedContact
from app.crm.import_models import CrmContactImport, CrmPropertyContactClaim
from app.crm.owner_match_status import apply_owner_match, date_differs
from app.crm.owner_matcher import MATCHER_VERSION
from app.crm.ownership import refresh_contact_import_match_summaries

BATCH = 1000


def _is_broker(mark: Any) -> bool:
    return bool(isinstance(mark, dict) and mark.get("is_broker"))


def _candidate(claim: CrmPropertyContactClaim) -> ParsedContact:
    return ParsedContact(
        source_sheet=claim.source_sheet,
        source_row_number=claim.source_row_number,
        contact_name=claim.contact_name,
        phone_primary=claim.phone_primary,
        phone_alternate=claim.phone_alternate,
        email_primary=claim.email_primary,
        area_name=claim.area_name,
        project_name=claim.project_name,
        building_name=claim.building_name,
        unit_number=claim.unit_number,
        property_type=claim.property_type,
        transaction_date=claim.transaction_date,
        transaction_price_aed=claim.transaction_price_aed,
        party_role=claim.party_role,
        procedure_type=claim.procedure_type,
        row_fingerprint=claim.row_fingerprint,
        ownership_status=claim.ownership_status,
        confidence_score=claim.confidence_score,
        match_reason=claim.match_reason,
        latest_sale_date=claim.latest_sale_date,
        latest_sale_price_aed=claim.latest_sale_price_aed,
        later_sale_date=claim.later_sale_date,
        evidence=dict(claim.evidence or {}),
    )


def _date_flag(match: Any, procedure_type: str, sheet_date: Any) -> tuple[bool, bool]:
    """(stored, now): whether the stored verdict carries the date-review warning, and whether the
    date rule applies to the row today. None when the verdict is from another matcher version."""
    if not isinstance(match, dict) or match.get("version") != MATCHER_VERSION:
        return False, False
    stored = any(str(w).startswith("date_differs") for w in match.get("warnings") or ())
    sale_date = (match.get("sale") or {}).get("date")
    return stored, date_differs(
        match.get("matcher_outcome", ""), procedure_type, sheet_date, sale_date
    )


def _redecide(claim: CrmPropertyContactClaim, index: BrokerIndex, now: datetime) -> None:
    """Store the row's broker marks; when its broker or date-review state flipped, re-apply the
    stored verdict."""
    candidate = _candidate(claim)
    was_broker = _is_broker(candidate.evidence.get("broker_contact"))
    annotate_broker_contacts([candidate], index)
    stored, applies = _date_flag(
        candidate.evidence.get("owner_match"), claim.procedure_type, claim.transaction_date
    )
    if stored != applies or was_broker != _is_broker(candidate.evidence.get("broker_contact")):
        apply_owner_match(candidate)
        reasons = (candidate.evidence.get("source_lifecycle") or {}).get("reasons")
        if reasons and candidate.match_reason != claim.match_reason:
            candidate.match_reason += " Source review: " + " ".join(reasons)
        claim.ownership_status = candidate.ownership_status
        claim.confidence_score = candidate.confidence_score
        claim.match_reason = candidate.match_reason
        claim.latest_sale_date = candidate.latest_sale_date
        claim.latest_sale_price_aed = candidate.latest_sale_price_aed
        claim.later_sale_date = candidate.later_sale_date
    claim.evidence = candidate.evidence
    claim.updated_at = now


async def backfill_licensed_brokers(
    db: AsyncSession, *, organization_id: str | None = None, import_id: int | None = None
) -> dict[str, Any]:
    """Apply the broker rules to stored claims; refresh the summaries of every import touched.

    Returns counts: claims scanned and changed, and per import the broker rows and the rows that
    carry a broker's phone or email under another name (after the run)."""
    index = await load_broker_index(db)
    columns = (
        CrmPropertyContactClaim.id,
        CrmPropertyContactClaim.organization_id,
        CrmPropertyContactClaim.import_id,
        CrmPropertyContactClaim.contact_name,
        CrmPropertyContactClaim.phone_primary,
        CrmPropertyContactClaim.phone_alternate,
        CrmPropertyContactClaim.email_primary,
        CrmPropertyContactClaim.evidence["broker_contact"],
        CrmPropertyContactClaim.transaction_date,
        CrmPropertyContactClaim.procedure_type,
        CrmPropertyContactClaim.evidence["owner_match"],
    )
    statement = select(*columns)
    if organization_id is not None:
        statement = statement.where(CrmPropertyContactClaim.organization_id == organization_id)
    if import_id is not None:
        statement = statement.where(CrmPropertyContactClaim.import_id == import_id)
    scanned = 0
    changed: list[int] = []
    per_import: dict[int, Counter[str]] = defaultdict(Counter)
    organizations: set[str] = set()
    for row in (await db.exec(statement)).all():
        claim_id, org, import_, name, primary, alternate, email, old, day, procedure, match = row
        scanned += 1
        organizations.add(org)
        new = broker_contact_evidence(name, primary, alternate, email, index)
        stored, applies = _date_flag(match, procedure or "", day)
        if (old or None) != new or stored != applies:
            changed.append(claim_id)
        per_import[import_]["date_review_rows"] += applies
        if new:
            per_import[import_]["broker_rows" if new["is_broker"] else "broker_contact_rows"] += 1
    now = datetime.now(timezone.utc)
    for start in range(0, len(changed), BATCH):
        claims = (
            await db.exec(
                select(CrmPropertyContactClaim).where(
                    CrmPropertyContactClaim.id.in_(changed[start : start + BATCH])
                )
            )
        ).all()
        for claim in claims:
            _redecide(claim, index, now)
            import_repository.save(db, claim)
        await db.flush()
    await db.commit()
    for org in sorted(organizations):
        await refresh_contact_import_match_summaries(db, organization_id=org, import_id=import_id)
    return {
        "brokers_in_table": len({n for ids in index.names.values() for n in ids}),
        "claims_scanned": scanned,
        "claims_changed": len(changed),
        "per_import": {k: dict(v) for k, v in sorted(per_import.items())},
    }


async def import_summaries(
    db: AsyncSession, *, organization_id: str | None = None
) -> dict[int, dict[str, Any]]:
    """(name, owner_match summary) of every import, for before/after reports."""
    statement = select(CrmContactImport)
    if organization_id is not None:
        statement = statement.where(CrmContactImport.organization_id == organization_id)
    return {
        record.id: {
            "name": record.name,
            "owner_match": (record.summary or {}).get("owner_match"),
            "contact_ready": (record.summary or {}).get("contact_ready"),
            "valid_contacts": (record.summary or {}).get("valid_contacts"),
        }
        for record in (await db.exec(statement)).all()
        if record.id is not None
    }
