from __future__ import annotations

from typing import Any

import orjson
from sqlalchemy import ARRAY, Integer, String, any_, exists, func, literal, or_, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.import_events import source_size_unit
from app.crm.import_models import (
    CrmContactImport,
    CrmContactList,
    CrmOwnerAssessmentRevision,
    CrmPropertyContactClaim,
)


async def list_owner_history_rows(
    db: AsyncSession,
    *,
    organization_id: str,
    owner_key: str | None = None,
    import_id: int | None = None,
    property_context: bool = False,
    include_source_details: bool = True,
    canonical_phone_digits: list[str] | None = None,
    canonical_emails: list[str] | None = None,
    additional_property_keys: list[str] | None = None,
    unit_candidate_keys: list[str] | None = None,
    claim_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Read only the history projection's fields, without raw contact/source JSON.

    Context deliberately spans imports and owners of the selected properties. A
    selected file must not hide a later disposal or competing acquisition.

    ``unit_candidate_keys`` reads just the claims of those lease units plus every
    other claim on the same properties (so a competing owner still counts), instead
    of the organization's whole claim table. ``claim_ids`` reads exactly those claims.
    """
    claim = CrmPropertyContactClaim
    scope = [claim.organization_id == organization_id]
    unit_scope = None
    if unit_candidate_keys is not None:
        # One array parameter, not one bind per key: the key list grows with the
        # agent's workspaces and asyncpg caps a statement at 32,767 parameters.
        keys = any_(literal(sorted(set(unit_candidate_keys)), ARRAY(String)))
        unit_scope = claim.unit_candidate_key == keys
    if owner_key is not None:
        scope.append(claim.owner_key == owner_key)
    if import_id is not None:
        scope.append(claim.import_id == import_id)
    # Import mappings may contain the full previous replay result. Read their
    # resolver version once per import, rather than reparsing it for every row.
    sources = {
        row.id: row
        for row in (
            await db.exec(
                select(
                    CrmContactImport.id,
                    CrmContactImport.original_filename,
                    CrmContactImport.owner_source_metadata["sheets"].label("sheets"),
                    CrmContactImport.owner_source_metadata["resolver_version"]
                    .as_string()
                    .label("resolver_version"),
                ).where(CrmContactImport.organization_id == organization_id)
            )
        ).all()
    }
    size_units = {
        (source.id, str(sheet.get("sheet_name") or "")): source_size_unit(
            sheet.get("field_map") or {}
        )
        for source in sources.values()
        for sheet in (source.sheets or [])
        if isinstance(sheet, dict)
    }
    columns = [
        getattr(claim, name)
        for name in (
            "id",
            "owner_key",
            "property_key",
            "import_id",
            "list_id",
            "source_sheet",
            "source_row_number",
            "contact_name",
            "phone_primary",
            "phone_alternate",
            "email_primary",
            "area_name",
            "project_name",
            "building_name",
            "unit_number",
            "property_type",
            "party_role",
            "procedure_type",
            "transaction_date",
            "transaction_price_aed",
            "ownership_status",
            "confidence_score",
            "match_reason",
            "latest_sale_date",
            "latest_sale_price_aed",
            "later_sale_date",
            "lead_id",
            "unit_candidate_key",
            "lease_end",
            "annual_rent_aed",
            "created_at",
            "updated_at",
        )
        if include_source_details
        or name
        not in {
            "source_sheet",
            "source_row_number",
            "match_reason",
        }
    ]
    # Written transactionally by database triggers. Reads never detoast/reparse
    # the original evidence or replay mapping, which remain the audit authority.
    metadata = claim.owner_history_evidence
    statement = (
        select(
            *columns,
            metadata["resolver_version"].as_string().label("claim_resolver_version"),
            metadata["event_family"].as_string().label("event_family"),
            metadata["cadastral_identity"]["property_key"].as_string().label("cadastral_key"),
            metadata["scoped_identity_collision"].as_boolean().label("identity_collision"),
            metadata.op("-")("resolver_version").cast(String).label("history_evidence_json"),
            CrmContactList.name.label("source_list_name"),
        )
        .select_from(claim)
        .join(
            CrmContactList,
            (CrmContactList.id == claim.list_id)
            & (CrmContactList.organization_id == organization_id),
        )
        .where(claim.import_id.in_(sources))
    )
    if claim_ids is not None:
        statement = statement.where(
            claim.organization_id == organization_id,
            claim.id == any_(literal(sorted(set(claim_ids)), ARRAY(Integer))),
        )
    elif unit_scope is not None:
        # Every claim on a property that has a claim on one of the units; that already
        # includes the units' own claims.
        statement = statement.where(
            claim.organization_id == organization_id,
            claim.property_key.in_(
                select(claim.property_key).where(
                    claim.organization_id == organization_id, unit_scope
                )
            ),
        )
    elif property_context:
        statement = statement.where(claim.organization_id == organization_id)
        if import_id is not None and owner_key is None:
            # The selected import is already loaded. Read other imports once;
            # a property-key semijoin otherwise repeatedly scans the existing
            # (org, owner, property) index without its owner prefix.
            statement = statement.where(claim.import_id != import_id)
        else:
            # Owner drilldowns use the (org, property) index to include later
            # evidence recorded under another contact identity.
            candidates = [claim.property_key.in_(select(claim.property_key).where(*scope))]
            if additional_property_keys:
                candidates.append(claim.property_key.in_(additional_property_keys))
            if canonical_phone_digits:
                candidates.extend(
                    func.regexp_replace(channel, "[^0-9]", "", "g").in_(canonical_phone_digits)
                    for channel in (claim.phone_primary, claim.phone_alternate)
                )
            if canonical_emails:
                candidates.append(func.lower(func.trim(claim.email_primary)).in_(canonical_emails))
            statement = statement.where(or_(*candidates))
    else:
        statement = statement.where(*scope)
    result = await db.exec(statement)
    names = tuple(result.keys())
    rows = []
    for source in result:
        # Avoid a mapping lookup for every column of every source event.
        row = dict(zip(names, source, strict=True))
        evidence = orjson.loads(row.pop("history_evidence_json"))
        declared_size_unit = size_units.get((row["import_id"], row.get("source_sheet", "")))
        if declared_size_unit:
            evidence["source_size_unit"] = declared_size_unit
        elif not evidence.get("source_size_unit") and any(
            (evidence.get("source_fields") or {}).get(field) not in (None, "")
            for field in ("size_sqft", "size_sqm", "size_unknown")
        ):
            evidence["source_size_unit"] = "unknown"
        evidence.update(
            event_family=row["event_family"],
            scoped_identity_collision=row["identity_collision"],
        )
        row.update(
            source_filename=sources[row["import_id"]].original_filename,
            import_resolver_version=sources[row["import_id"]].resolver_version,
            evidence={key: value for key, value in evidence.items() if value is not None},
            source_size_sqft=(evidence.get("source_fields") or {}).get("size_sqft"),
        )
        rows.append(row)
    return rows


async def owner_history_import_exists(
    db: AsyncSession, organization_id: str, import_id: int
) -> bool:
    return (
        await db.exec(
            select(CrmContactImport.id).where(
                CrmContactImport.id == import_id,
                CrmContactImport.organization_id == organization_id,
            )
        )
    ).first() is not None


_OWNER_REGISTRY_BASE_SQL = """
WITH base AS (
    SELECT
        c.id,
        c.organization_id,
        c.import_id,
        c.list_id,
        c.source_sheet,
        c.source_row_number,
        c.owner_key,
        c.property_key,
        c.contact_name,
        c.phone_primary,
        c.phone_alternate,
        c.email_primary,
        c.area_name,
        c.project_name,
        c.building_name,
        c.unit_number,
        c.property_type,
        c.party_role,
        c.transaction_date,
        c.transaction_price_aed,
        c.ownership_status,
        c.confidence_score,
        c.match_reason,
        c.lead_id,
        c.unit_candidate_key,
        c.latest_sale_date,
        c.latest_sale_price_aed,
        c.later_sale_date,
        c.lease_end,
        c.annual_rent_aed,
        c.owner_key AS owner_key_sql,
        c.property_key AS property_key_sql,
        CASE c.ownership_status
            WHEN 'former_owner' THEN 6
            WHEN 'verified_current_owner' THEN 5
            WHEN 'probable_current_owner' THEN 4
            WHEN 'unit_linked_unverified' THEN 3
            WHEN 'conflicting_claim' THEN 2
            ELSE 1
        END AS status_rank
    FROM crm_property_contact_claims c
    WHERE c.organization_id = :organization_id
      AND (
        CAST(:owner_list_id AS INTEGER) IS NULL
        OR c.list_id = CAST(:owner_list_id AS INTEGER)
      )
),
ranked AS (
    SELECT DISTINCT ON (owner_key_sql, property_key_sql)
        *
    FROM base
    ORDER BY
        owner_key_sql,
        property_key_sql,
        (status_rank >= 4) DESC,
        CASE WHEN status_rank >= 4 THEN transaction_date END DESC NULLS LAST,
        status_rank DESC,
        confidence_score DESC,
        transaction_date DESC NULLS LAST
),
properties AS (
    SELECT * FROM ranked
)
"""


def _owner_scope_clause(scope: str, alias: str = "p") -> str:
    ready = (
        f"{alias}.lead_id IS NOT NULL AND "
        f"{alias}.ownership_status IN "
        "('verified_current_owner', 'probable_current_owner')"
    )
    if scope == "rental_ready":
        return ready
    if scope == "prior_owners":
        return f"{alias}.ownership_status = 'former_owner'"
    if scope == "registry":
        return f"NOT ({ready}) AND {alias}.ownership_status <> 'former_owner'"
    return "TRUE"


def _owner_filter_sql(
    *,
    scope: str,
    status: str | None,
    search: str | None,
    lease_window: str | None = None,
    min_rent_aed: int | None = None,
    max_rent_aed: int | None = None,
    min_value_aed: int | None = None,
    max_value_aed: int | None = None,
    alias: str = "p",
) -> tuple[str, dict[str, Any]]:
    clauses = [_owner_scope_clause(scope, alias)]
    parameters: dict[str, Any] = {}
    if status:
        clauses.append(f"{alias}.ownership_status = :owner_status")
        parameters["owner_status"] = status
    if search:
        clauses.append(
            "lower(concat_ws(' ', "
            f"{alias}.contact_name, {alias}.phone_primary, "
            f"{alias}.phone_alternate, {alias}.email_primary, "
            f"{alias}.building_name, {alias}.project_name, "
            f"{alias}.area_name, {alias}.unit_number"
            ")) LIKE :owner_search"
        )
        parameters["owner_search"] = f"%{search.casefold().strip()}%"
    if lease_window == "expired":
        clauses.append(f"{alias}.lease_end < CURRENT_DATE")
    elif lease_window in {"expiring_30", "expiring_60", "expiring_90"}:
        lower_days, upper_days = {
            "expiring_30": (0, 30),
            "expiring_60": (30, 60),
            "expiring_90": (60, 90),
        }[lease_window]
        clauses.append(
            f"{alias}.lease_end > CURRENT_DATE + make_interval(days => :lease_lower_days)"
        )
        clauses.append(
            f"{alias}.lease_end <= CURRENT_DATE + make_interval(days => :lease_upper_days)"
        )
        parameters["lease_lower_days"] = lower_days
        parameters["lease_upper_days"] = upper_days
    if min_rent_aed is not None:
        clauses.append(f"{alias}.annual_rent_aed >= :owner_min_rent")
        parameters["owner_min_rent"] = min_rent_aed
    if max_rent_aed is not None:
        clauses.append(f"{alias}.annual_rent_aed <= :owner_max_rent")
        parameters["owner_max_rent"] = max_rent_aed
    if min_value_aed is not None:
        clauses.append(f"{alias}.latest_sale_price_aed >= :owner_min_value")
        parameters["owner_min_value"] = min_value_aed
    if max_value_aed is not None:
        clauses.append(f"{alias}.latest_sale_price_aed <= :owner_max_value")
        parameters["owner_max_value"] = max_value_aed
    return " AND ".join(f"({clause})" for clause in clauses), parameters


async def _owner_page_keys_sql(
    db: AsyncSession,
    *,
    organization_id: str,
    list_id: int | None,
    scope: str,
    status: str | None,
    search: str | None,
    lease_window: str | None,
    portfolio_only: bool,
    min_rent_aed: int | None,
    max_rent_aed: int | None,
    min_value_aed: int | None,
    max_value_aed: int | None,
    limit: int,
    offset: int,
    min_properties: int | None = None,
    next_event_days: int | None = None,
) -> tuple[list[str], int]:
    where_sql, parameters = _owner_filter_sql(
        scope=scope,
        status=status,
        search=search,
        lease_window=lease_window,
        min_rent_aed=min_rent_aed,
        max_rent_aed=max_rent_aed,
        min_value_aed=min_value_aed,
        max_value_aed=max_value_aed,
    )
    statement = text(
        _OWNER_REGISTRY_BASE_SQL
        + f"""
        , scoped_properties AS (
            SELECT p.* FROM properties p WHERE {where_sql}
        ),
        profile_rollup AS (
            SELECT
                owner_key_sql,
                count(*) AS property_count,
                count(*) FILTER (WHERE lead_id IS NOT NULL)
                    AS rental_linked_count,
                count(*) FILTER (
                    WHERE lead_id IS NOT NULL
                    AND ownership_status IN (
                        'verified_current_owner',
                        'probable_current_owner'
                    )
                ) AS contact_ready_count,
                max(confidence_score) AS highest_confidence_score,
                min(lease_end) FILTER (WHERE lease_end IS NOT NULL)
                    AS next_lease_end
            FROM scoped_properties
            GROUP BY owner_key_sql
        )
        SELECT
            owner_key_sql,
            count(*) OVER () AS total_profiles
        FROM profile_rollup
        WHERE (NOT :portfolio_only OR property_count > 1)
          AND (CAST(:min_properties AS integer) IS NULL
               OR property_count >= CAST(:min_properties AS integer))
          AND (CAST(:next_event_days AS integer) IS NULL
               OR (next_lease_end >= CURRENT_DATE
                   AND next_lease_end <= CURRENT_DATE
                       + make_interval(days => CAST(:next_event_days AS integer))))
        ORDER BY
            contact_ready_count DESC,
            property_count DESC,
            highest_confidence_score DESC,
            next_lease_end ASC NULLS LAST,
            owner_key_sql
        LIMIT :owner_limit OFFSET :owner_offset
        """
    )
    parameters.update(
        {
            "organization_id": organization_id,
            "owner_list_id": list_id,
            "portfolio_only": portfolio_only,
            "min_properties": min_properties,
            "next_event_days": next_event_days,
            "owner_limit": limit,
            "owner_offset": offset,
        }
    )
    rows = (await db.exec(statement, params=parameters)).mappings().all()
    return (
        [str(row["owner_key_sql"]) for row in rows],
        int(rows[0]["total_profiles"]) if rows else 0,
    )


async def _owner_properties_sql(
    db: AsyncSession,
    *,
    organization_id: str,
    list_id: int | None,
    owner_keys: list[str],
    scope: str,
    status: str | None = None,
    search: str | None = None,
    lease_window: str | None = None,
    min_rent_aed: int | None = None,
    max_rent_aed: int | None = None,
    min_value_aed: int | None = None,
    max_value_aed: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if not owner_keys:
        return {}
    where_sql, parameters = _owner_filter_sql(
        scope=scope,
        status=status,
        search=search,
        lease_window=lease_window,
        min_rent_aed=min_rent_aed,
        max_rent_aed=max_rent_aed,
        min_value_aed=min_value_aed,
        max_value_aed=max_value_aed,
    )
    statement = text(
        _OWNER_REGISTRY_BASE_SQL
        + f"""
        , limited_properties AS (
            SELECT DISTINCT ON (owner_key_sql, property_key_sql)
                *
            FROM base
            WHERE owner_key_sql = ANY(:owner_keys)
            ORDER BY
                owner_key_sql,
                property_key_sql,
                (status_rank >= 4) DESC,
                CASE WHEN status_rank >= 4 THEN transaction_date END DESC NULLS LAST,
                status_rank DESC,
                confidence_score DESC,
                transaction_date DESC NULLS LAST
        ),
        limited_source_aggregation AS (
            SELECT
                c.owner_key AS owner_key_sql,
                c.property_key AS property_key_sql,
                count(*) AS duplicate_count,
                array_agg(DISTINCT l.name ORDER BY l.name)
                    AS source_lists,
                array_agg(
                    DISTINCT c.source_sheet || ':' || c.source_row_number::text
                    ORDER BY c.source_sheet || ':' || c.source_row_number::text
                ) AS source_rows
            FROM crm_property_contact_claims c
            INNER JOIN crm_contact_lists l ON l.id = c.list_id
            WHERE c.organization_id = :organization_id
              AND (
                CAST(:owner_list_id AS INTEGER) IS NULL
                OR c.list_id = CAST(:owner_list_id AS INTEGER)
              )
              AND c.owner_key = ANY(:owner_keys)
            GROUP BY c.owner_key, c.property_key
        ),
        scoped_properties AS (
            SELECT p.* FROM limited_properties p WHERE {where_sql}
        )
        SELECT
            p.*,
            a.duplicate_count,
            a.source_lists,
            a.source_rows
        FROM scoped_properties p
        INNER JOIN limited_source_aggregation a
            ON a.owner_key_sql = p.owner_key_sql
            AND a.property_key_sql = p.property_key_sql
        WHERE p.owner_key_sql = ANY(:owner_keys)
        ORDER BY
            p.owner_key_sql,
            p.status_rank DESC,
            p.confidence_score DESC,
            p.lease_end ASC NULLS LAST
        """
    )
    parameters.update(
        {
            "organization_id": organization_id,
            "owner_list_id": list_id,
            "owner_keys": owner_keys,
        }
    )
    rows = (await db.exec(statement, params=parameters)).mappings().all()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["owner_key_sql"]), []).append(dict(row))
    return grouped


async def find_contact_list_claims(db: AsyncSession, list_id, organization_id, search):
    statement = select(CrmPropertyContactClaim).where(
        CrmPropertyContactClaim.organization_id == organization_id,
        CrmPropertyContactClaim.list_id == list_id,
    )
    if search:
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                CrmPropertyContactClaim.contact_name.ilike(term),
                CrmPropertyContactClaim.building_name.ilike(term),
                CrmPropertyContactClaim.project_name.ilike(term),
                CrmPropertyContactClaim.unit_number.ilike(term),
            )
        )
    all_result = await db.exec(statement)
    return (all_result).all()


async def list_claims_by_ids(db: AsyncSession, organization_id: str, claim_ids: list[int]):
    if not claim_ids:
        return []
    return (
        await db.exec(
            select(CrmPropertyContactClaim).where(
                CrmPropertyContactClaim.organization_id == organization_id,
                CrmPropertyContactClaim.id.in_(claim_ids),  # type: ignore[union-attr]
            )
        )
    ).all()


async def owner_assessment_revision(db: AsyncSession, organization_id: str) -> int:
    """One indexed row, including committed changes from every database writer.

    Tokens come from a nontransactional sequence but their visibility is
    transactional. A rollback cannot reuse a token already put in a source cache.
    """
    revision = (
        await db.exec(
            select(CrmOwnerAssessmentRevision.revision).where(
                CrmOwnerAssessmentRevision.organization_id == organization_id
            )
        )
    ).first()
    return revision if revision is not None else 0


async def fetch_owner_registry_totals(db: AsyncSession, list_id, organization_id):
    statement = text(
        _OWNER_REGISTRY_BASE_SQL
        + """
        , profile_rollup AS (
            SELECT
                owner_key_sql,
                count(*) AS property_count,
                count(*) FILTER (
                    WHERE lead_id IS NOT NULL
                    AND ownership_status IN (
                        'verified_current_owner',
                        'probable_current_owner'
                    )
                ) AS rental_ready_count,
                count(*) FILTER (
                    WHERE NOT (
                        lead_id IS NOT NULL
                        AND ownership_status IN (
                            'verified_current_owner',
                            'probable_current_owner'
                        )
                    )
                    AND ownership_status <> 'former_owner'
                ) AS registry_count,
                count(*) FILTER (
                    WHERE ownership_status = 'former_owner'
                ) AS prior_count,
                count(*) FILTER (
                    WHERE ownership_status IN (
                        'unit_linked_unverified',
                        'conflicting_claim',
                        'insufficient_property_data',
                        'registry_not_observed',
                        'unmatched'
                    )
                ) AS review_count
            FROM properties
            GROUP BY owner_key_sql
        )
        SELECT
            count(*) FILTER (WHERE rental_ready_count > 0)
                AS rental_owner_profiles,
            count(*) FILTER (WHERE registry_count > 0)
                AS registry_owner_profiles,
            count(*) FILTER (WHERE prior_count > 0)
                AS prior_owner_profiles,
            count(*) FILTER (WHERE review_count > 0)
                AS needs_review_profiles,
            count(*) FILTER (WHERE property_count > 1)
                AS multi_property_owners
        FROM profile_rollup
        """
    )
    row = (
        (
            await db.exec(
                statement,
                params={"organization_id": organization_id, "owner_list_id": list_id},
            )
        )
        .mappings()
        .one()
    )
    return row


async def list_contact_lists(db: AsyncSession, organization_id):
    return (
        await db.exec(
            select(CrmContactList)
            .where(CrmContactList.organization_id == organization_id)
            .order_by(CrmContactList.updated_at.desc())
        )
    ).all()


async def list_claims_for_lists(db: AsyncSession, ids, organization_id):
    return (
        await db.exec(
            select(CrmPropertyContactClaim).where(
                CrmPropertyContactClaim.organization_id == organization_id,
                CrmPropertyContactClaim.list_id.in_(ids),  # type: ignore[union-attr]
            )
        )
    ).all()


async def get_contact_list(db: AsyncSession, list_id, organization_id):
    return (
        await db.exec(
            select(CrmContactList).where(
                CrmContactList.id == list_id,
                CrmContactList.organization_id == organization_id,
            )
        )
    ).first()


async def list_claims_for_list(db: AsyncSession, list_id, organization_id):
    return (
        await db.exec(
            select(CrmPropertyContactClaim).where(
                CrmPropertyContactClaim.organization_id == organization_id,
                CrmPropertyContactClaim.list_id == list_id,
            )
        )
    ).all()


async def list_lead_claims_with_lists(db: AsyncSession, lead_id, organization_id):
    return (
        await db.exec(
            select(CrmPropertyContactClaim, CrmContactList)
            .join(CrmContactList, CrmContactList.id == CrmPropertyContactClaim.list_id)
            .where(
                CrmPropertyContactClaim.organization_id == organization_id,
                CrmPropertyContactClaim.lead_id == lead_id,
            )
            .order_by(CrmPropertyContactClaim.confidence_score.desc())
        )
    ).all()


async def count_owner_properties(db: AsyncSession, organization_id, owner_keys):
    return (
        await db.exec(
            select(
                CrmPropertyContactClaim.owner_key,
                func.count(func.distinct(CrmPropertyContactClaim.property_key)),
            )
            .where(
                CrmPropertyContactClaim.organization_id == organization_id,
                CrmPropertyContactClaim.owner_key.in_(owner_keys),
            )
            .group_by(CrmPropertyContactClaim.owner_key)
        )
    ).all()


async def list_claims_with_lists(db: AsyncSession, organization_id):
    return (
        await db.exec(
            select(CrmPropertyContactClaim, CrmContactList)
            .join(CrmContactList, CrmContactList.id == CrmPropertyContactClaim.list_id)
            .where(CrmPropertyContactClaim.organization_id == organization_id)
        )
    ).all()


async def owner_sources_only(db: AsyncSession, organization_id: str) -> bool:
    modes = (
        await db.exec(
            select(CrmContactImport.owner_source_metadata["mode"].as_string())
            .where(
                CrmContactImport.organization_id == organization_id,
                exists(
                    select(CrmPropertyContactClaim.id).where(
                        CrmPropertyContactClaim.import_id == CrmContactImport.id,
                        CrmPropertyContactClaim.organization_id == organization_id,
                    )
                ),
            )
            .distinct()
        )
    ).all()
    return bool(modes) and all(
        mode in {"source_only", "source_transaction_matched"} for mode in modes
    )
