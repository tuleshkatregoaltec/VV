"""Source procedure semantics, independent of whether a row is retained."""

from __future__ import annotations

import re

IMPORT_RESOLVER_VERSION = "owner-qualified-18"


def event_family(procedure: str) -> str:
    label = " ".join(re.sub(r"[-_]", " ", procedure.casefold()).split())
    # Composite procedures take precedence over incidental 'sell' words.
    if "mortgage" in label or "finance" in label:
        return "financing"
    if "lease to own" in label:
        return "lease_to_own"
    if re.search(r"\b(rent|rental|lease|leasing|tenancy|ejari)\b", label):
        return "rental"
    if "grant" in label or "gift" in label:
        return "gift"
    if "heir" in label or "inherit" in label:
        return "inheritance"
    if "ownership transfer" in label:
        return "ownership_transfer"
    if "annexation" in label or "cut off" in label:
        return "property_change"
    if re.search(r"\b(sale|sell)\b", label):
        return "sale"
    return "unknown" if label else "contact_snapshot"


def has_sale_evidence(candidate) -> bool:
    """Only explicit sales may use sale date/amount as acquisition evidence.

    Older imports did not store a family. Preserve their explicit Buyer/Seller
    blank-procedure interpretation; newly parsed rows always carry a family.
    """
    family = candidate.evidence.get("event_family")
    if family is None:
        family = event_family(candidate.procedure_type)
        if not candidate.procedure_type and candidate.party_role in {"Buyer", "Seller"}:
            family = "sale"
    return family == "sale" and candidate.party_role in {"Buyer", "Seller"}


def source_size_unit(field_map: dict[str, str]) -> str | None:
    """Read declared size units; an auto-mapped generic Size header has none."""
    unknown = False
    for field in ("size_sqft", "size_sqm", "size_unknown"):
        header = field_map.get(field)
        if not header:
            continue
        normalized = re.sub(r"[^a-z0-9]", "", str(header).lower().replace("²", "2"))
        if any(token in normalized for token in ("sqft", "squarefeet", "squarefoot", "ft2")):
            return "sqft"
        if any(token in normalized for token in ("sqm", "squaremeter", "squaremetre", "m2")):
            return "sqm"
        unknown = True
    return "unknown" if unknown else None
