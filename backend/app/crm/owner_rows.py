"""Per-row owner rules shared by the Owners read path and the stored assessment.

They depend only on the owner models, so ``owners``, ``owner_store`` and
``owner_store_profiles`` can all use them without importing each other.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.crm.identity import _OWNERSHIP_PRIORITY, has_usable_contact, usable_channels
from app.crm.import_models import (
    CrmOwnerProfile,
    CrmOwnerProperty,
    CrmOwnerRegistrySummary,
    CrmOwnerSourceReference,
)
from app.crm.owner_assessment import OwnerAssessmentSnapshot, summarize_assessment_rows


def assessed_contact_groups(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped = {}
    for row in rows:
        identity = (
            tuple(row["property_identity"]) if row["property_identity"] else ("source", row["id"])
        )
        grouped.setdefault((row["canonical_owner_key"], identity), []).append(row)
    return list(grouped.values())


def assessed_list_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """A list's contact counts. Groups never span owners, so counts add up across owners."""
    groups = assessed_contact_groups(rows)
    best = [max(group, key=assessed_row_preference) for group in groups]
    return {
        "total_contacts": len(groups),
        "contact_ready": sum(
            row["property_identity"] is not None
            and bool(row.get("lead_id"))
            and bool(row.get("unit_candidate_key"))
            and source_contact_ready(row["assessed_status"], row.get("party_role"))
            and source_contact_ready(
                row.get("event_assessed_status", row["assessed_status"]), row.get("party_role")
            )
            and has_usable_contact(
                row.get("phone_primary"),
                row.get("phone_alternate"),
                row.get("email_primary"),
                row.get("broker_contact"),
            )
            for row in best
        ),
        "needs_review": sum(row["assessed_status"] in REVIEW_OWNER_STATUSES for row in best),
        "former_owners": sum(row["assessed_status"] == "former_owner" for row in best),
    }


CURRENT_OWNER_STATUSES = {"verified_current_owner", "probable_current_owner"}


REVIEW_OWNER_STATUSES = {
    "probable_current_owner",
    "unit_linked_unverified",
    "conflicting_claim",
    "insufficient_property_data",
    "registry_not_observed",
    "unmatched",
    "unverified_former_owner",
}


def owner_read_keys(
    rows: list[dict[str, Any]], *, shared_keys: set[str] | None = None
) -> dict[str, str]:
    """Keep an existing workspace key when it uniquely identifies this person.

    ``shared_keys`` names the persisted keys that more than one person carries, when
    ``rows`` hold only some of the organization's people.
    """
    by_alias: dict[str, set[str]] = {}
    by_owner: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        canonical = row["canonical_owner_key"]
        by_alias.setdefault(row["owner_key"], set()).add(canonical)
        by_owner.setdefault(canonical, []).append(row)

    def unique(key: str) -> bool:
        if shared_keys is not None:
            return key not in shared_keys
        return len(by_alias[key]) == 1

    return {
        canonical: next(
            (
                row["owner_key"]
                for row in sorted(events, key=lambda event: event["id"])
                if unique(row["owner_key"])
            ),
            canonical,
        )
        for canonical, events in by_owner.items()
    }


def profile_has_channel(profile: CrmOwnerProfile) -> bool:
    return bool(profile.phone_primary or profile.phone_alternate or profile.email_primary)


def source_contact_ready(status: str, party_role: str | None) -> bool:
    return status in CURRENT_OWNER_STATUSES and not (
        status == "probable_current_owner" and party_role == "Seller"
    )


def assessed_row_preference(row: dict[str, Any]) -> tuple:
    current_support = (
        row["assessed_status"] in CURRENT_OWNER_STATUSES
        and row.get("event_assessed_status", row["assessed_status"]) in CURRENT_OWNER_STATUSES
    )
    return (
        current_support,
        current_support and row.get("party_role") == "Buyer",
        row.get("transaction_date") or date.min,
        int(
            row.get(
                "event_assessed_confidence_score",
                row.get("assessed_confidence_score", row["confidence_score"]),
            )
        ),
        row["id"],
    )


def property_contact_ready(item: CrmOwnerProperty, profile: CrmOwnerProfile) -> bool:
    return bool(
        profile_has_channel(profile)
        and item.lead_id
        and item.unit_candidate_key
        and source_contact_ready(item.ownership_status, item.imported_party_role)
    )


# An owner's headline is what they hold now: a current property outranks a sold one. (Per
# property, ``_OWNERSHIP_PRIORITY`` lets a later sale win, which is right for one unit.)
HEADLINE_PRIORITY = {
    "verified_current_owner": 6,
    "probable_current_owner": 5,
    "former_owner": 4,
    "unit_linked_unverified": 3,
    "unverified_former_owner": 2,
    "conflicting_claim": 2,
}


def profile_with_properties(
    profile: CrmOwnerProfile, properties: list[CrmOwnerProperty]
) -> CrmOwnerProfile:
    rental_properties = [item for item in properties if item.lead_id and item.unit_candidate_key]
    lease_dates = [item.lease_end for item in rental_properties if item.lease_end]
    best = max(
        properties,
        key=lambda item: (HEADLINE_PRIORITY.get(item.ownership_status, 1), item.confidence_score),
        default=None,
    )
    return profile.model_copy(
        update={
            "properties": properties,
            "property_count": len(properties),
            "current_property_count": sum(
                item.ownership_status in CURRENT_OWNER_STATUSES for item in properties
            ),
            "rental_linked_count": len(rental_properties),
            "contact_ready_count": sum(
                property_contact_ready(item, profile) for item in properties
            ),
            "annual_rent_aed": sum(item.annual_rent_aed or 0 for item in rental_properties),
            "next_lease_end": min(lease_dates) if lease_dates else None,
            "highest_ownership_status": best.ownership_status
            if best
            else "insufficient_property_data",
            "highest_confidence_score": best.confidence_score if best else 0,
        }
    )


def assessed_profiles(
    rows: list[dict[str, Any]],
    *,
    identity_rows: list[dict[str, Any]] | None = None,
    snapshot: OwnerAssessmentSnapshot | None = None,
    read_keys: dict[str, str] | None = None,
    signals: dict[str, dict[str, Any]] | None = None,
) -> list[CrmOwnerProfile]:
    from app.crm.owner_signals import build_owner_signals
    from app.crm.source_audit import source_audit_for_row

    if identity_rows is None:
        identity_rows = rows
    rows = [
        row
        for row in rows
        if not (audit := source_audit_for_row(row))
        or (
            (audit["transaction_match"].get("owner_category") in {"current", "former"})
            if audit.get("transaction_match")
            else audit["owner_candidate"]
        )
    ]
    if read_keys is None:
        read_keys = owner_read_keys(identity_rows if identity_rows is not None else rows)
    if signals is None:
        signals = build_owner_signals(identity_rows if identity_rows is not None else rows)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["canonical_owner_key"], []).append(row)
    profiles = []
    for canonical, events in grouped.items():
        by_property: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in events:
            if row["property_identity"] is not None:
                by_property.setdefault(tuple(row["property_identity"]), []).append(row)
        properties = []
        for property_events in by_property.values():
            best = max(property_events, key=assessed_row_preference)
            row = dict(best)
            if (
                row["assessed_status"] in CURRENT_OWNER_STATUSES
                and row.get("event_assessed_status", row["assessed_status"])
                not in CURRENT_OWNER_STATUSES
            ):
                # A file-scoped historical event cannot supply an actionable
                # lease contact solely by inheriting another event's current label.
                row["lead_id"] = None
            row.update(
                property_key_sql=row["property_key"],
                ownership_status=row["assessed_status"],
                confidence_score=row.get("assessed_confidence_score", row["confidence_score"]),
                match_reason=row["assessed_reason"],
                duplicate_count=len(property_events),
                source_lists=sorted(
                    {str(event.get("source_list_name") or "") for event in property_events} - {""}
                ),
                source_rows=sorted(
                    {
                        f"{event.get('source_sheet', '')}:{event.get('source_row_number', '')}"
                        for event in property_events
                    }
                ),
            )
            properties.append(sql_owner_property(row))
        properties.sort(
            key=lambda item: (
                -_OWNERSHIP_PRIORITY.get(item.ownership_status, 0),
                -item.confidence_score,
                item.property_key,
                item.area_name,
            )
        )
        best = max(events, key=lambda row: (row["confidence_score"], row["id"]))
        # a licensed broker's number or address is not the owner's: never a channel to reach them
        channels = [
            usable_channels(
                row.get("phone_primary"),
                row.get("phone_alternate"),
                row.get("email_primary"),
                row.get("broker_contact"),
            )
            for row in events
        ]
        phones = list(dict.fromkeys(phone for found, _ in channels for phone in found))
        emails = list(dict.fromkeys(email for _, found in channels for email in found))
        profile = CrmOwnerProfile(
            owner_key=read_keys[canonical],
            contact_name=best["contact_name"],
            phone_primary=phones[0] if phones else None,
            phone_alternate=phones[1] if len(phones) > 1 else None,
            phone_numbers=phones,
            email_primary=emails[0] if emails else None,
            highest_ownership_status="insufficient_property_data",
            highest_confidence_score=0,
            property_count=0,
            rental_linked_count=0,
            contact_ready_count=0,
            annual_rent_aed=0,
            history_summary=summarize_assessment_rows(snapshot, events) if snapshot else None,
            **signals.get(canonical, {}),
        )
        profiles.append(profile_with_properties(profile, properties))
    return profiles


def owner_registry_summary(
    profiles: list[CrmOwnerProfile],
) -> CrmOwnerRegistrySummary:
    return CrmOwnerRegistrySummary(
        rental_owner_profiles=sum(profile.contact_ready_count > 0 for profile in profiles),
        registry_owner_profiles=sum(
            not profile.properties
            or any(
                not property_contact_ready(item, profile)
                and item.ownership_status != "former_owner"
                for item in profile.properties
            )
            for profile in profiles
        ),
        prior_owner_profiles=sum(
            not profile.developer_side_seller
            and any(item.ownership_status == "former_owner" for item in profile.properties)
            for profile in profiles
        ),
        needs_review_profiles=sum(
            bool(profile.history_summary and profile.history_summary.invalid_identity_source_count)
            or any(item.ownership_status in REVIEW_OWNER_STATUSES for item in profile.properties)
            for profile in profiles
        ),
        multi_property_owners=sum(profile.property_count > 1 for profile in profiles),
    )


def sql_owner_property(row: dict[str, Any]) -> CrmOwnerProperty:
    from app.crm.source_audit import source_audit_for_row

    audit = source_audit_for_row(row)
    source_reference = None
    if audit:
        values = audit.get("source_values") or []

        def identifier(field, position):
            return str(
                audit.get(field) or (values[position] if len(values) > position else "") or ""
            )

        source_key = list(audit["source_key"])
        match = audit.get("transaction_match") or {}
        source_reference = CrmOwnerSourceReference(
            transaction_match_status=match.get("status"),
            ownership_evidence_basis=(
                "transaction_supported"
                if match.get("status") == "matched"
                and match.get("acquisition_sale_keys")
                and (row["ownership_status"] != "former_owner" or match.get("later_sale_date"))
                else "workbook_only"
            ),
            reference_id=audit["reference_id"],
            kind=source_key[0],
            source_key=source_key,
            building_number=identifier("building_number", 5),
            land_number=identifier("land_number", 11),
            dm_sub_number=identifier("dm_sub_number", 9),
            size_sqm=audit.get("size_sqm"),
            disposition=audit["disposition"],
        )
    return CrmOwnerProperty(
        source_reference=source_reference,
        property_key=str(row["property_key_sql"]),
        area_name=str(row["area_name"] or ""),
        project_name=str(row["project_name"] or ""),
        building_name=str(row["building_name"] or ""),
        unit_number=str(row["unit_number"] or ""),
        property_type=str(row["property_type"] or ""),
        ownership_status=str(row["ownership_status"]),  # type: ignore[arg-type]
        confidence_score=int(row["confidence_score"] or 0),
        match_reason=str(row["match_reason"] or ""),
        lead_id=str(row["lead_id"]) if row["lead_id"] else None,
        unit_candidate_key=(str(row["unit_candidate_key"]) if row["unit_candidate_key"] else None),
        imported_transaction_date=row["transaction_date"],
        imported_transaction_price_aed=(
            int(row["transaction_price_aed"]) if row["transaction_price_aed"] else None
        ),
        imported_property_type=str(row["property_type"] or ""),
        imported_party_role=str(row.get("party_role") or ""),
        latest_sale_date=row["latest_sale_date"],
        latest_sale_price_aed=(
            int(row["latest_sale_price_aed"]) if row["latest_sale_price_aed"] else None
        ),
        registry_sale_date=row["latest_sale_date"],
        registry_sale_price_aed=(
            int(row["latest_sale_price_aed"]) if row["latest_sale_price_aed"] else None
        ),
        later_sale_date=row["later_sale_date"],
        lease_end=row["lease_end"],
        annual_rent_aed=(int(row["annual_rent_aed"]) if row["annual_rent_aed"] else None),
        duplicate_count=int(row["duplicate_count"] or 1),
        source_lists=list(row["source_lists"] or []),
        source_rows=list(row["source_rows"] or []),
    )
