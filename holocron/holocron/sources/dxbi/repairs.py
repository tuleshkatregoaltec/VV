"""Evidence-gated, read-only proposals for replaying DXBI property titles.

The caller retains source files and proposal output. This module never writes a
warehouse row and never associates transactions by property similarity.
"""

from typing import Any

from holocron.sources.dxbi.sales_units import normalize_sales_row


_FIELDS = ("building_name", "building_key", "project_name", "area_name", "area_key")


def propose_name_repair(payload: dict[str, Any], stored: list[dict[str, Any]]) -> dict[str, Any]:
    url = str(payload.get("detail_url") or "")
    if not url or not payload.get("location_title"):
        return {"status": "unresolved", "reason": "missing_identity_or_property_title"}
    matches = [row for row in stored if row.get("detail_url") == url]
    # Multiple warehouse versions of one identity require review, not arbitrary selection.
    if len(matches) != 1:
        return {"status": "unresolved", "reason": "non_unique_identity", "candidates": len(matches)}
    old = matches[0]
    new = normalize_sales_row(payload)
    if not new:
        return {"status": "unresolved", "reason": "incomplete_source_record"}
    for field in ("transaction_date", "sale_amount_aed", "size_sqft", "unit_number"):
        before, after = old.get(field), new.get(field)
        equal = (
            float(before or 0) == float(after or 0)
            if field in {"sale_amount_aed", "size_sqft"}
            else str(before or "") == str(after or "")
        )
        if not equal:
            return {
                "status": "unresolved",
                "reason": f"conflicting_{field}",
                "sale_key": old["sale_key"],
            }
    if any(old.get(field) and not new[field] for field in _FIELDS):
        return {
            "status": "unresolved",
            "reason": "incomplete_property_hierarchy",
            "sale_key": old["sale_key"],
        }
    changes = {
        field: {"before": old.get(field, ""), "after": new[field]}
        for field in _FIELDS
        if old.get(field, "") != new[field]
    }
    return {
        "status": "proposed" if changes else "unchanged",
        "sale_key": old["sale_key"],
        "detail_url": url,
        "source_loaded_at": str(old.get("loaded_at", "")),
        "changes": changes,
    }
