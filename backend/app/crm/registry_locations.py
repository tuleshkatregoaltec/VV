"""Recover missing DXBI labels from its own catalog without changing unit identity."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Any

_FIELDS = ("building_name", "project_name", "area_name")
_LABELS = ("building_label", "project_label", "area_label")


@lru_cache(maxsize=100_000)
def _place_key(value: Any) -> str:
    # These are the provider catalog's path-key spelling/singular conventions.
    text = str(value or "").casefold().replace("jumeriah", "jumeirah")
    text = text.replace("residences", "residence").replace("apartments", "apartment")
    return re.sub(r"[^a-z0-9]", "", text)


def _file_key(value: Any) -> str:
    # One Za'abeel's own brand has this specific common exported spelling.
    # Tower qualifiers remain intact; this is not a phase/building alias.
    key = _place_key(value)
    return "onezaabeel" + key[len("onezabeel") :] if key.startswith("onezabeel") else key


@lru_cache(maxsize=100_000)
def _area_key(value: Any) -> str:
    """Provider area suffix equivalences; never used for buildings or unit IDs."""
    key = _place_key(value)
    roman = re.search(
        r"(?:\s|[-_])(VIII|VII|VI|IV|IX|III|II|V|X|I)$", str(value or ""), re.IGNORECASE
    )
    romans = {
        "i": "1",
        "ii": "2",
        "iii": "3",
        "iv": "4",
        "v": "5",
        "vi": "6",
        "vii": "7",
        "viii": "8",
        "ix": "9",
        "x": "10",
    }
    if roman:
        return key[: -len(roman.group(1))] + romans[roman.group(1).lower()]
    ordinals = {
        "first": "1",
        "second": "2",
        "third": "3",
        "fourth": "4",
        "fifth": "5",
        "sixth": "6",
        "seventh": "7",
        "eighth": "8",
        "ninth": "9",
        "tenth": "10",
    }
    for word, number in ordinals.items():
        if key.endswith(word):
            return key[: -len(word)] + number
    return key


class RegistryLocationIndex:
    """Index a complete DXBI place catalog once; tied conflicting labels stay blank."""

    def __init__(self, places: Iterable[Mapping[str, Any]]):
        places = list(places)
        self._exact_locations = {
            (
                _place_key(place.get("building_label")),
                _place_key(place.get("project_label")),
                _area_key(place.get("area_label")),
            )
            for place in places
        }
        self._paths: dict[str, dict[str, Any] | None] = {}
        self._sales: dict[tuple[str, str], dict[str, Any] | None] = {}
        self._file_names: dict[str, list[Mapping[str, Any]]] = {}
        self._file_projects: dict[str, list[Mapping[str, Any]]] = {}
        self._area_names: dict[str, list[Mapping[str, Any]]] = {}
        self._community_areas: dict[str, list[Mapping[str, Any]]] = {}
        self._qualified_projects: dict[str, list[Mapping[str, Any]]] = {}
        paths: dict[str, list[Mapping[str, Any]]] = {}
        sales: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for place in places:
            project = _file_key(place.get("project_label"))
            area = _area_key(place.get("area_label"))
            if project and area and project != area:
                areas = {area}
                romans = {
                    "1": "i",
                    "2": "ii",
                    "3": "iii",
                    "4": "iv",
                    "5": "v",
                    "6": "vi",
                    "7": "vii",
                    "8": "viii",
                    "9": "ix",
                }
                if area[-1:] in romans:
                    areas.add(area[:-1] + romans[area[-1]])
                for key in {a + project for a in areas} | {project + a for a in areas}:
                    self._qualified_projects.setdefault(key, []).append(place)
            for name in {
                _file_key(place.get(field))
                for field in ("building_label", "project_label", "building_key")
            } - {""}:
                if (
                    place.get("building_label") or place.get("project_label")
                ) and name != _file_key(place.get("area_label")):
                    self._area_names.setdefault(name, []).append(place)
            canonical = _area_key(place.get("area_label"))
            if (
                canonical
                and _area_key(place.get("building_key")) == canonical
                and int(place.get("match_rank") or 0) == 2
            ):
                self._community_areas.setdefault(canonical, []).append(place)
            name = _file_key(place.get("building_label"))
            project = _file_key(place.get("project_label"))
            if project and project != _file_key(place.get("area_label")):
                self._file_projects.setdefault(project, []).append(place)
            if name and name != _place_key(place.get("area_label")):
                self._file_names.setdefault(name, []).append(place)
            path = _place_key(place.get("path_key") or place.get("path"))
            building, area = (
                _place_key(place.get("building_key")),
                _place_key(place.get("area_key")),
            )
            if path:
                paths.setdefault(path, []).append(place)
            if building and area:
                sales.setdefault((building, area), []).append(place)
        self._paths = {key: self._unique_best(rows) for key, rows in paths.items()}
        self._sales = {key: self._unique_best(rows) for key, rows in sales.items()}

    @staticmethod
    def _unique_best(rows: list[Mapping[str, Any]]) -> dict[str, Any] | None:
        rank = min(int(row.get("match_rank") or 0) for row in rows)
        best = [row for row in rows if int(row.get("match_rank") or 0) == rank]
        labels = {tuple(str(row.get(field) or "") for field in _LABELS) for row in best}
        if len(labels) != 1:
            return None
        return dict(min(best, key=lambda row: int(row.get("location_id") or 0)))

    def _area_evidence(self, place: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        canonical = _area_key(place.get("area_label"))
        return [place, *self._community_areas.get(canonical, [])]

    def _place_accepts_area(self, place: Mapping[str, Any], area: Any) -> bool:
        key = _area_key(area)
        return bool(key) and any(
            key in {_area_key(item.get("area_key")), _area_key(item.get("area_label"))}
            for item in self._area_evidence(place)
        )

    def _align_area(self, event: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(event)
        if not row.get("area_name"):
            return row
        building = _file_key(row.get("building_name"))
        project = _file_key(row.get("project_name"))
        candidates = self._area_names.get(building, []) or self._area_names.get(project, [])
        if project and any(
            _file_key(place.get("project_label")) == project for place in candidates
        ):
            candidates = [
                place for place in candidates if _file_key(place.get("project_label")) == project
            ]
        exact_buildings = [
            place
            for place in candidates
            if building and _file_key(place.get("building_label")) == building
        ]
        project_only = [
            place
            for place in candidates
            if not place.get("building_label")
            and _file_key(place.get("project_label")) in {building, project}
        ]
        candidates = exact_buildings or project_only or candidates
        candidates = [
            place for place in candidates if self._place_accepts_area(place, row["area_name"])
        ]
        scopes = {
            (
                _file_key(
                    place.get("building_label")
                    or place.get("project_label")
                    or place.get("building_key")
                ),
                _file_key(place.get("project_label")),
                _area_key(place.get("area_label")),
            )
            for place in candidates
        }
        if len(scopes) != 1:
            return row
        place = min(
            candidates,
            key=lambda item: (int(item.get("match_rank") or 0), int(item.get("location_id") or 0)),
        )
        canonical = str(place.get("area_label") or "")
        if not canonical or row["area_name"] == canonical:
            return row
        resolution = dict(row.get("registry_location_resolution") or {})
        resolution.setdefault("raw_fields", {field: row.get(field) or "" for field in _FIELDS})
        resolution["area_alignment"] = {
            "method": "dxbi_place_scoped_area",
            "location_id": place.get("location_id"),
            "provider_place_evidence_ids": sorted(
                {
                    int(item["location_id"])
                    for item in self._area_evidence(place)
                    if item.get("location_id")
                }
            ),
            "source_area": row["area_name"],
            "canonical_area": canonical,
            "legal_area_key": place.get("area_key"),
        }
        row["area_name"] = canonical
        row["registry_location_resolution"] = resolution
        return row

    def _finish(self, event: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(event)
        raw_project = str(row.get("project_name") or "")
        candidates = self._qualified_projects.get(_file_key(raw_project), [])
        if row.get("area_name"):
            candidates = [
                place for place in candidates if self._place_accepts_area(place, row["area_name"])
            ]
        scopes = {
            (_file_key(place.get("project_label")), _area_key(place.get("area_label")))
            for place in candidates
        }
        if len(scopes) == 1:
            project_only = [place for place in candidates if not place.get("building_label")]
            place = min(
                project_only or candidates,
                key=lambda item: (
                    int(item.get("match_rank") or 0),
                    int(item.get("location_id") or 0),
                ),
            )
            resolution = dict(row.get("registry_location_resolution") or {})
            resolution.setdefault("raw_fields", {field: row.get(field) or "" for field in _FIELDS})
            resolution["project_alignment"] = {
                "method": "dxbi_place_area_project",
                "location_id": place.get("location_id"),
                "source_project": raw_project,
                "canonical_project": place["project_label"],
            }
            row["project_name"] = str(place["project_label"])
            if (
                row.get("raw_location_fields") is not None
                and not row["raw_location_fields"].get("building_name")
                and row.get("building_name") == raw_project
            ):
                row["building_name"] = ""
            row["registry_location_resolution"] = resolution
        row = self._align_area(row)
        if row.get("registry_location_resolution"):
            resolution = dict(row["registry_location_resolution"])
            resolution["resolved_fields"] = {field: row.get(field) or "" for field in _FIELDS}
            row["registry_location_resolution"] = resolution
        # Confirmation describes the resolved labels. Computing it before a
        # catalog fills a blank project made the first and second passes differ.
        row["registry_catalog_confirmed"] = (
            _place_key(row.get("building_name")),
            _place_key(row.get("project_name")),
            _area_key(row.get("area_name")),
        ) in self._exact_locations
        return row

    def normalize(self, event: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(event)
        if all(row.get(field) for field in _FIELDS):
            return self._finish(row)
        path = _place_key(row.get("location_name"))
        place = (
            self._paths.get(path)
            if path
            else self._sales.get(
                (_place_key(row.get("building_name")), _place_key(row.get("area_name")))
            )
        )
        if not place:
            return self._finish(row)
        recovered = {}
        raw = {field: row.get(field) or "" for field in _FIELDS}
        for field, label in zip(_FIELDS, _LABELS, strict=True):
            if not row.get(field) and place.get(label):
                row[field] = str(place[label])
                recovered[field] = row[field]
        if recovered:
            row["registry_location_resolution"] = {
                "method": "dxbi_place_path" if path else "dxbi_place_building_area",
                "location_id": place.get("location_id"),
                "raw_fields": raw,
                "recovered_fields": recovered,
            }
        return self._finish(row)


def normalize_registry_locations(
    event: Mapping[str, Any], places: RegistryLocationIndex | Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Fill blank labels and align provider-verified, named-place area equivalences.

    Pass an index for a batch. Full unit/plot codes and explicit row labels are
    never rewritten; no project-only label is promoted into a building label.
    """
    index = places if isinstance(places, RegistryLocationIndex) else RegistryLocationIndex(places)
    return index.normalize(event)


def infer_source_file_context(
    source: Mapping[str, Any],
    places: RegistryLocationIndex | Iterable[Mapping[str, Any]],
    filename: str | None = None,
) -> dict[str, Any]:
    """Confirm a filename as one exact DXBI building, never a guessed community.

    Callers may supply raw_location_fields to distinguish parser-generated names
    from explicit spreadsheet labels. An unconfirmed filename changes nothing.
    """
    from app.crm.import_normalization import normalize_location

    result = dict(source)
    raw = source.get("raw_location_fields", source)
    if raw.get("building_name") or raw.get("project_name"):
        return result
    filename = filename or str(source.get("source_filename") or "")
    stem = re.split(r"[/\\]", filename)[-1]
    stem = re.sub(r"\.(?:xlsx?|csv)$", "", stem, flags=re.IGNORECASE)
    # Full dates may be removed; isolated numbers remain because they can be
    # tower/phase identifiers. Document tags must be separate words.
    stem = re.sub(
        r"\b(?:20\d{2}[-_. ]\d{1,2}[-_. ]\d{1,2}|\d{1,2}[-_. ]\d{1,2}[-_. ]20\d{2})\b", " ", stem
    )
    stem = re.sub(r"[_()]", " ", stem)
    stem = re.sub(
        r"\b(?:owners?|contacts?|lists?|updated?|cleaned?|final|database|data|sheet|new|old)\b",
        " ",
        stem,
        flags=re.IGNORECASE,
    )
    months = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    stem = re.sub(r"(?i)(?:^|[\s_.-])" + months + r"[\s_.-]*20\d{2}(?=$|[\s_.-])", " ", stem)
    stem = re.sub(months + r"[\s_.-]*20\d{2}$", " ", stem, flags=re.IGNORECASE)
    key = _file_key(stem)
    index = places if isinstance(places, RegistryLocationIndex) else RegistryLocationIndex(places)
    building_context = bool(index._file_names.get(key))
    candidates = (
        index._file_names.get(key, []) if building_context else index._file_projects.get(key, [])
    )
    area = normalize_location(source.get("area_name"), area=True)
    if area:
        candidates = [place for place in candidates if index._place_accepts_area(place, area)]
    scope_fields = _LABELS if building_context else ("project_label", "area_label")
    scopes = {tuple(_file_key(place.get(field)) for field in scope_fields) for place in candidates}
    if len(scopes) != 1:
        return result
    place = min(
        candidates,
        key=lambda item: (int(item.get("match_rank") or 0), int(item.get("location_id") or 0)),
    )
    result["building_name"] = str(place.get("building_label") or "") if building_context else ""
    result["project_name"] = str(place.get("project_label") or result.get("project_name") or "")
    result["area_name"] = str(result.get("area_name") or place.get("area_label") or "")
    result["inferred_file_context"] = {
        "method": "filename_exact_dxbi_building"
        if building_context
        else "filename_exact_dxbi_project",
        "location_id": place.get("location_id"),
        "source_filename": filename,
        "raw_fields": {field: raw.get(field) or "" for field in _FIELDS},
        "resolved_fields": {field: result.get(field) or "" for field in _FIELDS},
    }
    return result
