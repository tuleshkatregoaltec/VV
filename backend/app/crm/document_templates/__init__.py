"""Fixed, versioned document templates and the information each one requires.

The `draft-1` templates and field rules are proposals; client-approved wording and fields
replace them (as `v1`) before rollout. A missing required value blocks generation; nothing is
invented or left as an empty clause.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    return snapshot


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
    return missing
