"""Exact, community-qualified villa aliases shared by matching and history reads."""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.crm.identifier_keys import _kind, generic_building, identifier
from app.crm.registry_locations import _area_key
from app.market.reference import property_name_lookup_key


def parse_r3(value: Any) -> tuple[str, str] | None:
    match = re.fullmatch(r"r3([a-z][a-z0-9_-]*?)-v-([0-9]+)", identifier(str(value or "")))
    return (property_name_lookup_key(match[1]), str(int(match[2]))) if match else None


def registry_namespace(row: Mapping[str, Any]) -> tuple[str, str, str] | None:
    if _kind(row.get("property_type")) != "villa":
        return None
    master = "arabianranches3"
    if not any(_area_key(row.get(key)) == master for key in ("area_name", "project_name")):
        return None
    names = {
        property_name_lookup_key(str(row.get(key) or ""))
        for key in ("building_name", "project_name")
        if _area_key(row.get(key)) != master
    } - {"", master}
    if len(names) != 1:
        return None
    community = next(iter(names))
    if community.isdigit() or generic_building(community):
        return None
    unit = identifier(str(row.get("unit_number") or ""))
    if unit.isdigit():
        return master, community, str(int(unit))
    full = parse_r3(unit)
    return (master, *full) if full and full[0] == community else None


def source_namespace(
    source: Mapping[str, Any], target: Mapping[str, Any]
) -> tuple[str, str, str] | None:
    raw = source.get("original_identifiers") or source
    full = parse_r3(raw.get("building_number"))
    if not full or _kind(source.get("property_type")) not in {"villa", "plot", ""}:
        return None
    community, number = full
    for row in (source, {**source.get("raw_location_fields", {}), **raw}):
        names = set()
        for field in ("building_name", "project_name"):
            value = row.get(field)
            embedded = parse_r3(value)
            text = identifier(str(value or ""))
            if field == "building_name" and text.isdigit():
                if text != number:
                    return None
                continue
            qualified = (
                re.fullmatch(
                    r"arabian\s+ranches\s+(?:iii|3)\s*[-:]\s*(.+)", str(value or "").strip(), re.I
                )
                if field == "project_name"
                else None
            )
            if qualified:
                names.add(property_name_lookup_key(qualified[1]))
            elif embedded:
                if embedded != full:
                    return None
                names.add(embedded[0])
            elif text and _area_key(value) != "arabianranches3":
                names.add(property_name_lookup_key(str(value)))
        if names and names != {community}:
            return None
    if not any(
        property_name_lookup_key(str(source.get(key) or "")) == community
        for key in ("building_name", "project_name")
    ):
        return None
    area = _area_key(source.get("area_name"))
    if area and area != "arabianranches3":
        return None
    unit = identifier(str(raw.get("unit_number") or ""))
    if unit and unit != number and parse_r3(unit) != full:
        return None
    namespace = registry_namespace(target)
    return namespace if namespace == ("arabianranches3", community, number) else None


def history_unit_aliases(row: Mapping[str, Any]) -> set[str]:
    from app.market.reference import unit_lookup_key

    values = {unit_lookup_key(str(row.get("unit_number") or ""))} - {""}
    if namespace := registry_namespace(row):
        _, community, number = namespace
        values.update({unit_lookup_key(number), unit_lookup_key(f"R3 {community}-V-{number}")})
    return values
