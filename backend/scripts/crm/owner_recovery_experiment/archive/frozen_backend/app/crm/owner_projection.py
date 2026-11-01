"""Tenant-scoped source history and conservative owner/property evidence counts."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from app.crm.identity import (
    _identity_text,
    _location_key,
    _normalize_email,
    _normalize_phone,
    _normalize_unit,
    _owner_key,
    _property_scopes_compatible,
)
from app.crm.import_events import IMPORT_RESOLVER_VERSION, event_family
from app.crm.import_models import (
    CrmOwnerHistorySummary,
)

_CURRENT = {"verified_current_owner", "probable_current_owner"}
_DECISIVE = _CURRENT | {"former_owner"}
_EMPTY = {"", "-", "n/a", "na", "none", "null", "unknown", "nan"}


def _property_identity(row: dict[str, Any]) -> tuple[str, str] | None:
    """Validate the persisted grammar and location scope; never count source keys."""
    from app.crm.source_audit import source_audit_for_row

    audit = source_audit_for_row(row)
    if audit and audit.get("mode") == "source_only":
        return ("source_audit", f"{row['import_id']}:{audit['reference_id']}")
    key = str(row.get("property_key") or "").strip()
    if re.fullmatch(r"dld-land:\d+:[a-zA-Z0-9.]+:[a-zA-Z0-9.]+", key):
        return ("land", key) if row.get("cadastral_key") == key else None
    if key.count("|") != 1:
        return None
    location, unit = key.split("|", 1)
    locations = {
        _location_key(str(row.get(field) or ""))
        for field in ("building_name", "project_name")
        if str(row.get(field) or "").strip().casefold() not in _EMPTY
    }
    source_unit = _normalize_unit(str(row.get("unit_number") or "")).casefold()
    if (
        not re.fullmatch(r"[a-z0-9]+", location)
        or location in _EMPTY
        or location not in locations
        or unit.casefold() in _EMPTY
        or not source_unit
        or source_unit in _EMPTY
        or unit.casefold() != source_unit
    ):
        return None
    # The display key historically omits area. Keep incompatible areas separate
    # rather than merging identically named buildings across Dubai.
    area = str(row.get("area_name") or "").strip()
    return (_location_key(area) if area.casefold() not in _EMPTY else "", key)


def _family(row: dict[str, Any]) -> str:
    if row.get("registry_inferred_sale") and not str(row.get("procedure_type") or "").strip():
        return "sale"
    if row.get("event_family"):
        return str(row["event_family"])
    procedure = str(row.get("procedure_type") or "")
    if not procedure and row.get("party_role") in {"Buyer", "Seller"}:
        return "sale"  # Explicit legacy sale semantics, before family persistence.
    return event_family(procedure)


def _projection_owner_key(row: dict[str, Any]) -> str:
    """Canonical read identity; persisted keys continue to own agent workspaces."""
    from app.crm.source_audit import source_audit_for_row

    audit = source_audit_for_row(row)
    if audit and audit.get("mode") == "source_only":
        return str(audit["canonical_owner_key"])
    name = _identity_text(str(row.get("contact_name") or ""))
    identity = _property_identity(row)
    phone = _normalize_phone(row.get("phone_primary")) or _normalize_phone(
        row.get("phone_alternate")
    )
    email = _normalize_email(row.get("email_primary"))
    if not name or name in _EMPTY or (not (phone or email) and identity is None):
        return str(row["owner_key"])
    return _owner_key(
        contact_name=name,
        phone_primary=phone,
        phone_alternate=None,
        email_primary=email,
        property_key=f"{identity[0]}|{identity[1]}" if identity else "",
    )


def _evidence_date(row: dict[str, Any]) -> date:
    if row["ownership_status"] == "former_owner" and not row.get("matched_sale_date"):
        return max(row.get("transaction_date") or date.min, row.get("later_sale_date") or date.min)
    if row.get("matched_sale_date"):
        return row["matched_sale_date"]
    if row["ownership_status"] in _CURRENT:
        source = row.get("transaction_date")
        registry = row.get("latest_sale_date")
        # The resolver permits a two-day source/registration date offset. A
        # distant latest sale is subsequent evidence, never a new acquisition.
        if source and registry and abs((source - registry).days) <= 2:
            return registry
        return source or registry or date.min
    return row.get("transaction_date") or date.min


def _complementary_parties(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """A paired source transaction can identify two tentative contacts, not two buyers."""
    return bool(
        {left.get("party_role"), right.get("party_role")} == {"Buyer", "Seller"}
        and left.get("sale_anchor_key")
        and left.get("sale_anchor_key") == right.get("sale_anchor_key")
        and left.get("sale_anchor_date")
        and left.get("sale_anchor_date") == right.get("sale_anchor_date")
        and left.get("transaction_date")
        and left.get("transaction_date") == right.get("transaction_date")
        and (left.get("transaction_price_aed") or 0) > 0
        and left.get("transaction_price_aed") == right.get("transaction_price_aed")
    )


def _resolve_property(
    rows: list[dict[str, Any]],
    owner_keys: dict[int, str],
) -> dict[str, tuple[str, str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scopes = list(
        {(str(row.get("area_name") or ""), str(row.get("project_name") or "")) for row in rows}
    )
    incompatible_scope = any(
        not _property_scopes_compatible(
            {"area_name": area, "project_name": project},
            {"area_name": other_area, "project_name": other_project},
        )
        for index, (area, project) in enumerate(scopes)
        for other_area, other_project in scopes[index + 1 :]
    )
    for row in rows:
        if row["ownership_status"] in _DECISIVE and (
            _family(row) != "sale"
            or row["party_role"] not in {"Buyer", "Seller"}
            or (row["ownership_status"] in _CURRENT and row["party_role"] != "Buyer")
        ):
            row = {
                **row,
                "ownership_status": "unit_linked_unverified",
                "match_reason": "The source procedure and party role do not establish an acquisition or disposal; the observed label requires review.",
            }
        grouped[owner_keys[row["id"]]].append(row)
    resolved: dict[str, tuple[str, str]] = {}
    selected: dict[str, dict[str, Any]] = {}
    registry_latest = max(
        (row.get("latest_sale_date") or date.min for row in rows), default=date.min
    )
    for owner, events in grouped.items():
        decisive = [row for row in events if row["ownership_status"] in _DECISIVE]
        candidates = decisive or events
        latest = max(_evidence_date(row) for row in candidates)
        contemporaries = [row for row in candidates if _evidence_date(row) == latest]
        best = max(contemporaries, key=lambda row: (row["confidence_score"], row["id"]))
        status, reason = str(best["ownership_status"]), str(best.get("match_reason") or "")
        statuses = {row["ownership_status"] for row in contemporaries}
        if statuses & _CURRENT and "former_owner" in statuses:
            status, reason = (
                "conflicting_claim",
                "Acquisition and disposal evidence share a date; their order is unresolved.",
            )
        if status in _CURRENT and registry_latest > latest:
            status, reason = (
                "former_owner",
                "A later registry sale appears in another source event for this property.",
            )
        if status in _CURRENT and any(
            other_owner != owner
            and event["ownership_status"] == "former_owner"
            and event["party_role"] == "Seller"
            and _family(event) == "sale"
            and _evidence_date(event) > latest
            for other_owner, other_events in grouped.items()
            for event in other_events
        ):
            status, reason = (
                "conflicting_claim",
                "A later disposal is reported under another contact identity; ownership shares or identity continuity require review.",
            )
        if status in _CURRENT and any(
            event["ownership_status"] == "conflicting_claim"
            and (event.get("transaction_date") is None or event["transaction_date"] >= latest)
            for event in events
        ):
            status, reason = (
                "conflicting_claim",
                "A newer or undated conflicting claim for this identity requires review before relying on the acquisition.",
            )
        if status in _CURRENT and any(
            (event.get("transaction_date") or date.min) >= latest
            and (
                _family(event)
                in {"gift", "inheritance", "ownership_transfer", "property_change", "lease_to_own"}
                or event["ownership_status"] == "unverified_former_owner"
            )
            for event in rows
        ):
            status, reason = (
                "conflicting_claim",
                "A later or same-day transfer-related event or unverified disposal requires review; the sale alone cannot establish current ownership.",
            )
        if status in _DECISIVE and (
            incompatible_scope or any(row.get("identity_collision") for row in events)
        ):
            status, reason = (
                "conflicting_claim",
                "The property key has conflicting location scopes requiring review.",
            )
        selected[owner] = best
        resolved[owner] = status, reason
    # A later source disposal is not the same transaction merely because both
    # parties happen to match the last known amount.
    for owner, (status, _) in list(resolved.items()):
        if status in _CURRENT and any(
            event["party_role"] == "Seller"
            and event["ownership_status"] in _CURRENT
            and (event.get("transaction_date") or date.min)
            > (selected[owner].get("transaction_date") or date.min)
            and not _complementary_parties(selected[owner], event)
            for event in grouped[owner]
        ):
            resolved[owner] = (
                "conflicting_claim",
                "A later source seller may describe a subsequent disposal; its relationship to the anchored sale requires review.",
            )
    # Sellers describe disposal, never a second current acquisition.
    current_owners = [owner for owner, (status, _) in resolved.items() if status in _CURRENT]
    if len(current_owners) > 1:
        latest = max(_evidence_date(selected[owner]) for owner in current_owners)
        latest_owners = [
            owner for owner in current_owners if _evidence_date(selected[owner]) == latest
        ]
        for owner in current_owners:
            if _evidence_date(selected[owner]) < latest:
                resolved[owner] = (
                    "conflicting_claim",
                    "A later acquisition is reported for another party; the competing ownership evidence requires review.",
                )
            elif len(latest_owners) > 1:
                resolved[owner] = (
                    "conflicting_claim",
                    "Multiple parties have current evidence on the same sale date; ownership shares or event order require review.",
                )
    return resolved


def project_owner_history(
    selected: list[dict[str, Any]],
    context: list[dict[str, Any]],
    *,
    identities_by_id: dict[int, tuple[str, str] | None] | None = None,
    owner_keys: dict[int, str] | None = None,
) -> tuple[CrmOwnerHistorySummary, dict[tuple[str, tuple[str, str]], tuple[str, str]]]:
    properties: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    if identities_by_id is None:
        identities_by_id = {row["id"]: _property_identity(row) for row in context}
    if owner_keys is None:
        owner_keys = {row["id"]: _projection_owner_key(row) for row in context}
    for row in context:
        identity = identities_by_id[row["id"]]
        if identity is not None:
            properties[identity].append(row)
    statuses = {
        (owner, identity): result
        for identity, events in properties.items()
        for owner, result in _resolve_property(events, owner_keys).items()
    }
    identities = {identities_by_id[row["id"]] for row in selected} - {None}
    associations = {
        (owner_keys[row["id"]], identity)
        for row in selected
        if (identity := identities_by_id[row["id"]]) is not None
    }
    counts = Counter(statuses[association][0] for association in associations)
    versions = Counter(
        str(row.get("claim_resolver_version") or row.get("import_resolver_version") or "legacy")
        for row in selected
    )
    summary = CrmOwnerHistorySummary(
        source_event_count=len(selected),
        identifiable_property_count=len(identities),
        owner_property_count=len(associations),
        verified_current_count=counts["verified_current_owner"],
        probable_current_count=counts["probable_current_owner"],
        former_count=counts["former_owner"],
        unverified_former_count=counts["unverified_former_owner"],
        unresolved_count=sum(count for status, count in counts.items() if status not in _DECISIVE),
        invalid_identity_source_count=sum(identities_by_id[row["id"]] is None for row in selected),
        legacy_source_event_count=sum(
            count for version, count in versions.items() if version != IMPORT_RESOLVER_VERSION
        ),
        resolver_versions=dict(versions),
    )
    return summary, statuses
