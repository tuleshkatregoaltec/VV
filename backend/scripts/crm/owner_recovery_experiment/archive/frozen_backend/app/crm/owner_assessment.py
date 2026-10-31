"""One tenant-scoped, short-lived assessment for every CRM ownership consumer."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import logging
import time
import weakref
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import orjson
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.cache import RedisCache
from app.crm import owner_repository
from app.crm.identity import ParsedContact
from app.crm.import_models import CrmOwnerHistorySummary
from app.crm.owner_namespaces import history_unit_aliases, registry_namespace
from app.crm.source_lifecycle import annotate_source_lifecycle

ASSESSMENT_VERSION = "owner-assessment-16-qualified-history"
ASSESSMENT_TTL_SECONDS = 3600
_BUILD_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
_DATE_FIELDS = {
    "transaction_date",
    "latest_sale_date",
    "later_sale_date",
    "lease_end",
    "matched_sale_date",
    "sale_anchor_date",
}
_DATETIME_FIELDS = {"created_at", "updated_at"}
logger = logging.getLogger(__name__)
_cache: RedisCache | None = None
_recent: tuple[str, float, OwnerAssessmentSnapshot] | None = None


@dataclass
class OwnerAssessmentSnapshot:
    rows: list[dict[str, Any]]
    summary: CrmOwnerHistorySummary
    checked_at: datetime
    warehouse_status: str
    cached_at: datetime | None = None


def summarize_assessment_rows(
    snapshot: OwnerAssessmentSnapshot, rows: list[dict[str, Any]]
) -> CrmOwnerHistorySummary:
    from app.crm.import_events import IMPORT_RESOLVER_VERSION
    from app.crm.source_audit import source_audit_for_row

    associations = {
        (row["canonical_owner_key"], row["property_identity"]): row["assessed_status"]
        for row in rows
        if row["property_identity"] is not None
        and (
            not (match := (source_audit_for_row(row) or {}).get("transaction_match"))
            or match.get("owner_category") in {"current", "former"}
        )
    }
    counts = Counter(associations.values())
    versions = Counter(
        str(row.get("claim_resolver_version") or row.get("import_resolver_version") or "legacy")
        for row in rows
    )
    return CrmOwnerHistorySummary(
        source_event_count=len(rows),
        identifiable_property_count=len({identity for _, identity in associations}),
        owner_property_count=len(associations),
        verified_current_count=counts["verified_current_owner"],
        probable_current_count=counts["probable_current_owner"],
        former_count=counts["former_owner"],
        unverified_former_count=counts["unverified_former_owner"],
        unresolved_count=sum(
            count
            for status, count in counts.items()
            if status not in {"verified_current_owner", "probable_current_owner", "former_owner"}
        ),
        invalid_identity_source_count=sum(row["property_identity"] is None for row in rows),
        legacy_source_event_count=sum(
            not source_audit_for_row(row)
            and (row.get("claim_resolver_version") or row.get("import_resolver_version"))
            != IMPORT_RESOLVER_VERSION
            for row in rows
        ),
        resolver_versions=dict(versions),
        checked_at=snapshot.checked_at,
        warehouse_status=snapshot.warehouse_status,
        assessment_version=ASSESSMENT_VERSION,
    )


async def capture_owner_evidence(
    candidates: list[ParsedContact],
) -> dict[str, list[dict[str, Any]]]:
    """Load the exact alias and DXBI sale inputs without changing source candidates."""
    from app.crm import owner_queries
    from app.market.reference import property_name_lookup_key

    properties = {
        (
            property_name_lookup_key(candidate.building_name or candidate.project_name),
            unit,
        )
        for candidate in candidates
        if candidate.unit_number
        for unit in history_unit_aliases({**vars(candidate), "property_type": "Villa"})
    }
    names = sorted({name for name, _ in properties})
    aliases = (
        await owner_queries.fetch_assessment_building_aliases({"names": names}) if names else []
    )
    names_by_id: dict[str, set[str]] = defaultdict(set)
    ids_by_name: dict[str, set[str]] = defaultdict(set)
    for row in aliases:
        names_by_id[str(row["building_id"])].add(str(row["name_key"]))
        ids_by_name[str(row["name_key"])].add(str(row["building_id"]))
    expanded = set(properties)
    for name, unit in properties:
        for building in ids_by_name[name]:
            expanded.update((alias, unit) for alias in names_by_id[building])
    registry = await owner_queries.fetch_assessment_sales({"properties": sorted(expanded)})
    return {"aliases": aliases, "sales": registry}


def match_owner_evidence(
    candidates: list[ParsedContact], bundle: dict[str, list[dict[str, Any]]]
) -> dict[str, list[dict[str, Any]]]:
    """Match captured evidence; mutate only the supplied, independently owned candidates."""
    from app.crm.identity import _location_key, _normalize_unit, _property_scopes_compatible
    from app.crm.owner_matching_policy import qualified
    from app.crm.ownership import (
        _amount_match_source,
        _canonical_alias_id,
        _canonical_source_location,
    )
    from app.market.reference import property_name_lookup_key, unit_lookup_key

    probes: dict[tuple[str, ...], ParsedContact] = {}
    grouped: dict[tuple[str, ...], list[ParsedContact]] = defaultdict(list)
    fields = ("area_name", "project_name", "building_name", "unit_number", "property_type")
    for candidate in candidates:
        source = _canonical_source_location(candidate)
        key = (
            tuple(getattr(candidate, name) for name in fields)
            + tuple(str(source.get(name) or "") for name in fields)
            + tuple(
                str((candidate.evidence.get("original_identifiers") or {}).get(name) or "")
                for name in ("unit_number", "building_number", "property_number", "plot_number")
            )
        )
        grouped[key].append(candidate)
        if key not in probes:
            probe = copy.copy(candidate)
            probe.evidence = {"source_fields": source}
            if "original_identifiers" in candidate.evidence:
                probe.evidence["original_identifiers"] = candidate.evidence["original_identifiers"]
                probe.evidence["match_source"] = _amount_match_source(candidate)
            probes[key] = probe
    aliases, registry = bundle["aliases"], bundle["sales"]
    names_by_id: dict[str, set[str]] = defaultdict(set)
    ids_by_name: dict[str, set[str]] = defaultdict(set)
    for row in aliases:
        names_by_id[str(row["building_id"])].add(str(row["name_key"]))
        ids_by_name[str(row["name_key"])].add(str(row["building_id"]))
    by_name_unit: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in registry:
        for name in {
            property_name_lookup_key(str(row.get("building_name") or "")),
            property_name_lookup_key(str(row.get("project_name") or "")),
        } - {""}:
            for unit in history_unit_aliases(row):
                by_name_unit[(name, unit)].append(row)
    scoped_aliases: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for alias in aliases:
        scoped_aliases[
            (
                str(alias["name_key"]),
                str(alias["community_key"]),
                str(alias.get("project_key") or ""),
            )
        ].add(str(alias["building_id"]))
    sales: dict[str, list[dict[str, Any]]] = {}
    scopes_by_key: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for probe in probes.values():
        name = property_name_lookup_key(probe.building_name or probe.project_name)
        names = {name}
        for building in ids_by_name[name]:
            names.update(names_by_id[building])
        matched: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
        for candidate_name in names:
            for row in by_name_unit.get((candidate_name, unit_lookup_key(probe.unit_number)), []):
                if "original_identifiers" in probe.evidence and not qualified(
                    probe.evidence["match_source"], row
                ):
                    continue
                namespace = registry_namespace({**vars(probe), "property_type": "Villa"})
                same_namespace = bool(namespace and namespace == registry_namespace(row))
                if not same_namespace and not _property_scopes_compatible(vars(probe), row):
                    continue
                alias = _canonical_alias_id(probe, row, scoped_aliases)
                if candidate_name != name and not alias:
                    continue
                identity = registry_namespace(row) or (
                    _location_key(str(row.get("area_name") or "")),
                    f"analytics:{alias}"
                    if alias
                    else _location_key(
                        str(row.get("building_name") or row.get("project_name") or "")
                    ),
                    unit_lookup_key(probe.unit_number),
                )
                matched[identity][str(row["sale_key"])] = row
        if len(matched) != 1:
            probe.evidence["sales_lookup"] = {
                "status": "ambiguous_location" if matched else "unit_not_observed"
            }
            if matched:
                probe.evidence["scoped_identity_collision"] = True
            continue
        selected = sorted(
            next(iter(matched.values())).values(),
            key=lambda row: (row["transaction_date"], str(row["sale_key"])),
        )
        canonical = selected[0]
        probe.area_name = str(canonical.get("area_name") or probe.area_name)
        probe.project_name = str(canonical.get("project_name") or probe.project_name)
        probe.building_name = str(
            canonical.get("building_name") or canonical.get("project_name") or probe.building_name
        )
        probe.unit_number = _normalize_unit(canonical["unit_number"])
        scopes_by_key[probe.property_key].add(
            (_location_key(probe.area_name), _location_key(probe.project_name))
        )
        sales[probe.property_key] = selected
    for probe in probes.values():
        if len(scopes_by_key[probe.property_key]) > 1:
            probe.evidence["scoped_identity_collision"] = True
            sales[probe.property_key] = []
    for key, probe in probes.items():
        for candidate in grouped[key]:
            for name in fields[:4]:
                setattr(candidate, name, getattr(probe, name))
            for name in ("sales_lookup", "scoped_identity_collision", "registry_property_scope"):
                candidate.evidence.pop(name, None)
                if name in probe.evidence:
                    candidate.evidence[name] = probe.evidence[name]
    return sales


async def _fresh_sales(
    valid: list[tuple[dict[str, Any], ParsedContact]],
) -> dict[str, list[dict[str, Any]]]:
    candidates = [candidate for _, candidate in valid]
    bundle = await capture_owner_evidence(candidates)
    return await asyncio.to_thread(match_owner_evidence, candidates, bundle)


def _cache_client() -> RedisCache:
    global _cache
    if _cache is None:
        from app.config import settings

        _cache = RedisCache(settings.REDIS_URL, settings.REDIS_PASSWORD)
    return _cache


async def _source_revision(db: AsyncSession, organization_id: str) -> str:
    row = await owner_repository.owner_assessment_revision(db, organization_id)
    return hashlib.sha256(orjson.dumps(tuple(row), default=RedisCache._json_default)).hexdigest()[
        :24
    ]


def _encode(snapshot: OwnerAssessmentSnapshot) -> str:
    payload = {
        "rows": snapshot.rows,
        "summary": snapshot.summary.model_dump(mode="json"),
        "checked_at": snapshot.checked_at.isoformat(),
        "warehouse_status": snapshot.warehouse_status,
        "cached_at": snapshot.cached_at.isoformat() if snapshot.cached_at else None,
    }
    return base64.b64encode(
        zlib.compress(orjson.dumps(payload, default=RedisCache._json_default), level=1)
    ).decode()


def _decode(payload: str) -> OwnerAssessmentSnapshot:
    data = orjson.loads(zlib.decompress(base64.b64decode(payload)))
    for row in data["rows"]:
        for name in _DATE_FIELDS:
            if row.get(name):
                row[name] = date.fromisoformat(row[name])
        for name in _DATETIME_FIELDS:
            if row.get(name):
                row[name] = datetime.fromisoformat(row[name])
        if row.get("property_identity"):
            row["property_identity"] = tuple(row["property_identity"])
    return OwnerAssessmentSnapshot(
        rows=data["rows"],
        summary=CrmOwnerHistorySummary.model_validate(data["summary"]),
        checked_at=datetime.fromisoformat(data["checked_at"]),
        warehouse_status=data["warehouse_status"],
        cached_at=datetime.fromisoformat(data["cached_at"]) if data.get("cached_at") else None,
    )


async def _source_rows(
    db: AsyncSession, organization_id: str, revision: str | None
) -> list[dict[str, Any]]:
    if revision is None:
        return await owner_repository.list_owner_history_rows(db, organization_id=organization_id)
    key = f"crm:owner-sources:{ASSESSMENT_VERSION}:{hashlib.sha256(organization_id.encode()).hexdigest()}"
    cache = _cache_client()
    cached = await cache.get(key)
    if isinstance(cached, dict) and cached.get("revision") == revision:
        payload = cached["data"]
        try:
            rows = await asyncio.to_thread(
                lambda: orjson.loads(zlib.decompress(base64.b64decode(payload)))
            )
            for row in rows:
                for field in _DATE_FIELDS:
                    if row.get(field):
                        row[field] = date.fromisoformat(row[field])
                for field in _DATETIME_FIELDS:
                    if row.get(field):
                        row[field] = datetime.fromisoformat(row[field])
            return rows
        except (ValueError, TypeError, KeyError, zlib.error):
            logger.warning("Invalid CRM ownership source cache")
    rows = await owner_repository.list_owner_history_rows(db, organization_id=organization_id)
    payload = await asyncio.to_thread(
        lambda: base64.b64encode(
            zlib.compress(orjson.dumps(rows, default=RedisCache._json_default), level=1)
        ).decode()
    )
    await cache.set(key, {"revision": revision, "data": payload}, expire=3600)
    return rows


def _candidate(row: dict[str, Any]) -> ParsedContact:
    names = (
        "contact_name",
        "area_name",
        "project_name",
        "building_name",
        "unit_number",
        "property_type",
        "party_role",
        "procedure_type",
    )
    return ParsedContact(
        **{name: str(row.get(name) or "") for name in names},
        source_sheet=str(row.get("source_sheet") or ""),
        source_row_number=int(row.get("source_row_number") or 0),
        phone_primary=row.get("phone_primary"),
        phone_alternate=row.get("phone_alternate"),
        email_primary=row.get("email_primary"),
        transaction_date=row.get("transaction_date"),
        transaction_price_aed=row.get("transaction_price_aed"),
        row_fingerprint=str(row["id"]),
        evidence={
            key: value for key, value in (row.get("evidence") or {}).items() if value is not None
        },
    )


def _project(
    rows: list[dict[str, Any]], checked_at: datetime, warehouse_status: str
) -> OwnerAssessmentSnapshot:
    from app.crm.owner_projection import (
        _projection_owner_key,
        _property_identity,
        project_owner_history,
    )

    identities = {row["id"]: _property_identity(row) for row in rows}
    owners = {row["id"]: _projection_owner_key(row) for row in rows}
    observed = [
        (row["ownership_status"], row.get("match_reason", ""), row["confidence_score"])
        for row in rows
    ]
    for row in rows:
        row["event_assessed_status"] = row["assessed_status"]
        row["event_assessed_confidence_score"] = row["assessed_confidence_score"]
        row["ownership_status"] = row["assessed_status"]
        row["match_reason"] = row["assessed_reason"]
        row["confidence_score"] = row["assessed_confidence_score"]
    try:
        summary, statuses = project_owner_history(
            rows, rows, identities_by_id=identities, owner_keys=owners
        )
    finally:
        for row, original in zip(rows, observed, strict=True):
            row["ownership_status"], row["match_reason"], row["confidence_score"] = original
    supporting_scores: dict[tuple[str, tuple[str, str]], tuple[date, int]] = {}
    for row in rows:
        association = (owners[row["id"]], identities[row["id"]])
        result = statuses.get(association)
        if result and row["event_assessed_status"] == result[0]:
            support = (
                row.get("matched_sale_date") or row.get("transaction_date") or date.min,
                row["event_assessed_confidence_score"],
            )
            supporting_scores[association] = max(
                supporting_scores.get(association, (date.min, 0)), support
            )
    for row in rows:
        identity = identities[row["id"]]
        owner = owners[row["id"]]
        row["canonical_owner_key"] = owner
        row["property_identity"] = identity
        row["assessed_status"], row["assessed_reason"] = statuses.get(
            (owner, identity),
            ("insufficient_property_data", "The source has no valid scoped property identity."),
        )
        support = supporting_scores.get((owner, identity))
        row["assessed_confidence_score"] = (
            support[1]
            if support
            else (0 if row["assessed_status"] == "insufficient_property_data" else 40)
        )
        row["supported_former"] = row["assessed_status"] == "former_owner"
    summary = summary.model_copy(
        update={
            "checked_at": checked_at,
            "warehouse_status": warehouse_status,
            "assessment_version": ASSESSMENT_VERSION,
        }
    )
    return OwnerAssessmentSnapshot(rows, summary, checked_at, warehouse_status)


async def _build(
    db: AsyncSession,
    organization_id: str,
    *,
    source_revision: str | None = None,
    warehouse_available: bool = True,
) -> OwnerAssessmentSnapshot:
    from app.crm.owner_projection import _property_identity
    from app.crm.source_audit import source_audit_for_row

    rows = await _source_rows(db, organization_id, source_revision)
    valid = await asyncio.to_thread(
        lambda: [
            (row, _candidate(row))
            for row in rows
            if not source_audit_for_row(row) and _property_identity(row) is not None
        ]
    )
    for row, candidate in valid:
        candidate.evidence["source_import_scope"] = str(row.get("import_id") or "")
    await asyncio.to_thread(annotate_source_lifecycle, [candidate for _, candidate in valid])
    checked_at = datetime.now(timezone.utc)
    if rows and all(source_audit_for_row(row) for row in rows):
        return await asyncio.to_thread(_source_snapshot, rows, checked_at)
    warehouse_status = "available"
    try:
        if not warehouse_available:
            raise RuntimeError("Ownership evidence metadata is unavailable")
        async with asyncio.timeout(30):
            sales = await _fresh_sales(valid) if valid else {}
    except Exception:
        # Never reuse saved current-owner labels after an unavailable or partial lookup.
        logger.warning("CRM ownership warehouse assessment unavailable")
        warehouse_status = "unavailable"
        sales = {}
    return await asyncio.to_thread(
        _finish_assessment, rows, valid, sales, checked_at, warehouse_status
    )


def _finish_assessment(rows, valid, sales, checked_at, warehouse_status) -> OwnerAssessmentSnapshot:
    from app.crm.ownership import _apply_evidence
    from app.crm.source_audit import source_audit_for_row

    source_rows = [row for row in rows if source_audit_for_row(row)]
    rows = [row for row in rows if not source_audit_for_row(row)]
    valid = [(row, candidate) for row, candidate in valid if not source_audit_for_row(row)]
    for row, candidate in valid:
        candidate.evidence["source_import_scope"] = str(
            row.get("import_id") or row.get("source_filename") or ""
        )
    annotate_source_lifecycle([candidate for _, candidate in valid])
    for row in rows:
        row["assessed_status"] = "insufficient_property_data"
        row["assessed_reason"] = "The source has no valid scoped property identity."
        row["assessed_confidence_score"] = 0
    for row, candidate in valid:
        row["source_property_key"] = row["property_key"]
        if warehouse_status == "available":
            _apply_evidence(candidate, sales=sales, rentals={})
            for name in ("area_name", "project_name", "building_name", "unit_number"):
                row[name] = getattr(candidate, name)
            row["property_key"] = candidate.property_key
            if (
                row["source_property_key"] != candidate.property_key
                or candidate.evidence.get("sales_lookup")
                or candidate.evidence.get("scoped_identity_collision")
            ):
                for name in ("lead_id", "unit_candidate_key", "lease_end", "annual_rent_aed"):
                    row[name] = None
            row["latest_sale_date"] = candidate.latest_sale_date
            row["latest_sale_price_aed"] = candidate.latest_sale_price_aed
            row["later_sale_date"] = candidate.later_sale_date
            row["matched_sale_date"] = (
                date.fromisoformat(candidate.evidence["matched_sale_date"])
                if candidate.evidence.get("matched_sale_date")
                else None
            )
            row["sale_anchor_key"] = candidate.evidence.get("sale_anchor_key")
            row["sale_anchor_date"] = row["matched_sale_date"] if row["sale_anchor_key"] else None
            row["identity_collision"] = candidate.evidence.get("scoped_identity_collision", False)
            row["registry_inferred_sale"] = bool(candidate.evidence.get("registry_inferred_sale"))
            row["assessed_status"] = candidate.ownership_status
            row["assessed_reason"] = candidate.match_reason
            row["assessed_confidence_score"] = candidate.confidence_score
        else:
            row["registry_inferred_sale"] = False
            for name in (
                "latest_sale_date",
                "latest_sale_price_aed",
                "later_sale_date",
                "matched_sale_date",
                "sale_anchor_key",
                "sale_anchor_date",
            ):
                row[name] = None
            row["assessed_status"] = (
                "unverified_former_owner"
                if candidate.party_role == "Seller"
                else "unit_linked_unverified"
            )
            row["assessed_reason"] = (
                "Registry assessment is unavailable; current or former ownership cannot be confirmed."
            )
    for row, candidate in valid:
        row["source_lifecycle"] = candidate.evidence["source_lifecycle"]
    for row in rows:
        row.pop("evidence", None)
    del valid, sales
    if warehouse_status == "unavailable":
        checked_at = datetime.now(timezone.utc)
    snapshot = _project(rows, checked_at, warehouse_status)
    if source_rows:
        source = _source_snapshot(source_rows, checked_at)
        snapshot.rows.extend(source.rows)
        snapshot.summary = summarize_assessment_rows(snapshot, snapshot.rows)
    if warehouse_status == "unavailable":
        snapshot.checked_at = datetime.now(timezone.utc)
        snapshot.summary.checked_at = snapshot.checked_at
    return snapshot


def _source_snapshot(rows, checked_at) -> OwnerAssessmentSnapshot:
    from app.crm.owner_projection import _projection_owner_key, _property_identity
    from app.crm.source_audit import source_audit_for_row

    for row in rows:
        audit = source_audit_for_row(row)
        row["source_audit"] = audit
        match = audit.get("transaction_match") or {}
        row["canonical_owner_key"] = match.get("canonical_owner_key") or _projection_owner_key(row)
        row["property_identity"] = _property_identity(row)
        candidate = bool(audit["owner_candidate"])
        row["assessed_status"] = (
            "probable_current_owner"
            if candidate
            else (
                "unverified_former_owner"
                if row.get("party_role", "").casefold() == "seller"
                else "unit_linked_unverified"
            )
        )
        row["assessed_reason"] = (
            "Reviewed source-only owner candidate, as of the supplied snapshot; "
            "DXBI/registry ownership has not been checked. "
            if candidate
            else "Source history retained without a current-owner claim. "
        ) + audit["decision_basis"]
        row["assessed_confidence_score"] = 60 if candidate else 0
        row["event_assessed_status"] = row["assessed_status"]
        row["event_assessed_confidence_score"] = row["assessed_confidence_score"]
        row["supported_former"] = False
        for field in (
            "latest_sale_date",
            "latest_sale_price_aed",
            "later_sale_date",
            "matched_sale_date",
            "sale_anchor_key",
            "sale_anchor_date",
        ):
            row[field] = None
        if match:
            category = match.get("owner_category")
            row["assessed_status"] = {
                "current": "probable_current_owner",
                "former": "former_owner",
            }.get(category, "unit_linked_unverified")
            row["assessed_reason"] = str(match.get("reason") or "No supported owner association.")
            row["assessed_confidence_score"] = (
                (85 if category == "former" else 70)
                if category and match.get("status") == "matched"
                else (60 if category else 0)
            )
            row["event_assessed_status"] = row["assessed_status"]
            row["event_assessed_confidence_score"] = row["assessed_confidence_score"]
            row["supported_former"] = category == "former"
            for field in ("latest_sale_date", "later_sale_date"):
                value = match.get(field)
                row[field] = date.fromisoformat(value) if isinstance(value, str) else value
            row["latest_sale_price_aed"] = match.get("latest_sale_price_aed")
    status = (
        "available"
        if any((source_audit_for_row(row) or {}).get("transaction_match") for row in rows)
        else "not_requested"
    )
    capture_dates = [
        datetime.fromisoformat(match["matched_at"])
        for row in rows
        if (match := (source_audit_for_row(row) or {}).get("transaction_match"))
        and match.get("matched_at")
    ]
    if capture_dates:
        checked_at = min(capture_dates)
    snapshot = OwnerAssessmentSnapshot(rows, None, checked_at, status)
    snapshot.summary = summarize_assessment_rows(snapshot, rows)
    return snapshot


async def _warehouse_revision() -> str | None:
    from app.crm import owner_queries

    try:
        return await owner_queries.fetch_assessment_source_fingerprint()
    except Exception:
        logger.warning("CRM ownership evidence fingerprint unavailable")
        return None


def _remaining_lifetime(snapshot: OwnerAssessmentSnapshot) -> float:
    expiry = ASSESSMENT_TTL_SECONDS if snapshot.warehouse_status != "unavailable" else 10
    return (
        expiry
        - (datetime.now(timezone.utc) - (snapshot.cached_at or snapshot.checked_at)).total_seconds()
    )


def _unavailable_snapshot(snapshot: OwnerAssessmentSnapshot) -> OwnerAssessmentSnapshot:
    valid = [
        (row, _candidate(row)) for row in snapshot.rows if row["property_identity"] is not None
    ]
    return _finish_assessment(snapshot.rows, valid, {}, datetime.now(timezone.utc), "unavailable")


async def get_owner_assessment(
    db: AsyncSession, *, organization_id: str
) -> OwnerAssessmentSnapshot:
    """Reuse the bounded tenant/source/rules/evidence projection while inputs match.

    ``checked_at`` records evidence capture, independently of cache completion.
    Physical warehouse changes invalidate immediately; mutable inputs still lack
    an atomic publication contract. Metadata failure never reuses verified labels.
    """
    global _recent
    tenant = hashlib.sha256(organization_id.encode()).hexdigest()

    async def cache_identity():
        revision = await _source_revision(db, organization_id)
        source_only = await owner_repository.owner_sources_only(db, organization_id)
        warehouse_revision = "not_requested" if source_only else await _warehouse_revision()
        key = (
            f"crm:owner-assessment:{ASSESSMENT_VERSION}:{tenant}:"
            f"{revision}:{warehouse_revision or 'unavailable'}"
        )
        return revision, warehouse_revision, key

    revision, warehouse_revision, key = await cache_identity()
    if (
        _recent
        and _recent[0] == key
        and (_recent[2].warehouse_status == "available" or _recent[1] > time.monotonic())
    ):
        return _recent[2]
    cache = _cache_client()
    lock = _BUILD_LOCKS.setdefault(tenant, asyncio.Lock())
    waiting = lock.locked()
    async with lock:
        # A queued request may have waited through an import or warehouse change.
        if waiting:
            revision, warehouse_revision, key = await cache_identity()
        if (
            _recent
            and _recent[0] == key
            and (_recent[2].warehouse_status == "available" or _recent[1] > time.monotonic())
        ):
            return _recent[2]
        payload = await cache.get(key)
        if payload:
            try:
                snapshot = await asyncio.to_thread(_decode, payload)
                remaining = _remaining_lifetime(snapshot)
                if remaining > 0:
                    _recent = (key, time.monotonic() + remaining, snapshot)
                    return snapshot
            except (ValueError, TypeError, KeyError, zlib.error):
                logger.warning("Invalid CRM ownership assessment cache")
        snapshot = await _build(
            db,
            organization_id,
            source_revision=revision,
            warehouse_available=warehouse_revision is not None,
        )
        current_revision = await _source_revision(db, organization_id)
        current_warehouse = (
            "not_requested"
            if warehouse_revision == "not_requested"
            else await _warehouse_revision()
        )
        stable = revision == current_revision and warehouse_revision == current_warehouse
        if not stable:
            # Never publish confirmed ownership across changing evidence inputs.
            snapshot = await asyncio.to_thread(_unavailable_snapshot, snapshot)
            return snapshot
        snapshot.cached_at = datetime.now(timezone.utc)
        payload = await asyncio.to_thread(_encode, snapshot)
        remaining = _remaining_lifetime(snapshot)
        if remaining > 0:
            await cache.set(key, payload, expire=max(1, int(remaining)))
            _recent = (key, time.monotonic() + remaining, snapshot)
        return snapshot
