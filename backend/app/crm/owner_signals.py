"""Observable contact patterns for review, never proof of profession or ownership."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.crm.brokers import BROKER_SIGNAL
from app.crm.identity import _identity_text, usable_channels

_ORGANIZATION_NAME = re.compile(
    r"\b(?:llc|l\.?l\.?c\.?|ltd|limited|pjsc|fze|fzco|company|corporation|"
    r"developments?|developers?|real\s+estate|propert(?:y|ies))\b",
    re.IGNORECASE,
)


# Off-plan procedures: the seller is the developer side (sale, completion, pre-registration).
_OFF_PLAN = re.compile(r"delayed|pre[\s-]*reg", re.IGNORECASE)
# A person's name that sold this many units, in this many buildings, mostly off-plan, signs for a
# developer: Danube's founders, or a signatory whose rows carry buyers' phone numbers.
DEVELOPER_SELLER_MIN_UNITS = 50
DEVELOPER_SELLER_MIN_BUILDINGS = 3
# A company is the developer on the same counts when its name says so or it sold this many units:
# Dubai Hills Estate registers plain sales. Banks and investors selling their own stay former owners.
DEVELOPER_COMPANY_MIN_UNITS = 500
_DEVELOPER_NAME = re.compile(r"\bdevelop", re.IGNORECASE)


def _developer_side_sellers(rows: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Names that sell units for a developer, with their unit and building counts.

    Counted by name across identities: such a name splits into one identity per phone number, or
    per property when the rows carry none."""
    units: dict[str, set] = defaultdict(set)
    buildings: dict[str, set[str]] = defaultdict(set)
    sales: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    labels: dict[str, str] = {}
    for row in rows:
        if str(row.get("party_role") or "").casefold() != "seller":
            continue
        name = _identity_text(str(row.get("contact_name") or ""))
        if not name:
            continue
        labels.setdefault(name, str(row.get("contact_name") or ""))
        if identity := row.get("property_identity"):
            units[name].add(tuple(identity))
        if building := _identity_text(str(row.get("building_name") or "")):
            buildings[name].add(building)
        sales[name][0] += 1
        sales[name][1] += bool(_OFF_PLAN.search(str(row.get("procedure_type") or "")))
    result = {}
    for name, (total, off_plan) in sales.items():
        sold, spread = len(units[name]), len(buildings[name])
        if sold < DEVELOPER_SELLER_MIN_UNITS or spread < DEVELOPER_SELLER_MIN_BUILDINGS:
            continue
        mostly_off_plan = off_plan * 2 >= total
        if _ORGANIZATION_NAME.search(labels[name]):
            developer = (
                mostly_off_plan
                or bool(_DEVELOPER_NAME.search(labels[name]))
                or sold >= DEVELOPER_COMPANY_MIN_UNITS
            )
        else:
            developer = mostly_off_plan
        if developer:
            result[name] = (sold, spread)
    return result


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
                "company": False,
                "source_reviews": set(),
                "names": set(),
                "broker_channel": False,
            },
        )
        if identity_name:
            owner["names"].add(identity_name)
        lifecycle = (
            row.get("source_lifecycle") or (row.get("evidence") or {}).get("source_lifecycle") or {}
        )
        owner["source_reviews"].update(lifecycle.get("reasons") or [])
        owner["company"] |= bool(_ORGANIZATION_NAME.search(name))
        # a licensed broker's number is the broker's, not this owner's: not one of their phones
        marked = row.get("broker_contact") or (row.get("evidence") or {}).get("broker_contact")
        phones, _ = usable_channels(
            row.get("phone_primary"), row.get("phone_alternate"), None, marked
        )
        for phone in phones:
            owner["phones"].add(phone)
            if identity_name:
                names_by_phone[phone].add(identity_name)
        if isinstance(marked, dict) and not marked.get("is_broker"):
            owner["broker_channel"] |= bool(marked.get("phones") or marked.get("emails"))

    result = {}
    for key, owner in owners.items():
        signals = sorted(owner["source_reviews"])
        role = "unknown"
        shared_names = max((len(names_by_phone[p]) for p in owner["phones"]), default=0)
        if shared_names > 1:
            signals.append(f"Phone shared by {shared_names} names.")
            if shared_names >= 5:
                role = "possible_intermediary"
        developer = next(
            (developer_sellers[n] for n in sorted(owner["names"]) if n in developer_sellers), None
        )
        if developer and owner["company"]:
            signals.append(f"Developer: sold {developer[0]} units across {developer[1]} buildings.")
        elif developer:
            role = "possible_intermediary"
            signals.append(
                f"Developer-side seller: sold {developer[0]} units across {developer[1]} "
                "buildings, mostly off-plan."
            )
        if owner["broker_channel"]:
            signals.append(BROKER_SIGNAL)
        if owner["company"]:
            role = "organization"
        result[key] = {
            "relationship_role": role,
            "role_signals": signals,
            "developer_side_seller": bool(developer),
        }
    return result
