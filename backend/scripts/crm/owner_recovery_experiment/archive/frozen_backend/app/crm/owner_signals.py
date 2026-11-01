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


def build_owner_signals(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Count distinct identities/properties so repeated files cannot inflate signals."""
    names_by_phone: dict[str, set[str]] = defaultdict(set)
    owners: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["canonical_owner_key"]
        name = str(row.get("contact_name") or "")
        identity_name = _identity_text(name)
        owner = owners.setdefault(
            key, {"phones": set(), "properties": set(), "company": False, "source_reviews": set()}
        )
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
        result[key] = {"relationship_role": role, "role_signals": signals}
    return result
