from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from sqlalchemy import and_, delete, func, or_, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.import_models import (
    CrmContactImport,
    CrmContactList,
    CrmPropertyContactClaim,
)


async def list_rental_refresh_claims(db: AsyncSession, import_id, organization_id):
    statement = select(CrmPropertyContactClaim).where(
        CrmPropertyContactClaim.organization_id == organization_id
    )
    if import_id is not None:
        statement = statement.where(CrmPropertyContactClaim.import_id == import_id)
    claims = (await db.exec(statement.with_for_update())).all()
    return claims


def rental_link_statement(import_id, organization_id):
    """The columns a lease-link refresh reads, locked for its transaction.

    Loading whole claims (contact, source and owner-history payloads) for a 311k-claim tenant
    takes ~12 GB; the refresh needs only the property key and the current link.
    """
    claim = CrmPropertyContactClaim
    statement = select(
        claim.id,
        claim.import_id,
        claim.property_key,
        claim.unit_number,
        claim.area_name,
        claim.project_name,
        claim.lead_id,
        claim.unit_candidate_key,
        claim.lease_end,
        claim.annual_rent_aed,
        claim.evidence["scoped_identity_collision"].as_boolean().label("scoped_identity_collision"),
        claim.evidence["registry_property_scope"].label("registry_property_scope"),
    ).where(claim.organization_id == organization_id)
    if import_id is not None:
        statement = statement.where(claim.import_id == import_id)
    return statement.order_by(claim.id).with_for_update(of=claim)


async def list_rental_link_rows(db: AsyncSession, import_id, organization_id) -> list[Any]:
    rows = (await db.exec(rental_link_statement(import_id, organization_id))).all()
    return [
        SimpleNamespace(
            **{
                key: value
                for key, value in row._mapping.items()
                if key not in {"scoped_identity_collision", "registry_property_scope"}
            },
            evidence={
                key: row._mapping[key]
                for key in ("scoped_identity_collision", "registry_property_scope")
                if row._mapping[key] is not None
            },
        )
        for row in rows
    ]


_SAVE_RENTAL_LINKS = text(
    """
    UPDATE crm_property_contact_claims AS c
    SET lead_id = v.lead_id,
        unit_candidate_key = v.unit_candidate_key,
        lease_end = v.lease_end,
        annual_rent_aed = v.annual_rent_aed,
        updated_at = :now
    FROM jsonb_to_recordset(CAST(:payload AS jsonb)) AS v(
        id integer, lead_id varchar, unit_candidate_key varchar, lease_end date,
        annual_rent_aed bigint
    )
    WHERE c.id = v.id
    """
)
RENTAL_LINK_BATCH = 5000


async def save_rental_links(db: AsyncSession, changes: list[dict[str, Any]], now) -> None:
    """Write only the four lease-link fields (and updated_at) of the changed claims."""
    for start in range(0, len(changes), RENTAL_LINK_BATCH):
        payload = [
            {
                **change,
                "lease_end": change["lease_end"].isoformat() if change["lease_end"] else None,
            }
            for change in changes[start : start + RENTAL_LINK_BATCH]
        ]
        await db.exec(
            _SAVE_RENTAL_LINKS,
            params={"payload": json.dumps(payload), "now": now},
        )


async def list_claims_for_rematch(
    db, audit_resolution_methods, import_id, only_unmatched, organization_id
):
    statement = select(CrmPropertyContactClaim).where(
        CrmPropertyContactClaim.organization_id == organization_id
    )
    if import_id is not None:
        statement = statement.where(CrmPropertyContactClaim.import_id == import_id)
    if audit_resolution_methods:
        statement = statement.where(
            CrmPropertyContactClaim.evidence["property_identity_resolution"]["method"]
            .as_string()
            .in_(sorted(audit_resolution_methods))
        )
    elif only_unmatched:
        statement = statement.where(CrmPropertyContactClaim.ownership_status == "unmatched")
    claims = (await db.exec(statement)).all()
    return claims


async def count_import_claim_metrics(db: AsyncSession, organization_id, record_id):
    # A channel marked as a licensed broker's (evidence["broker_contact"]) is not the owner's.
    broker = CrmPropertyContactClaim.evidence["broker_contact"]
    has_contact = and_(
        or_(
            CrmPropertyContactClaim.phone_primary.is_not(None),
            CrmPropertyContactClaim.phone_alternate.is_not(None),
            CrmPropertyContactClaim.email_primary.is_not(None),
        ),
        or_(
            broker["usable_contact"].as_string().is_(None),
            broker["usable_contact"].as_string() != "false",
        ),
    )
    metrics_result = await db.exec(
        select(
            func.count(),
            func.count().filter(has_contact),
            func.count().filter(CrmPropertyContactClaim.lead_id.is_not(None)),
            func.count().filter(
                and_(
                    CrmPropertyContactClaim.lead_id.is_not(None),
                    has_contact,
                    CrmPropertyContactClaim.ownership_status.in_(
                        ("verified_current_owner", "probable_current_owner")
                    ),
                )
            ),
            func.count().filter(CrmPropertyContactClaim.latest_sale_date.is_not(None)),
            func.count().filter(
                and_(
                    CrmPropertyContactClaim.property_key.like("dld-land:%"),
                    CrmPropertyContactClaim.unit_number == "",
                )
            ),
        ).where(
            CrmPropertyContactClaim.organization_id == organization_id,
            CrmPropertyContactClaim.import_id == record_id,
        )
    )
    return tuple(int(value or 0) for value in metrics_result.one())


async def count_import_distinct_properties(db: AsyncSession, organization_id, record_id) -> int:
    # Claims with no building + unit carry a "source:<fingerprint>" key; they are not properties.
    result = await db.exec(
        select(func.count(func.distinct(CrmPropertyContactClaim.property_key))).where(
            CrmPropertyContactClaim.organization_id == organization_id,
            CrmPropertyContactClaim.import_id == record_id,
            CrmPropertyContactClaim.property_key.not_like("source:%"),
            CrmPropertyContactClaim.property_key != "",
        )
    )
    return int(result.one() or 0)


async def count_import_linked_rows(db: AsyncSession, organization_id, record_id) -> int:
    result = await db.exec(
        select(func.count())
        .select_from(CrmPropertyContactClaim)
        .where(
            CrmPropertyContactClaim.organization_id == organization_id,
            CrmPropertyContactClaim.import_id == record_id,
            or_(
                CrmPropertyContactClaim.latest_sale_date.is_not(None),
                and_(
                    CrmPropertyContactClaim.unit_candidate_key.is_not(None),
                    CrmPropertyContactClaim.unit_candidate_key != "",
                ),
                CrmPropertyContactClaim.property_key.like("dld-land:%"),
            ),
        )
    )
    return int(result.one() or 0)


async def list_claim_matches(db: AsyncSession, organization_id, record_id):
    """(owner_match, matcher_source) evidence of every claim of an import; None where absent."""
    evidence = CrmPropertyContactClaim.evidence
    result = await db.exec(
        select(evidence["owner_match"], evidence["matcher_source"]).where(
            CrmPropertyContactClaim.organization_id == organization_id,
            CrmPropertyContactClaim.import_id == record_id,
        )
    )
    return [(match, source or {}) for match, source in result if isinstance(match, dict)]


async def list_import_property_claims(db: AsyncSession, organization_id, record_id, search):
    """Include unresolved source records so retained evidence is accessible for review."""
    statement = select(CrmPropertyContactClaim).where(
        CrmPropertyContactClaim.organization_id == organization_id,
        CrmPropertyContactClaim.import_id == record_id,
    )
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                CrmPropertyContactClaim.building_name.ilike(term),
                CrmPropertyContactClaim.project_name.ilike(term),
                CrmPropertyContactClaim.area_name.ilike(term),
                CrmPropertyContactClaim.unit_number.ilike(term),
                CrmPropertyContactClaim.contact_name.ilike(term),
                CrmPropertyContactClaim.evidence["source_identifiers"]["land_number"]
                .as_string()
                .ilike(term),
            )
        )
    return (await db.exec(statement)).all()


def save(db: AsyncSession, record):
    db.add(record)


async def find_import_by_digest(db: AsyncSession, organization_id, sha256):
    return (
        await db.exec(
            select(CrmContactImport).where(
                CrmContactImport.organization_id == organization_id,
                CrmContactImport.sha256 == sha256,
            )
        )
    ).first()


def save_all(db: AsyncSession, records):
    db.add_all(records)


async def find_import_list(db: AsyncSession, record):
    return (
        await db.exec(select(CrmContactList).where(CrmContactList.source_import_id == record.id))
    ).first()


async def list_imports(db: AsyncSession, organization_id):
    return (
        await db.exec(
            select(CrmContactImport)
            .where(CrmContactImport.organization_id == organization_id)
            .order_by(CrmContactImport.created_at.desc())
        )
    ).all()


async def get_import_for_org(db: AsyncSession, import_id, organization_id):
    return (
        await db.exec(
            select(CrmContactImport).where(
                CrmContactImport.id == import_id,
                CrmContactImport.organization_id == organization_id,
            )
        )
    ).first()


async def lock_import_for_replay(db: AsyncSession, import_id: int, organization_id: str):
    return (
        await db.exec(
            select(CrmContactImport)
            .where(
                CrmContactImport.id == import_id,
                CrmContactImport.organization_id == organization_id,
            )
            .with_for_update(nowait=True)
        )
    ).first()


async def find_import_list_for_org(db: AsyncSession, import_id, organization_id):
    return (
        await db.exec(
            select(CrmContactList).where(
                CrmContactList.source_import_id == import_id,
                CrmContactList.organization_id == organization_id,
            )
        )
    ).first()


async def delete_import_claims(db: AsyncSession, import_id, organization_id):
    return await db.exec(
        delete(CrmPropertyContactClaim).where(
            CrmPropertyContactClaim.import_id == import_id,
            CrmPropertyContactClaim.organization_id == organization_id,
        )
    )


async def delete_import_lists(db: AsyncSession, import_id, organization_id):
    return await db.exec(
        delete(CrmContactList).where(
            CrmContactList.source_import_id == import_id,
            CrmContactList.organization_id == organization_id,
        )
    )


async def delete_record(db: AsyncSession, record):
    await db.delete(record)


async def list_imports_by_ids(db: AsyncSession, import_ids, organization_id):
    return (
        await db.exec(
            select(CrmContactImport).where(
                CrmContactImport.organization_id == organization_id,
                CrmContactImport.id.in_(sorted(import_ids)),
            )
        )
    ).all()


async def count_claims_by_status(db: AsyncSession, organization_id, record_id):
    return (
        await db.exec(
            select(CrmPropertyContactClaim.ownership_status, func.count())
            .where(
                CrmPropertyContactClaim.organization_id == organization_id,
                CrmPropertyContactClaim.import_id == record_id,
            )
            .group_by(CrmPropertyContactClaim.ownership_status)
        )
    ).all()


async def list_import_ids(db: AsyncSession, organization_id):
    return (
        await db.exec(
            select(CrmContactImport.id).where(CrmContactImport.organization_id == organization_id)
        )
    ).all()


_SAVED_MAPPING_SCAN = 200


async def latest_mapping_for_signature(
    db: AsyncSession, organization_id: str, signature: str
) -> dict[str, Any] | None:
    """The saved mapping of the most recent completed import that has a sheet with this header
    signature. Failed model answers (``heuristic_fallback``) are never reused."""
    records = (
        await db.exec(
            select(CrmContactImport)
            .where(
                CrmContactImport.organization_id == organization_id,
                CrmContactImport.status == "completed",
            )
            .order_by(CrmContactImport.completed_at.desc())
            .limit(_SAVED_MAPPING_SCAN)
        )
    ).all()
    for record in records:
        for sheet in (record.mapping or {}).get("sheets", []):
            if (
                isinstance(sheet, dict)
                and sheet.get("signature") == signature
                and sheet.get("mapping_source") != "heuristic_fallback"
            ):
                return sheet
    return None


async def lists_for_imports(db: AsyncSession, organization_id: str, import_ids: list[int]):
    if not import_ids:
        return []
    return (
        await db.exec(
            select(CrmContactList).where(
                CrmContactList.organization_id == organization_id,
                CrmContactList.source_import_id.in_(import_ids),
            )
        )
    ).all()
