"""Licensed real-estate brokers are not owners.

The regulator's broker list (``crm_licensed_brokers``, loaded by ``scripts/crm/load_licensed_brokers``)
tells an owner sheet's agents from its owners. Two rules, both needing the row's own contact:

* a row whose name AND phone or email belong to the SAME broker is that broker, not an owner
  (``is_broker``: the decision table gives it the outcome ``broker``, like a bank's ``lender``);
* a phone or email of any broker on a row under a different name stays the owner's row, but that
  channel is the broker's, not the owner's: it never makes the row contact-ready, and the owner's
  profile says so.

A name alone is no evidence (brokers own property too); an expired card still counts (a former
broker's number is still an agent's). The verdict is stored per claim as ``evidence["broker_contact"]``
so later replays, the owner registry and the backfill need no broker table.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.identity import ParsedContact, _identity_text, _normalize_email, _normalize_phone
from app.crm.models import CrmLicensedBroker

BROKER_SIGNAL = "Phone belongs to a licensed broker."
BROKER_REASON = "Licensed broker, not an owner."


@dataclass
class BrokerIndex:
    """name key / normalized phone / casefolded email -> the broker numbers that carry it."""

    names: dict[str, set[int]] = field(default_factory=dict)
    phones: dict[str, set[int]] = field(default_factory=dict)
    emails: dict[str, set[int]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.names or self.phones or self.emails)

    def add(self, number: int, name_key: str, phones: Iterable[str], emails: Iterable[str]) -> None:
        if name_key:
            self.names.setdefault(name_key, set()).add(number)
        for phone in phones:
            self.phones.setdefault(phone, set()).add(number)
        for email in emails:
            self.emails.setdefault(email, set()).add(number)


def broker_phone(value: Any) -> str | None:
    """A broker-list phone ("0509166543", "971|50-4264267", "971567995941") as a sheet phone."""
    return _normalize_phone(str(value or "").replace("|", "").replace("-", ""))


def broker_email(value: Any) -> str | None:
    return _normalize_email(value)


def broker_row(record: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any] | None:
    """The table row of one broker-list record (None without a broker number)."""
    try:
        number = int(str(record.get("broker_number") or "").strip())
    except ValueError:
        return None
    phones = list(
        dict.fromkeys(p for key in ("phone", "mobile") if (p := broker_phone(record.get(key))))
    )
    email = broker_email(record.get("email"))
    expiry = str(record.get("card_expiry_date") or "")[:10]
    return {
        "broker_number": number,
        "name_key": _identity_text(str(record.get("name_en") or "")),
        "phones": phones,
        "emails": [email] if email else [],
        "card_expiry_date": date.fromisoformat(expiry) if len(expiry) == 10 else None,
        "updated_at": now or datetime.now(timezone.utc),
    }


async def load_broker_index(db: AsyncSession) -> BrokerIndex:
    """The whole broker table as an index; empty (no rules apply) while the table is empty."""
    index = BrokerIndex()
    result = await db.exec(
        select(
            CrmLicensedBroker.broker_number,
            CrmLicensedBroker.name_key,
            CrmLicensedBroker.phones,
            CrmLicensedBroker.emails,
        )
    )
    for number, name_key, phones, emails in result:
        index.add(number, name_key, phones or (), emails or ())
    return index


def broker_contact_evidence(
    contact_name: str,
    phone_primary: Any,
    phone_alternate: Any,
    email_primary: Any,
    index: BrokerIndex,
) -> dict[str, Any] | None:
    """``evidence["broker_contact"]`` for a row, or None when none of its contact is a broker's.

    ``phones`` / ``emails`` are the row's own normalized channels that a licensed broker carries;
    ``is_broker`` says the name belongs to one of those same brokers; ``usable_contact`` is
    whether any other channel is left to reach the owner."""
    phones = list(
        dict.fromkeys(p for v in (phone_primary, phone_alternate) if (p := _normalize_phone(v)))
    )
    email = _normalize_email(email_primary)
    broker_phones = [p for p in phones if p in index.phones]
    broker_emails = [email] if email and email in index.emails else []
    if not broker_phones and not broker_emails:
        return None
    same = index.names.get(_identity_text(contact_name or ""), set())
    carriers: set[int] = set()
    for phone in broker_phones:
        carriers |= index.phones[phone]
    for address in broker_emails:
        carriers |= index.emails[address]
    return {
        "is_broker": bool(same & carriers),
        "phones": broker_phones,
        "emails": broker_emails,
        "usable_contact": len(broker_phones) < len(phones) or (bool(email) and not broker_emails),
    }


def annotate_broker_contacts(candidates: Iterable[ParsedContact], index: BrokerIndex) -> int:
    """Store (or clear) ``evidence["broker_contact"]`` on every candidate; returns broker rows."""
    brokers = 0
    for candidate in candidates:
        found = broker_contact_evidence(
            candidate.contact_name,
            candidate.phone_primary,
            candidate.phone_alternate,
            candidate.email_primary,
            index,
        )
        if found is None:
            candidate.evidence.pop("broker_contact", None)
            continue
        candidate.evidence["broker_contact"] = found
        brokers += found["is_broker"]
    return brokers
