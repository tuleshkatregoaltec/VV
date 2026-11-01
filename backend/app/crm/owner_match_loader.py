"""Load only the DXBI / Transactions rows one import can touch, and match the import's rows.

The offline shadow run reads a 2.7M-event snapshot. A live import must not: it asks ClickHouse for
the places its rows name (``same_place`` with any of the import's source places), the DXBI sales and
rentals in those places, and the Transactions sales within 2 AED of any of the import's prices.
Rows outside those sets can never be a candidate for any row of the import, so the outcomes are
the same as over the full set; only the informational "other candidates" lists are shorter.
"""

from __future__ import annotations

import logging
import math
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any

from app.crm import owner_queries
from app.crm.owner_matcher import (
    AMOUNT_TOLERANCE,
    MatchResult,
    SalesIndex,
    match_row,
    promote_learned_aliases,
    source_place,
)
from app.crm.owner_places import CachedPlaceIndex, Place, load_place_aliases
from app.crm.registry_locations import RegistryLocationIndex

logger = logging.getLogger(__name__)

_AMOUNT_CHUNK = 20_000
_PRICELESS = ("transaction_price_aed",)
_RESOLVED = ("area_name", "project_name", "building_name")


@lru_cache(maxsize=1)
def _aliases() -> tuple[dict[str, str], dict[str, str]]:
    return load_place_aliases()


def _price(source: Mapping[str, Any]) -> Decimal | None:
    try:
        value = Decimal(str(source.get("transaction_price_aed") or "").replace(",", ""))
    except InvalidOperation:
        return None
    return value if value.is_finite() and value > 0 else None


def _place_signature(place: Place) -> tuple[Any, ...]:
    return (
        place.community,
        place.project,
        place.building,
        place.community_labels,
        place.names,
        place.buildings,
        place.markers,
        place.towers,
        place.marker_stems,
        place.numbered,
        place.families,
    )


def _intern(value: Any) -> Any:
    return sys.intern(value) if isinstance(value, str) else value


def _source_scope(
    places: CachedPlaceIndex, sources: Sequence[Mapping[str, Any]]
) -> tuple[list[Place], set[int]]:
    """The distinct places the import's priced rows name, and every whole-AED amount that could
    be within 2 AED of one of their prices."""
    found: dict[tuple[Any, ...], Place] = {}
    amounts: set[int] = set()
    seen: dict[tuple[str, ...], Place | None] = {}
    for source in sources:
        price = _price(source)
        if price is None:
            continue
        key = tuple(
            str(source.get(name) or "")
            for name in (
                "area_name",
                "master_project",
                "project_name",
                "building_name",
                "unit_number",
                "building_number",
                "property_number",
                "plot_number",
            )
        )
        if key not in seen:
            seen[key] = source_place(source, places)
        place = seen[key]
        if place is None:
            continue
        found.setdefault(_place_signature(place), place)
        low = math.floor(price - AMOUNT_TOLERANCE) - 1
        amounts.update(range(low, math.ceil(price + AMOUNT_TOLERANCE) + 2))
    return list(found.values()), amounts


def _kept_places(
    places: CachedPlaceIndex,
    sources: list[Place],
    rows: list[Mapping[str, Any]],
    catalog: RegistryLocationIndex | None,
) -> tuple[list[Mapping[str, Any]], dict[tuple[str, ...], tuple[str, str, str]]]:
    """The place rows whose (catalogue-resolved) place matches some source place, and the
    resolved labels of each."""
    by_label: dict[str, list[Place]] = defaultdict(list)
    unlabeled: list[Place] = []
    for place in sources:
        for label in place.community_labels:
            by_label[label].append(place)
        if not place.community_labels:
            unlabeled.append(place)
    kept, resolved = [], {}
    for row in rows:
        labels = {name: row[name] for name in _RESOLVED}
        if catalog is not None:
            labels = catalog.normalize({**labels, "location_name": row["location_name"]})
        triple = tuple(str(labels.get(name) or "") for name in _RESOLVED)
        event = places.event_place(dict(zip(_RESOLVED, triple, strict=True)))
        if event.community_labels:
            candidates = {id(p): p for label in event.community_labels for p in by_label[label]}
            candidates.update((id(p), p) for p in unlabeled)
            nearby = candidates.values()
        else:
            nearby = sources
        if any(places.same_place(place, event) for place in nearby):
            kept.append(row)
            resolved[_row_key(row)] = triple
    return kept, resolved


def _row_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        row["family"],
        row["area_name"],
        row["project_name"],
        row["building_name"],
        row["location_name"],
    )


async def load_sales_index(sources: Sequence[Mapping[str, Any]]) -> SalesIndex:
    """A ``SalesIndex`` holding what the matcher can need for these sheet rows."""
    hierarchy = await owner_queries.fetch_place_hierarchy()
    project_aliases, master_aliases = _aliases()
    places = CachedPlaceIndex(hierarchy, project_aliases, master_aliases)
    source_places, amounts = _source_scope(places, sources)
    if not source_places:
        return SalesIndex([], places, [])

    all_places = await owner_queries.fetch_matcher_places()
    catalog_rows = await owner_queries.fetch_registry_places()
    catalog = RegistryLocationIndex(catalog_rows) if catalog_rows else None
    kept, resolved = _kept_places(places, source_places, all_places, catalog)
    events: list[dict[str, Any]] = []
    for row in await owner_queries.fetch_matcher_events(kept):
        location = row.pop("location_name", "")
        row["area_name"], row["project_name"], row["building_name"] = (
            _intern(value)
            for value in resolved.get(
                (
                    row["family"],
                    row["area_name"],
                    row["project_name"],
                    row["building_name"],
                    location,
                ),
                (row["area_name"], row["project_name"], row["building_name"]),
            )
        )
        row["event_date"] = _intern(row["event_date"])
        events.append(row)

    registry: list[dict[str, Any]] = []
    ordered = sorted(amounts)
    for start in range(0, len(ordered), _AMOUNT_CHUNK):
        for row in await owner_queries.fetch_matcher_registry(
            ordered[start : start + _AMOUNT_CHUNK]
        ):
            registry.append({name: _intern(value) for name, value in row.items()})
    logger.info(
        "Owner matcher scope: %d source places, %d of %d event places, %d events, %d Transactions",
        len(source_places),
        len(kept),
        len(all_places),
        len(events),
        len(registry),
    )
    return SalesIndex(events, places, registry)


def match_sources(index: SalesIndex, sources: Sequence[Mapping[str, Any]]) -> list[MatchResult]:
    """Match every row (identical rows once), then learn the import's own unit numbering."""
    cache: dict[tuple[tuple[str, str], ...], MatchResult] = {}
    results = []
    for source in sources:
        key = tuple(sorted((str(k), str(v)) for k, v in source.items()))
        if key not in cache:
            cache[key] = match_row(source, index)
        results.append(cache[key])
    return promote_learned_aliases(list(zip(sources, results, strict=True)))
