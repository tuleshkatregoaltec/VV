"""Observable contact patterns for review, never proof of profession or ownership."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.crm.identity import _identity_text, _normalize_phone

_ORGANIZATION_NAME = re.compile(
    r"\b(?:llc|l\.?l\.?c\.?|ltd|limited|pjsc|fze|fzco|company|corporation|"
    r"developments?|developers?|real\s+estate)\b",
    re.IGNORECASE,
)


# Off-plan procedures: the seller is the developer side (sale, completion, pre-registration).
_OFF_PLAN = re.compile(r"delayed|pre[\s-]*reg", re.IGNORECASE)
# A person's name that sold this many units, in this many buildings, mostly off-plan, signs for a
# developer: Danube's founders, or a signatory whose rows carry buyers' phone numbers.
DEVELOPER_SELLER_MIN_UNITS = 50
DEVELOPER_SELLER_MIN_BUILDINGS = 3


def _developer_side_sellers(rows: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Names that sell off-plan units for a developer, with their unit and building counts.

    Counted by name across identities: such a name splits into one identity per phone number."""
    units: dict[str, set] = defaultdict(set)
    buildings: dict[str, set[str]] = defaultdict(set)
    sales: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        if str(row.get("party_role") or "").casefold() != "seller":
            continue
        name = _identity_text(str(row.get("contact_name") or ""))
        if not name or _ORGANIZATION_NAME.search(str(row.get("contact_name") or "")):
            continue
        if identity := row.get("property_identity"):
            units[name].add(tuple(identity))
        if building := _identity_text(str(row.get("building_name") or "")):
            buildings[name].add(building)
        sales[name][0] += 1
        sales[name][1] += bool(_OFF_PLAN.search(str(row.get("procedure_type") or "")))
    return {
        name: (len(units[name]), len(buildings[name]))
        for name, (total, off_plan) in sales.items()
        if len(units[name]) >= DEVELOPER_SELLER_MIN_UNITS
        and len(buildings[name]) >= DEVELOPER_SELLER_MIN_BUILDINGS
        and off_plan * 2 >= total
    }


def build_owner_signals(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Count distinct identities/properties so repeated files cannot inflate signals."""
    names_by_phone: dict[str, set[str]] = defaultdict(set)
    owners: dict[str, dict[str, Any]] = {}
    developer_sellers = _developer_side_sellers(rows)
    for row in rows:
        key = row["canonical_owner_key"]
        name = str(row.get("contact_name") or "")
        identity_name = _identity_text(name)
        owner = owners.setdefault(
            key,
            {
                "phones": set(),
                "properties": set(),
                "company": False,
                "source_reviews": set(),
                "names": set(),
            },
        )
        if identity_name:
            owner["names"].add(identity_name)
        lifecycle = (
            row.get("source_lifecycle") or (row.get("evidence") or {}).get("source_lifecycle") or {}
        )
        owner["source_reviews"].update(lifecycle.get("reasons") or [])
        owner["company"] |= bool(_ORGANIZATION_NAME.search(name))
        identity = row.get("property_identity")
        if identity:
            owner["properties"].add(tuple(identity))
        for field in ("phone_primary", "phone_alternate"):
            if phone := _normalize_phone(row.get(field)):
                owner["phones"].add(phone)
                if identity_name:
                    names_by_phone[phone].add(identity_name)

    result = {}
    for key, owner in owners.items():
        signals = sorted(owner["source_reviews"])
        role = "unknown"
        shared_names = max((len(names_by_phone[p]) for p in owner["phones"]), default=0)
        if shared_names > 1:
            signals.append(
                f"A supplied phone is shared by {shared_names} distinct names. "
                "Confirm whose number it is before outreach."
            )
            if shared_names >= 5:
                role = "possible_intermediary"
        developer = next(
            (developer_sellers[n] for n in sorted(owner["names"]) if n in developer_sellers), None
        )
        if developer and not owner["company"]:
            role = "possible_intermediary"
            signals.append(
                f"Sold {developer[0]} units across {developer[1]} buildings, mostly off-plan "
                "(delayed sell, pre-registration): a developer-side seller, not a former owner."
            )
        if owner["company"]:
            role = "organization"
            signals.append(
                "The supplied name appears to describe an organization. "
                "Its developer, broker or ownership role has not been verified."
            )
        if len(owner["properties"]) >= 20:
            signals.append(
                f"Associated with {len(owner['properties'])} identifiable properties. "
                "This count alone does not establish current holdings or a brokerage role."
            )
        result[key] = {
            "relationship_role": role,
            "role_signals": signals,
            "developer_side_seller": bool(developer) and not owner["company"],
        }
    return result
