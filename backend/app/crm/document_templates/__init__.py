"""Fixed, versioned document templates and the information each one requires.

The `draft-1` templates and field rules are proposals; client-approved wording and fields
replace them (as `v1`) before rollout. A missing required value blocks generation; nothing is
invented or left as an empty clause.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Any

from app.crm.document_models import DocType, DocumentFields
from app.crm.models import CrmCompanyListingDetail

_LISTING = ("listing.title", "listing.area_name", "listing.price_aed")


@dataclass(frozen=True)
class TemplateSpec:
    version: str
    file: str
    title: str
    # Which saved groups go into the snapshot; nothing else reaches the PDF.
    groups: tuple[str, ...]
    required: tuple[str, ...]


TEMPLATES: dict[str, TemplateSpec] = {
    "noc": TemplateSpec(
        version="draft-1",
        file="noc.html",
        title="No Objection Certificate",
        groups=("owner",),
        required=(*_LISTING, "owner.full_name", "owner.title_deed_number", "owner.id_number"),
    ),
    "lease": TemplateSpec(
        version="draft-1",
        file="lease.html",
        title="Lease Agreement",
        groups=("owner", "lease"),
        required=(
            *_LISTING,
            "owner.full_name",
            "lease.tenant_name",
            "lease.tenant_phone",
            "lease.start_date",
            "lease.end_date",
            "lease.annual_rent_aed",
            "lease.cheques",
            "lease.security_deposit_aed",
        ),
    ),
    "a2a": TemplateSpec(
        version="draft-1",
        file="a2a.html",
        title="Agent to Agent Agreement",
        groups=("a2a",),
        required=(
            *_LISTING,
            "a2a.other_brokerage",
            "a2a.other_broker_name",
            "a2a.other_broker_brn",
            "a2a.commission_split_pct",
            "a2a.valid_until",
        ),
    ),
    "sell_switch": TemplateSpec(
        version="draft-1",
        file="sell_switch.html",
        title="Sell & Switch Study",
        groups=("sell_switch",),
        required=(
            *_LISTING,
            "listing.size_sqft",
            "sell_switch.sale_price_aed",
            "sell_switch.mortgage_payoff_aed",
            "sell_switch.annual_rent_aed",
            "sell_switch.selling_fee_pct",
            "sell_switch.holding_months",
            "sell_switch.keep_annual_change_pct",
            "sell_switch.target_project_name",
            "sell_switch.target_project_area",
            "sell_switch.target_unit_size_sqft",
            "sell_switch.target_price_per_sqft_aed",
            "sell_switch.pre_handover_payment_pct",
            "sell_switch.dld_fee_pct",
            "sell_switch.mortgage_pct",
            "sell_switch.mortgage_rate_pct",
            "sell_switch.mortgage_term_years",
            "sell_switch.bank_fee_pct",
            "sell_switch.valuation_fee_aed",
            "sell_switch.handover_date",
            "sell_switch.conservative_handover_psf_aed",
            "sell_switch.base_handover_psf_aed",
            "sell_switch.upside_handover_psf_aed",
            "sell_switch.target_annual_rent_psf_aed",
            "sell_switch.market_context",
            "sell_switch.evidence_sources",
        ),
    ),
}

_LISTING_FIELDS = (
    "reference",
    "listing_key",
    "title",
    "mode",
    "property_type",
    "bedrooms",
    "size_sqft",
    "price_aed",
    "area_name",
    "building_name",
    "unit_number",
    "agent_name",
    "agent_phone",
    "broker_name",
)


def build_snapshot(
    listing: CrmCompanyListingDetail, fields: DocumentFields, doc_type: DocType
) -> dict[str, Any]:
    """The exact, JSON-safe input one document is made from (only the groups it uses)."""
    saved = fields.model_dump(mode="json")
    snapshot: dict[str, Any] = {
        "listing": listing.model_dump(mode="json", include=set(_LISTING_FIELDS))
    }
    for group in TEMPLATES[doc_type].groups:
        snapshot[group] = saved[group]
    if doc_type == "sell_switch" and not missing_fields(doc_type, snapshot):
        snapshot["calculations"] = _sell_switch_calculations(
            listing, DocumentFields.model_validate(fields).sell_switch.model_dump(mode="json")
        )
    return snapshot


def _money(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _sell_switch_calculations(listing: CrmCompanyListingDetail, inputs: dict[str, Any]) -> dict[str, Any]:
    """Calculate only from required listing data and assumptions explicitly supplied by the agent."""

    def amount(name: str) -> Decimal:
        return Decimal(str(inputs[name]))

    size = Decimal(str(listing.size_sqft))
    sale_price = amount("sale_price_aed")
    sale_fee = sale_price * amount("selling_fee_pct") / 100
    net_sale_proceeds = sale_price - sale_fee - amount("mortgage_payoff_aed")
    holding_years = Decimal(inputs["holding_months"]) / 12
    keep_factor = Decimal(
        str(
            math.pow(
                1 + float(amount("keep_annual_change_pct") / 100), float(holding_years)
            )
        )
    )
    keep_value = _money(sale_price * keep_factor)
    keep_rent = _money(amount("annual_rent_aed") * holding_years)

    target_size = amount("target_unit_size_sqft")
    target_price = target_size * amount("target_price_per_sqft_aed")
    pre_handover_cash = target_price * amount("pre_handover_payment_pct") / 100
    dld_fee = target_price * amount("dld_fee_pct") / 100
    mortgage = target_price * amount("mortgage_pct") / 100
    bank_fee = mortgage * amount("bank_fee_pct") / 100
    cash_required = pre_handover_cash + dld_fee + bank_fee + amount("valuation_fee_aed")
    cash_surplus = net_sale_proceeds - cash_required
    base_equity = target_size * amount("base_handover_psf_aed") - mortgage

    monthly_rate = amount("mortgage_rate_pct") / 1200
    months = int(inputs["mortgage_term_years"]) * 12
    payment = mortgage / months if monthly_rate == 0 else mortgage * (
        monthly_rate * (1 + monthly_rate) ** months
        / ((1 + monthly_rate) ** months - 1)
    )
    balance = mortgage
    year_one_principal = Decimal(0)
    for _ in range(min(12, months)):
        principal = payment - balance * monthly_rate
        year_one_principal += principal
        balance -= principal

    target_annual_rent = target_size * amount("target_annual_rent_psf_aed")
    year_one_debt_service = payment * 12
    year_one_cash_after_debt = target_annual_rent - year_one_debt_service
    starting_equity = target_price - mortgage
    total_return_pct = (
        (year_one_cash_after_debt + year_one_principal) / starting_equity * 100
        if starting_equity > 0
        else None
    )

    scenarios = {}
    for name, field in (
        ("conservative", "conservative_handover_psf_aed"),
        ("base", "base_handover_psf_aed"),
        ("upside", "upside_handover_psf_aed"),
    ):
        equity = target_size * amount(field) - mortgage
        scenarios[name] = {
            "psf_aed": int(inputs[field]),
            "equity_aed": _money(equity),
            "change_aed": _money(equity - net_sale_proceeds),
            "change_pct": round(float((equity / net_sale_proceeds - 1) * 100), 1)
            if net_sale_proceeds > 0
            else None,
        }

    return {
        "sale_price_per_sqft_aed": _money(sale_price / size),
        "current_yield_pct": round(float(amount("annual_rent_aed") / sale_price * 100), 1),
        "sale_fee_aed": _money(sale_fee),
        "net_sale_proceeds_aed": _money(net_sale_proceeds),
        "target_price_aed": _money(target_price),
        "pre_handover_cash_aed": _money(pre_handover_cash),
        "dld_fee_aed": _money(dld_fee),
        "mortgage_aed": _money(mortgage),
        "bank_fee_aed": _money(bank_fee),
        "cash_required_aed": _money(cash_required),
        "cash_surplus_aed": _money(cash_surplus),
        "keep_value_aed": keep_value,
        "keep_rent_aed": keep_rent,
        "keep_total_aed": keep_value + keep_rent,
        "scenarios": scenarios,
        "target_annual_rent_aed": _money(target_annual_rent),
        "year_one_debt_service_aed": _money(year_one_debt_service),
        "year_one_cash_after_debt_aed": _money(year_one_cash_after_debt),
        "year_one_principal_aed": _money(year_one_principal),
        "year_one_total_return_pct": round(float(total_return_pct), 1)
        if total_return_pct is not None
        else None,
        "target_yield_pct": round(float(target_annual_rent / target_price * 100), 1),
    }


def _value(snapshot: dict[str, Any], path: str) -> Any:
    value: Any = snapshot
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def missing_fields(doc_type: DocType, snapshot: dict[str, Any]) -> list[str]:
    """Required values that are absent or blank, in the template's order."""
    missing = []
    for path in TEMPLATES[doc_type].required:
        value = _value(snapshot, path)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(path)
    if doc_type == "sell_switch" and (_value(snapshot, "listing.size_sqft") or 0) <= 0:
        if "listing.size_sqft" not in missing:
            missing.append("listing.size_sqft")
    return missing
