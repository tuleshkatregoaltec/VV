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


class SignalContext:
    """Organization-wide counts a single owner's signals depend on, accumulated row by row.

    Which names sell under one developer, and how many names share one phone, can only be
    known from every row; the accumulator lets them be counted while rows stream past instead
    of holding the whole organization.
    """

    def __init__(self) -> None:
        self._units: dict[str, set] = defaultdict(set)
        self._buildings: dict[str, set[str]] = defaultdict(set)
        self._sales: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        self._labels: dict[str, str] = {}
        self._names_by_phone: dict[str, set[str]] = defaultdict(set)
        self._developer_sellers: dict[str, tuple[int, int]] | None = None

    def add(self, row: dict[str, Any]) -> None:
        name = _identity_text(str(row.get("contact_name") or ""))
        if name:
            marked = row.get("broker_contact") or (row.get("evidence") or {}).get("broker_contact")
            phones, _ = usable_channels(
                row.get("phone_primary"), row.get("phone_alternate"), None, marked
            )
            for phone in phones:
                self._names_by_phone[phone].add(name)
        if str(row.get("party_role") or "").casefold() != "seller" or not name:
            return
        self._labels.setdefault(name, str(row.get("contact_name") or ""))
        if identity := row.get("property_identity"):
            self._units[name].add(tuple(identity))
        if building := _identity_text(str(row.get("building_name") or "")):
            self._buildings[name].add(building)
        self._sales[name][0] += 1
        self._sales[name][1] += bool(_OFF_PLAN.search(str(row.get("procedure_type") or "")))

    @property
    def developer_sellers(self) -> dict[str, tuple[int, int]]:
        if self._developer_sellers is None:
            self._developer_sellers = self._count_developers()
        return self._developer_sellers

    def phone_name_count(self, phone: str) -> int:
        return len(self._names_by_phone.get(phone, ()))

    def _count_developers(self) -> dict[str, tuple[int, int]]:
        result = {}
        for name, (total, off_plan) in self._sales.items():
            sold, spread = len(self._units[name]), len(self._buildings[name])
            if sold < DEVELOPER_SELLER_MIN_UNITS or spread < DEVELOPER_SELLER_MIN_BUILDINGS:
                continue
            mostly_off_plan = off_plan * 2 >= total
            if _ORGANIZATION_NAME.search(self._labels[name]):
                developer = (
                    mostly_off_plan
                    or bool(_DEVELOPER_NAME.search(self._labels[name]))
                    or sold >= DEVELOPER_COMPANY_MIN_UNITS
                )
            else:
                developer = mostly_off_plan
            if developer:
                result[name] = (sold, spread)
        return result


def _developer_side_sellers(rows: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Names that sell units for a developer, with their unit and building counts.

    Counted by name across identities: such a name splits into one identity per phone number, or
    per property when the rows carry none."""
    context = SignalContext()
    for row in rows:
        context.add(row)
    return context.developer_sellers


def build_owner_signals(
    rows: list[dict[str, Any]], *, context: SignalContext | None = None
) -> dict[str, dict[str, Any]]:
    """Count distinct identities/properties so repeated files cannot inflate signals.

    ``context`` carries the organization-wide counts when ``rows`` are only some owners.
    """
    if context is None:
        context = SignalContext()
        for row in rows:
            context.add(row)
    owners: dict[str, dict[str, Any]] = {}
    developer_sellers = context.developer_sellers
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
        owner["phones"].update(phones)
        if isinstance(marked, dict) and not marked.get("is_broker"):
            owner["broker_channel"] |= bool(marked.get("phones") or marked.get("emails"))

    result = {}
    for key, owner in owners.items():
        signals = sorted(owner["source_reviews"])
        role = "unknown"
        shared_names = max((context.phone_name_count(p) for p in owner["phones"]), default=0)
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
