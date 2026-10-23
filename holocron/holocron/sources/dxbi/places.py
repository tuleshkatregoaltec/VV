"""DXBI's places, as its location list names them, for labelling sales and leases.

DXBI prints each record's location as one place's path in its own location list
(``scripts/dxbi_location_sweep.py`` saves the list as ``locations.json``): "Mog 197, Mogul
Cluster, Discovery Gardens" is building Mog 197 (flag B) in project Mogul Cluster (P); "Damac
Riverlink, Dubai Investment Park Second" is the project itself (P), with no building. The record
parsers cannot tell a building from a project, or a single-name project from an area, from the
text alone (2026-10-08: 46% of sales showed a project as their building). Each place here carries
the keys a stored record has for that path, and the building, project and area DXBI's list gives
it, so the Transactions pages label records as DXBI does.
"""

from __future__ import annotations

import re
from typing import Any

from holocron.sources.dxbi.rental_events import canonical_area_name
from holocron.sources.dxbi.sales_units import location_key

# DXBI's flags: B building and T tower are buildings; P project; M master community, U sub-area,
# A DLD area and C the city are areas.
BUILDING_FLAGS = ("B", "T")
PROJECT_FLAG = "P"
AREA_FLAGS = ("M", "U", "A", "C")
# Where two places share a key, the narrower one wins.
_RANK = {"B": 0, "T": 0, "P": 1, "M": 2, "U": 3, "A": 4, "C": 5}
# A search-box hint on a project's name: "Valencia (all buildings), Damac Lagoons".
_SCOPE_HINT = re.compile(r"\s*\((?:all buildings|all phases)\)\s*$", re.IGNORECASE)

PLACE_COLUMNS = [
    "location_id", "flag", "path", "path_key", "building_key", "area_key", "match_rank",
    "building_label", "project_label", "area_label", "source_run_id",
]  # fmt: skip


def _parts(path: str) -> list[str]:
    return [part.strip() for part in path.split(",") if part.strip()]


def _printed_name(item: dict[str, Any]) -> str:
    """A place's name as DXBI prints it on records: the first part of its path."""
    parts = _parts(str(item.get("dv") or ""))
    return _SCOPE_HINT.sub("", parts[0]) if parts else ""


def _nearest(
    item: dict[str, Any], by_id: dict[Any, dict[str, Any]], flags: tuple[str, ...]
) -> dict[str, Any] | None:
    """The place itself or its nearest parent with one of ``flags``."""
    node: dict[str, Any] | None = item
    while node and node.get("flag") not in flags:
        node = by_id.get(node.get("parent_id"))
    return node


def place_rows(items: list[dict[str, Any]], run_id: str) -> list[list[object]]:
    """One row per place and per key a stored record of that place can carry.

    A sale stores its path's first part as the building and its last part as the area
    (``sales_units.normalize_sales_row``); a lease stores the whole path (``location_name``). A
    single-name place keys as a building with no area, and, for plots, as the name in both.
    """
    by_id = {item["id"]: item for item in items}
    rows: list[list[object]] = []
    for item in items:
        flag = str(item.get("flag") or "")
        path = str(item.get("dv") or "")
        parts = _parts(path)
        if not parts or flag not in _RANK:
            continue
        project = _nearest(item, by_id, (PROJECT_FLAG,))
        # The place itself when it is an area, else the community or area it sits in: some
        # single-name buildings and projects print no area ("Eden Hills").
        area = _nearest(item, by_id, AREA_FLAGS[:-1])
        labels = [
            _printed_name(item) if flag in BUILDING_FLAGS else "",
            _printed_name(project) if project else "",
            canonical_area_name(_printed_name(area)) if area else "",
        ]
        first = location_key(parts[0])
        keys = [(first, location_key(canonical_area_name(parts[-1])) if len(parts) > 1 else "")]
        if len(parts) == 1:
            keys.append((first, location_key(canonical_area_name(parts[0]))))
        for building_key, area_key in keys:
            rows.append(
                [
                    int(item["id"]),
                    flag,
                    path,
                    location_key(path),
                    building_key,
                    area_key,
                    _RANK[flag],
                    *labels,
                    run_id,
                ]
            )
    return rows
