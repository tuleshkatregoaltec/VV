"""Recently sold owners → Lead Inbox.

An owner on the agency's file whose unit sold again (ownership.py marks the claim
`former_owner` and records `later_sale_date`) has just had a liquidity event and may buy
again. Each such owner becomes one Inbox item, newest sale first, carrying the sale details.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import inbound_repository, owner_queries
from app.crm.identity import _normalize_email, _normalize_phone
from app.crm.import_models import CrmPropertyContactClaim
from app.crm.inbound_models import (
    SOLD_OWNER_SOURCE,
    CrmInboundActivity,
    CrmInboundContact,
    CrmInboundEnquiry,
    InboundEnquiryResponse,
)
from app.crm.inbound_policy import _utcnow

# Sales data runs about a month behind, so a 30-day window would be nearly empty.
RECENTLY_SOLD_DAYS = 90
logger = logging.getLogger(__name__)

# Items are created by the sync, not by an agent.
SYNC_USER = "system"


@dataclass(frozen=True)
class SoldOwner:
    owner_key: str
    contact_name: str
    phone: str | None
    email: str | None
    last_sold_on: date
    sales: list[dict[str, Any]]
    notes: str


def _sale_line(sale: dict[str, Any]) -> str:
    """ "Sold … on … for AED … (bought … for AED …, +67%)." — the purchase when it is known."""
    place = " unit ".join(part for part in (sale["building"], sale["unit"]) if part)
    price = f" for AED {sale['price_aed']:,}" if sale["price_aed"] else ""
    bought = ""
    if sale.get("bought_on"):
        bought = f" (bought {date.fromisoformat(sale['bought_on']):%d %b %Y}"
        if sale.get("bought_price_aed"):
            bought += f" for AED {sale['bought_price_aed']:,}"
            if sale["price_aed"]:
                change = round(
                    (sale["price_aed"] - sale["bought_price_aed"]) / sale["bought_price_aed"] * 100
                )
                bought += f", {change:+d}%"
        bought += ")"
    return f"Sold {place or 'their unit'} on {date.fromisoformat(sale['sold_on']):%d %b %Y}{price}{bought}."


def _purchase(claim: CrmPropertyContactClaim) -> tuple[str | None, int | None]:
    """The owner's own purchase (date, price), when it came before the resale.

    A claim from the owner's seller row is dated by the sale itself, so it is not a purchase.
    """
    if (
        claim.transaction_date
        and claim.later_sale_date
        and claim.transaction_date < claim.later_sale_date
    ):
        return claim.transaction_date.isoformat(), claim.transaction_price_aed or None
    return None, None


def _rank(claim: CrmPropertyContactClaim) -> tuple:
    """Which claim speaks for a unit: latest sale, then best evidence, then a fixed tie-break.

    The same resale can arrive through several owner-file imports; the choice must not depend
    on the order the database returns rows, or every re-run would look like a change.
    """
    return (claim.later_sale_date or date.min, claim.confidence_score, claim.row_fingerprint)


def _unit_key(unit: str) -> str:
    return "".join(unit.lower().split())


def match_purchase_ltv(
    rows: list[dict[str, Any]], unit_key: str, bought_on: date, bought_price: int | None
) -> float | None:
    """The mortgage share (LTV %) DLD recorded on the owner's purchase, if it is on record.

    The purchase is the sale of the same unit within 2 days and 2% of what the owner paid.
    """
    for row in rows:
        if row["unit_key"] != unit_key or row.get("ltv_pct") is None:
            continue
        if abs((row["transaction_date"] - bought_on).days) > 2:
            continue
        paid = int(row.get("sale_amount_aed") or 0)
        if bought_price and abs(paid - bought_price) > 0.02 * bought_price:
            continue
        return float(row["ltv_pct"])
    return None


def _cash_in_hand(
    price: int | None, bought_price: int | None, ltv: float | None
) -> tuple[float | None, int | None]:
    """(LTV, sale price less the loan taken at purchase); unknown without a usable LTV.

    DLD records some LTVs above 100%, which cannot be a mortgage share, so those count as
    unknown. Repayments since the purchase are not known, so this is an estimate.
    """
    if ltv is None or not 0 < ltv <= 100 or not price or not bought_price:
        return None, None
    return ltv, price - round(bought_price * ltv / 100)


async def load_purchase_mortgages(
    claims: list[CrmPropertyContactClaim],
) -> dict[tuple[str, str], float]:
    """(property key, purchase date) → LTV % for the owners' purchases DLD recorded a loan on."""
    purchases = [(claim, _purchase(claim)) for claim in claims if claim.unit_number]
    purchases = [(claim, bought) for claim, bought in purchases if bought[0]]
    units = sorted({_unit_key(claim.unit_number) for claim, _ in purchases})
    if not units:
        return {}
    try:
        rows = await owner_queries.fetch_purchase_ltv({"unit_keys": units})
    except Exception:
        logger.warning(
            "Purchase mortgages unavailable; cash in hand shows as unknown", exc_info=True
        )
        return {}
    mortgages: dict[tuple[str, str], float] = {}
    for claim, (bought_on, bought_price) in purchases:
        ltv = match_purchase_ltv(
            rows, _unit_key(claim.unit_number), date.fromisoformat(bought_on), bought_price
        )
        if ltv is not None:
            mortgages[(claim.property_key, bought_on)] = ltv
    return mortgages


def summarize_sold_owners(
    claims: list[CrmPropertyContactClaim],
    mortgages: dict[tuple[str, str], float] | None = None,
) -> list[SoldOwner]:
    """One summary per owner: each resold unit once (its latest sale), newest sale first.

    `mortgages` ((property key, purchase date) → LTV %) gives each sale an estimated cash in hand.
    """
    latest: dict[str, dict[str, CrmPropertyContactClaim]] = {}
    for claim in claims:
        if claim.later_sale_date is None:
            continue
        units = latest.setdefault(claim.owner_key, {})
        seen = units.get(claim.property_key)
        if seen is None or _rank(claim) > _rank(seen):
            units[claim.property_key] = claim

    owners: list[SoldOwner] = []
    for owner_key, units in latest.items():
        # Newest sale first; units sold the same day keep a fixed order so re-runs match.
        ordered = sorted(units.values(), key=lambda c: c.property_key)
        ordered.sort(key=lambda c: c.later_sale_date or date.min, reverse=True)
        mortgages = mortgages or {}
        sales = []
        for claim in ordered:
            bought_on, bought_price = _purchase(claim)
            ltv, cash = _cash_in_hand(
                claim.latest_sale_price_aed,
                bought_price,
                mortgages.get((claim.property_key, bought_on)) if bought_on else None,
            )
            sales.append(
                {
                    "property_key": claim.property_key,
                    "building": claim.building_name or claim.project_name,
                    "unit": claim.unit_number,
                    "area": claim.area_name,
                    "property_type": claim.property_type,
                    "sold_on": (claim.later_sale_date or date.min).isoformat(),
                    "price_aed": claim.latest_sale_price_aed,
                    "bought_on": bought_on,
                    "bought_price_aed": bought_price,
                    "mortgage_ltv_pct": ltv,
                    "est_cash_in_hand_aed": cash,
                }
            )
        more = len(sales) - 1
        notes = _sale_line(sales[0]) + (f" (+{more} more recent sales)" if more else "")
        first = ordered[0]
        owners.append(
            SoldOwner(
                owner_key=owner_key,
                contact_name=next((c.contact_name for c in ordered if c.contact_name), owner_key),
                phone=next(
                    (
                        c.phone_primary or c.phone_alternate
                        for c in ordered
                        if c.phone_primary or c.phone_alternate
                    ),
                    None,
                ),
                email=next((c.email_primary for c in ordered if c.email_primary), None),
                last_sold_on=first.later_sale_date or date.min,
                sales=sales,
                notes=notes,
            )
        )
    owners.sort(key=lambda owner: owner.owner_key)
    owners.sort(key=lambda owner: owner.last_sold_on, reverse=True)
    return owners


def _sold_at(day: date) -> datetime:
    """The Inbox sorts by enquiry date: the sale date makes it newest sale first."""
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def refresh_sold_owner_item(enquiry: CrmInboundEnquiry, owner: SoldOwner, now: datetime) -> bool:
    """Bring an existing item's sales up to date; agents' changes are never touched.

    Only the sale list, the item's date and the sync's own note line change. Intent, status,
    assignment and an agent's notes stay as they are. Returns whether anything changed.
    """
    observed = dict(enquiry.observed_data or {})
    sold_at = _sold_at(owner.last_sold_on)
    if observed.get("recent_sales") == owner.sales and enquiry.enquiry_date == sold_at:
        return False
    if enquiry.raw_notes == observed.get("recently_sold_notes"):
        enquiry.raw_notes = owner.notes
    observed["recent_sales"] = owner.sales
    observed["recently_sold_notes"] = owner.notes
    enquiry.observed_data = observed
    enquiry.enquiry_date = sold_at
    enquiry.updated_at = now
    return True


async def sync_recently_sold_inbox(
    db: AsyncSession,
    *,
    organization_id: str,
    days: int = RECENTLY_SOLD_DAYS,
    today: date | None = None,
) -> dict[str, int]:
    """Put every owner whose unit sold in the last `days` into the Inbox, once per owner.

    New sellers become unqualified, unassigned items with no reply deadline (they did not
    enquire); sellers already there get their sale details refreshed. Nothing is deleted.
    """
    since = (today or date.today()) - timedelta(days=days)
    claims = await inbound_repository.list_recent_former_owner_claims(db, organization_id, since)
    existing = await inbound_repository.list_sold_owner_enquiries(db, organization_id)
    now = _utcnow()
    created = updated = 0
    claims = list(claims)
    mortgages = await load_purchase_mortgages(claims)
    for owner in summarize_sold_owners(claims, mortgages):
        enquiry = existing.get(owner.owner_key)
        if enquiry is not None:
            if refresh_sold_owner_item(enquiry, owner, now):
                inbound_repository.save(db, enquiry)
                updated += 1
            continue
        contact = CrmInboundContact(
            organization_id=organization_id,
            full_name=owner.contact_name,
            phone=_normalize_phone(owner.phone),
            email=_normalize_email(owner.email),
            created_at=now,
            updated_at=now,
        )
        inbound_repository.save(db, contact)
        await db.flush()
        enquiry = CrmInboundEnquiry(
            organization_id=organization_id,
            contact_id=contact.id or 0,
            created_by_user_id=SYNC_USER,
            assigned_user_id=None,
            record_kind="unqualified_contact",
            intent="unknown",
            status="new",
            source=SOLD_OWNER_SOURCE,
            source_lead_id=owner.owner_key,
            enquiry_date=_sold_at(owner.last_sold_on),
            raw_notes=owner.notes,
            criteria={},
            strict_fields=[],
            observed_data={"recent_sales": owner.sales, "recently_sold_notes": owner.notes},
            confirmed_data={},
            qualification={},
            extraction_confidence=1,
            created_at=now,
            updated_at=now,
        )
        inbound_repository.save(db, enquiry)
        await db.flush()
        inbound_repository.save(
            db,
            CrmInboundActivity(
                enquiry_id=enquiry.id or 0,
                organization_id=organization_id,
                user_id=SYNC_USER,
                activity_type="created",
                body="Added from the owner file: recent sale",
                metadata_json={"source": SOLD_OWNER_SOURCE, "owner_key": owner.owner_key},
                created_at=now,
            ),
        )
        created += 1
    if created or updated:
        await db.commit()
    return {"created": created, "updated": updated}


async def sync_after_ownership_change(db: AsyncSession, *, organization_id: str) -> None:
    """Refresh the Inbox after an import or re-match changed who is a former owner.

    The ownership change is already saved; a failed Inbox sync is logged and retried by the
    next import, re-match or `scripts/crm/sync_recently_sold_inbox.py`, never raised.
    """
    try:
        result = await sync_recently_sold_inbox(db, organization_id=organization_id)
        logger.info(
            "Recently sold Inbox sync", extra={"organization_id": organization_id, **result}
        )
    except Exception:
        logger.exception(
            "Recently sold Inbox sync failed", extra={"organization_id": organization_id}
        )


APPROVED_NOTE = "Approved as a possible buyer from a recent sale"


def approve_as_buyer(
    enquiry: CrmInboundEnquiry, *, user_id: str, now: datetime
) -> CrmInboundActivity:
    """Move a recently sold owner from the Inbox into Leads as a possible buyer.

    Their budget, area and property type are unknown until an agent has spoken to them, so the
    brief stays empty and matchmaking stays off. The sale notes stay with the lead, and the
    approving agent becomes its owner. Returns the history entry to save.
    """
    if enquiry.source != SOLD_OWNER_SOURCE or enquiry.intent != "unknown":
        raise HTTPException(
            status_code=409,
            detail="Only a recently sold owner waiting in the Inbox can be approved",
        )
    enquiry.intent = "buy"
    enquiry.record_kind = "opportunity"
    enquiry.assigned_user_id = user_id
    enquiry.updated_at = now
    return CrmInboundActivity(
        enquiry_id=enquiry.id or 0,
        organization_id=enquiry.organization_id,
        user_id=user_id,
        activity_type="status_changed",
        body=APPROVED_NOTE,
        metadata_json={"approved_from": SOLD_OWNER_SOURCE, "intent": "buy"},
        created_at=now,
    )


async def approve_recent_seller(
    db: AsyncSession, *, enquiry_id: int, organization_id: str, user_id: str
) -> InboundEnquiryResponse:
    from app.crm.inbound import _enquiry_response

    enquiry = await inbound_repository.get_crm_inbound_enquiry(db, enquiry_id)
    if not enquiry or enquiry.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Inbound enquiry not found")
    inbound_repository.save(db, approve_as_buyer(enquiry, user_id=user_id, now=_utcnow()))
    inbound_repository.save(db, enquiry)
    await db.commit()
    await db.refresh(enquiry)
    return await _enquiry_response(
        db, enquiry, include_registry_profiles=True, include_history=True
    )
