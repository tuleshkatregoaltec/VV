"""From a matcher outcome to what an owner row shows: outcome, colour, ownership status.

The matcher knows the property and its sale; only the ownership layer knows who the party is and
what role the sheet gave them. This module is that layer (the live-switch contract in
``docs/superpowers/plans/2026-10-29-owner-import-matching.md``). ``decide`` is the pure table,
``apply_owner_match`` writes it onto a candidate, ``summarize_owner_matches`` counts an import.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.crm.brokers import BROKER_REASON
from app.crm.identity import ParsedContact
from app.crm.import_models import CrmOwnerMatchSales, CrmOwnerMatchSummary, CrmOwnerMatchUnits
from app.crm.owner_matcher import _FINANCING, MATCHER_VERSION, MatchResult, sheet_unit
from app.crm.owner_matching_policy import SQM_TO_SQFT

COLOURS = {
    "matched_sale": "green",
    "matched_sale_inferred_unit": "green",
    "matched_registry_sale": "green",
    "matched_registry_sale_no_unit": "green",
    "matched_sale_via_mortgage": "green",
    "matched_sale_review": "amber",
    "property_confirmed_no_sale": "blue",
    "rejected": "red",
    "no_evidence": "grey",
    "lender": "grey",
    "broker": "grey",
}
_TIERS = ("green", "amber", "blue", "red", "grey")  # best first; red and grey share a unit tier
# A legacy status that claims no sale; a grey row may keep these.
_KEEP_LEGACY = {
    "unmatched",
    "insufficient_property_data",
    "registry_not_observed",
    "unit_linked_unverified",
    "conflicting_claim",
}
_LENDER = re.compile(
    r"\b(?:BANK|FINANCE|FINANCIAL\s+SERVICES|ISLAMIC|MASHREQ|EMIRATES\s+NBD|ENBD|ADCB|FAB"
    r"|FIRST\s+ABU\s+DHABI|DIB|HSBC|AMLAK|TAMWEEL|RAKBANK|CBD|COMMERCIAL\s+BANK"
    r"|STANDARD\s+CHARTERED|CITI|BARCLAYS)\b",
    re.I,
)


# An ordinary sale confirmed by a sale this far from the sheet's own date needs a look: the sheet
# row and the sale are probably two different transfers of the unit.
DATE_REVIEW_DAYS = 90
# Off-plan and completion procedures register the buyer long after (or before) the sale.
_OFF_PLAN = re.compile(r"delayed|pre[\s-]*reg", re.I)
_ORDINARY_SALE = re.compile(r"\b(?:sale|sell)\b", re.I)  # not a Grant, a gift or a transfer


def date_differs(
    matcher_outcome: str,
    procedure_type: str,
    sheet_date: date | str | None,
    sale_date: str | None,
) -> bool:
    """A would-be green row of an ordinary sale whose sheet date is over 90 days from the sale's.

    Only Sale / Sell procedures count. Financing rows (the via-mortgage path), off-plan or
    completion procedures, grants and the like, and rows with a blank procedure or date are left
    as they are."""
    procedure = (procedure_type or "").strip()
    if COLOURS.get(matcher_outcome) != "green" or not procedure or not sheet_date or not sale_date:
        return False
    if not _ORDINARY_SALE.search(procedure):
        return False
    if _OFF_PLAN.search(procedure) or _FINANCING.search(procedure):
        return False
    try:
        sheet = sheet_date if isinstance(sheet_date, date) else date.fromisoformat(sheet_date[:10])
        gap = abs((sheet - date.fromisoformat(sale_date[:10])).days)
    except ValueError:
        return False
    return gap > DATE_REVIEW_DAYS


def looks_like_a_lender(name: str) -> bool:
    """A bank or finance company by its name (word-bounded, so "Fabian" is not "FAB"). Names that
    are also people's or developers' names ("Noor", "Al Hilal", "Ajman") count only with BANK."""
    return bool(_LENDER.search(name or ""))


@dataclass(frozen=True)
class Decision:
    outcome: str
    colour: str
    status: str
    confidence: int
    reason: str
    keep_legacy: bool = False  # a grey row that keeps the legacy status, confidence and reason


def decide(
    matcher_outcome: str,
    *,
    party_role: str,
    contact_name: str,
    procedure_type: str,
    later_sale_date: str | None,
    legacy_status: str,
    legacy_property_found: bool,
    is_broker: bool = False,
    sheet_date: date | str | None = None,
    sale_date: str | None = None,
) -> Decision:
    """The contract's status mapping for one row. ``is_broker``: the row's name and contact are one
    licensed broker's (``app.crm.brokers``); like a lender, that beats whatever the matcher said."""
    if is_broker:
        return Decision("broker", "grey", "unmatched", 10, BROKER_REASON)
    financing = bool(_FINANCING.search(procedure_type or ""))
    if financing and party_role == "Buyer" and looks_like_a_lender(contact_name):
        return Decision(
            "lender",
            "grey",
            "unmatched",
            10,
            "A bank or finance company on a financing row: the lender, not an owner.",
        )
    outcome, colour = matcher_outcome, COLOURS[matcher_outcome]
    if date_differs(matcher_outcome, procedure_type, sheet_date, sale_date):
        outcome, colour = "matched_sale_review", "amber"
    if colour == "green":
        return _green(outcome, party_role, later_sale_date)
    if colour == "amber":
        if party_role == "Seller":
            return Decision(
                outcome,
                colour,
                "unverified_former_owner",
                40,
                "A sale fits this price and size, but one detail of the sheet disagrees. "
                "The source lists this party as Seller.",
            )
        return Decision(
            outcome,
            colour,
            "probable_current_owner",
            65,
            "A sale fits this price and size, but one detail of the sheet disagrees "
            "(see the match reasons). Review before relying on it.",
        )
    if colour == "blue":
        return Decision(
            outcome,
            colour,
            "unit_linked_unverified",
            50,
            "The unit exists in DXBI, but no sale at this price was found "
            "(on a mortgage row the amount is a loan, not a price).",
        )
    if colour == "red":
        return Decision(
            outcome,
            colour,
            "conflicting_claim",
            40,
            "DXBI contradicts the sheet for this unit (see the match reasons).",
        )
    if legacy_status in _KEEP_LEGACY:
        return Decision(outcome, colour, legacy_status, 0, "", keep_legacy=True)
    # The legacy resolver linked a sale the property-first matcher cannot confirm.
    if legacy_property_found:
        return Decision(
            outcome,
            colour,
            "unit_linked_unverified",
            50,
            "The property is linked, but no sale at this price could be confirmed for it.",
        )
    return Decision(outcome, colour, "unmatched", 20, "No unambiguous property evidence was found.")


def _green(outcome: str, role: str, later: str | None) -> Decision:
    colour = "green"
    mortgage = outcome == "matched_sale_via_mortgage"
    owner_role = "Seller" if mortgage else "Buyer"
    if mortgage and role == "Buyer":
        return Decision(
            outcome,
            colour,
            "unit_linked_unverified",
            50,
            "A mortgage row: its Buyer is the lender, not the owner. The sale is confirmed "
            "for the unit, but this party is not shown as its owner.",
        )
    if role == owner_role:
        if later:
            return Decision(
                outcome,
                colour,
                "former_owner",
                95,
                f"The sale is confirmed, but a later sale was recorded on {_long(later)}; "
                "this party is not presented as the current owner.",
            )
        if outcome == "matched_registry_sale_no_unit":
            return Decision(
                outcome,
                colour,
                "probable_current_owner",
                75,
                "A sale at this price and size was found in Transactions. It carries no unit "
                "number, so later sales cannot be checked.",
            )
        return Decision(
            outcome,
            colour,
            "verified_current_owner",
            98,
            "The sale at this price is confirmed for the unit and no later sale is recorded. "
            "The owner's identity comes from the import.",
        )
    if role == "Seller":
        return Decision(
            outcome,
            colour,
            "former_owner",
            95,
            "The source lists this party as Seller of the confirmed sale.",
        )
    return Decision(
        outcome,
        colour,
        "probable_current_owner",
        75,
        "The sale at this price is confirmed, but the sheet gives this party no Buyer or "
        "Seller role.",
    )


def _long(day: str) -> str:
    return date.fromisoformat(day).strftime("%d %b %Y")


# --------------------------------------------------------------------------- evidence


def matched_sale_view(sale: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The matched sale as the API shows it, whether it is a DXBI event or a Transactions row."""
    if not sale:
        return None
    if "family" in sale:
        amount, sqft = sale.get("amount"), sale.get("size_sqft")
        view = {
            "unit": sale.get("unit_number") or "",
            "building": sale.get("building_name") or "",
            "project": sale.get("project_name") or "",
            "area": sale.get("area_name") or "",
            "date": str(sale.get("event_date") or "")[:10],
            "source": "DXBI",
        }
    else:
        amount = sale.get("actual_worth")
        area = sale.get("procedure_area")
        sqft = float(area) * float(SQM_TO_SQFT) if area else None
        view = {
            "unit": sale.get("unit_number") or "",
            "building": sale.get("building_name_en") or "",
            "project": sale.get("project_name_en") or "",
            "area": sale.get("area_name_en") or sale.get("master_project_en") or "",
            "date": str(sale.get("instance_date") or "")[:10],
            "source": f"Transactions {sale.get('match_status') or ''}".strip(),
        }
    return {
        **view,
        "amount_aed": int(round(float(amount))) if amount else None,
        "sqft": round(float(sqft), 1) if sqft else None,
    }


def _sale_key(sale: Mapping[str, Any] | None) -> str:
    if not sale:
        return ""
    return str(
        sale.get("event_key") or sale.get("dxbi_sale_key") or sale.get("transaction_id") or ""
    )


def owner_match_evidence(result: MatchResult, *, later_sale_date: str | None) -> dict[str, Any]:
    """What a candidate stores for the matcher's verdict (``evidence["owner_match"]``)."""
    return {
        "version": MATCHER_VERSION,
        "matcher_outcome": result.outcome,
        "outcome": result.outcome,
        "colour": COLOURS[result.outcome],
        "property_key": list(result.property_key) if result.property_key else None,
        "sale": matched_sale_view(result.sale),
        "sale_key": _sale_key(result.sale),
        "reasons": list(result.reasons),
        "warnings": list(result.warnings),
        "later_sale_date": later_sale_date,
    }


def apply_owner_match(candidate: ParsedContact) -> None:
    """Let a stored matcher verdict decide the candidate's status; legacy evidence stays.

    Runs after the legacy assessment, which supplies the status a grey row may keep. It starts
    from ``matcher_outcome`` every time, so applying it twice changes nothing. A verdict from
    another matcher version is ignored (the next replay re-matches)."""
    match = candidate.evidence.get("owner_match")
    if not isinstance(match, dict) or match.get("version") != MATCHER_VERSION:
        return
    sale_date = (match.get("sale") or {}).get("date")
    decision = decide(
        match["matcher_outcome"],
        party_role=candidate.party_role,
        contact_name=candidate.contact_name,
        procedure_type=candidate.procedure_type,
        later_sale_date=match.get("later_sale_date"),
        legacy_status=candidate.ownership_status,
        legacy_property_found=candidate.latest_sale_date is not None,
        is_broker=bool((candidate.evidence.get("broker_contact") or {}).get("is_broker")),
        sheet_date=candidate.transaction_date,
        sale_date=sale_date,
    )
    warnings = [w for w in match.get("warnings") or () if not str(w).startswith("date_differs")]
    if date_differs(
        match["matcher_outcome"], candidate.procedure_type, candidate.transaction_date, sale_date
    ):
        warnings.append(f"date_differs: sheet {candidate.transaction_date}, sale {sale_date}")
    match = candidate.evidence["owner_match"] = {
        **match,
        "outcome": decision.outcome,
        "colour": decision.colour,
        "warnings": warnings,
    }
    for name in ("matched_sale_date", "matched_sale_key", "sale_anchor_key"):
        candidate.evidence.pop(name, None)
    sale = match.get("sale")
    if sale and decision.colour in ("green", "amber"):
        candidate.evidence["matched_sale_date"] = sale["date"]
        if match.get("sale_key"):
            candidate.evidence["matched_sale_key"] = match["sale_key"]
        if candidate.latest_sale_date is None and sale["date"]:
            candidate.latest_sale_date = date.fromisoformat(sale["date"])
            candidate.latest_sale_price_aed = sale["amount_aed"]
        if match.get("later_sale_date") and decision.status == "former_owner":
            candidate.later_sale_date = date.fromisoformat(match["later_sale_date"])
    if decision.keep_legacy:
        return
    candidate.ownership_status = decision.status
    candidate.confidence_score = decision.confidence
    candidate.match_reason = decision.reason


# --------------------------------------------------------------------------- import summary

# Why an amber row needs review, by priority: the first cause that applies is the row's one
# reason, so the counts add up to the amber rows. Each key is a stable plain word for the UI.
REVIEW_REASONS = (
    "date_differs",  # an ordinary sale over 90 days from the sheet's date
    "unit_differs",  # a sale fits price and size, but under another unit number
    "two_units_named",  # the sheet names two units / villas; the sale is of one of them
    "share_differs",  # another share of the unit sold at this price
    "size_differs",  # the sheet's size fits only on another size basis (or not at all)
    "unit_unverified",  # the sale was found by elimination, so the unit itself is not verified
    "type_differs",  # the property type differs (a warning only; never reviews a row by itself)
    "other",
)


def review_reason(match: Mapping[str, Any]) -> str:
    """The one primary reason an amber row is in review (``REVIEW_REASONS`` order wins)."""
    reasons = [str(reason) for reason in match.get("reasons") or ()]
    warnings = [str(warning) for warning in match.get("warnings") or ()]
    both = [*reasons, *warnings]

    def starts(prefix: str, texts: list[str] = both) -> bool:
        return any(text.startswith(prefix) for text in texts)

    if starts("date_differs", warnings):
        return "date_differs"
    if starts("unit differs", reasons):
        return "unit_differs"
    if starts("sheet_names_two"):
        return "two_units_named"
    if starts("share_qualifier_differs", warnings):
        return "share_differs"
    if "size_basis_differs" in warnings:
        return "size_differs"
    if starts("elimination_unverified", reasons):
        return "unit_unverified"
    if starts("type_label_differs", warnings):
        return "type_differs"
    return "other"


def _sale_identity(match: Mapping[str, Any]) -> tuple[str, str] | None:
    """(where the sale came from, which sale) of a row's matched sale; None without a sale.

    ``registry``: a sale event of the property registry (DXBI). ``transactions``: a sale found only
    in the Transactions data. The sale key tells two rows of one sale apart from two sales."""
    sale = match.get("sale")
    if not isinstance(sale, Mapping):
        return None
    source = "registry" if str(sale.get("source") or "") == "DXBI" else "transactions"
    key = str(match.get("sale_key") or "") or "|".join(
        str(sale.get(name) or "") for name in ("building", "unit", "date", "amount_aed")
    )
    return source, key


def summarize_owner_matches(
    items: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> CrmOwnerMatchSummary | None:
    """Rows by outcome, and units by the best tier among their rows.

    ``items`` are (``owner_match`` evidence, ``matcher_source``) pairs, one per kept row. A unit
    is a distinct (building-or-project label, identifier keys) among rows that carry an
    identifier; None when no row has a verdict. ``review_reasons`` counts the amber rows by their
    primary reason; ``sales_matched`` counts the distinct sales that green rows are tied to, by
    where the sale came from."""
    rows: Counter[str] = Counter()
    review: Counter[str] = Counter()
    sales: set[tuple[str, str]] = set()
    best: dict[tuple[str, tuple[str, ...]], int] = {}
    without_unit = 0
    for match, source in items:
        rows[match["outcome"]] += 1
        if match["colour"] == "amber":
            review[review_reason(match)] += 1
        elif match["colour"] == "green" and (sale := _sale_identity(match)):
            sales.add(sale)
        label, keys = sheet_unit(source)
        if not keys:
            without_unit += 1
            continue
        tier = _TIERS.index(match["colour"])
        key = (label, keys)
        best[key] = min(best.get(key, tier), tier)
    if not rows:
        return None
    tiers = Counter(min(tier, 3) for tier in best.values())  # red (3) and grey (4) are one tier
    units = CrmOwnerMatchUnits(
        total=len(best),
        confirmed=tiers[0],
        review=tiers[1],
        property_only=tiers[2],
        not_matched=tiers[3],
    )
    by_source = Counter(source for source, _ in sales)
    return CrmOwnerMatchSummary(
        version=MATCHER_VERSION,
        rows=dict(rows),
        units=units,
        rows_without_unit=without_unit,
        review_reasons={reason: review[reason] for reason in REVIEW_REASONS if review[reason]},
        sales_matched=CrmOwnerMatchSales(
            transactions=by_source["transactions"],
            registry=by_source["registry"],
            total=len(sales),
        ),
    )
