"""One place key space for sheet location labels and DXBI / Transactions events.

Pure rules, no I/O except reading the two curated alias CSVs that the Analytics hierarchy build
also uses (``holocron/holocron/market/data``). The backend does not import holocron, so they are
read by path. Keys are lowercase letters and digits with generic words removed; numbers are never
stripped, because "Damac Hills 2" and "Damac Hills" are different communities.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ALIAS_DIR = Path(__file__).resolve().parents[3] / "holocron" / "holocron" / "market" / "data"

_BLANK = {"", "0", "0.0", "null", "none", "n/a", "na", "-", "unknown", "#ref!", "#n/a", "#value!"}
_GENERIC = {"tower", "building", "bldg", "block", "residence", "residences", "phase", "the"}
_ROMAN = {"lll": "3", "iii": "3", "ii": "2"}
# Names that say nothing about where a property is.
_BROAD = {
    "dubai",
    "residential",
    "unit",
    "plot",
    "land",
    "commercial",
    "hotel",
    "rooms",
    "hotelrooms",
    "sold",
    "project",
}
_MIN_PARTIAL = 5
# "Springs - 2": a sub-community numbered inside one naming system (DLD's master project label).
_NUMBERED = re.compile(r"(.*\S)\s+-\s+([0-9]+)")
# "Springs 12": a numbered family of projects ("Emirates Living - Springs 12").
_FAMILY = re.compile(r"(.*\D)\s*[0-9]+")
# A stem this short is an abbreviation ("CW"), not a name that can contradict another.
_MIN_STEM = 4
_GENERIC_BUILDING = re.compile(r"[a-z]?[0-9]{0,3}[a-z]?")
_MARKER = re.compile(r"\b(?:building|bldg|tower|block)\s*(?:no\.?)?\s*([0-9]+[a-z]?)\b", re.I)
# "verve city walk tower b" -> stem "vervecitywalk", marker "b". Letters need the stem: "Tower B"
# alone exists in every community, so a letter marker only agrees when the stems do.
_TOWER = re.compile(r"(.*?)(?:building|bldg|tower|block)(?:no)?([0-9]+[a-z]?|[a-z])")
_GENERIC_PARTS = re.compile(r"building|bldg|tower|block|residences|residence|phase|the")
_ABBREVIATION = re.compile(r"\s*\([^)]*\)\s*$")
_LISTED = re.compile(r"\s*((?:no\.?\s*[0-9]+[a-z]?\s*,?\s*)+)(.+)", re.I)
_LISTED_CODE = re.compile(r"no\.?\s*([0-9]+[a-z]?)", re.I)


def _split_dash(text: str) -> list[str]:
    """Split ``A - B`` and ``A, B`` into their parts, but never inside brackets.

    "Emirates Garden 2 (Maple - Magnolia - Mulberry)" is one JVC project; its fragment
    "Mulberry" is also a Damac Hills 2 phase alias and must not be read as a place of its own.
    """
    parts, depth, start = [], 0, 0
    for found in re.finditer(r"[()]|\s+-\s+|\s*,\s*", text):
        if found[0] == "(":
            depth += 1
        elif found[0] == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            parts.append(text[start : found.start()])
            start = found.end()
    parts.append(text[start:])
    return parts


def _drop_initialism(text: str) -> str:
    """ "Jumeirah Village Triangle JVT" -> "Jumeirah Village Triangle" (``clean_label`` has already
    turned the bracketed "(JVT)" into a word)."""
    *words, last = text.split() or [""]
    initials = "".join(word[0] for word in words).upper()
    return " ".join(words) if len(words) > 1 and last.isalpha() and last == initials else text


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip().casefold() in _BLANK


def clean_label(value: Any) -> str:
    """The label as written, minus spreadsheet noise: no ``@suffix``, ``( E )`` becomes ``E``."""
    if _is_blank(value):
        return ""
    text = str(value).split("@")[0]
    text = re.sub(r"\(\s*([A-Za-z0-9]+)\s*\)", r" \1 ", text)
    text = " ".join(text.split())
    return "" if _is_blank(text) else text


def place_key(value: str) -> str:
    words = [_ROMAN.get(word, word) for word in re.findall(r"[a-z0-9]+", str(value).lower())]
    return "".join(word for word in words if word not in _GENERIC)


def _plain_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _close(a: str, b: str) -> bool:
    """Equal, or one contains the other (at least 5 characters, and the rest is not just digits)."""
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    if len(short) < _MIN_PARTIAL or short not in long:
        return False
    return not long.replace(short, "", 1).isdigit()


def _overlap(a: Iterable[str], b: Iterable[str]) -> bool:
    b = list(b)
    return any(_close(x, y) for x in a for y in b)


def load_place_aliases(directory: Path = ALIAS_DIR) -> tuple[dict[str, str], dict[str, str]]:
    """``(project_aliases, master_aliases)``: alias key -> canonical label, from the hierarchy CSVs."""

    def read(name: str, column: str) -> dict[str, str]:
        with (directory / name).open(newline="", encoding="utf-8") as handle:
            rows = csv.DictReader(handle)
            return {place_key(row["alias"]): row[column] for row in rows if place_key(row["alias"])}

    return read("project_aliases.csv", "project"), read("master_aliases.csv", "master")


@dataclass(frozen=True)
class Place:
    """Keys are ``place_key``s; ``""`` means unknown. The rest is what ``same_place`` compares."""

    community: str
    project: str
    building: str
    community_labels: frozenset[str] = field(default=frozenset(), compare=False, repr=False)
    names: frozenset[str] = field(default=frozenset(), compare=False, repr=False)
    buildings: tuple[str, ...] = field(default=(), compare=False, repr=False)
    markers: frozenset[str] = field(default=frozenset(), compare=False, repr=False)
    towers: frozenset[tuple[str, str]] = field(default=frozenset(), compare=False, repr=False)
    # (marker, stem): "Glamz Residence Tower 2" is ("bldg2", "glamz"); the stem is the name part.
    marker_stems: frozenset[tuple[str, str]] = field(default=frozenset(), compare=False, repr=False)
    # (head key, number) of "Springs - 2" labels: numbers in one naming system must agree.
    numbered: frozenset[tuple[str, str]] = field(default=frozenset(), compare=False, repr=False)
    # Registry (DLD) rows only: the numbered families their project / building belong to.
    families: frozenset[str] = field(default=frozenset(), compare=False, repr=False)


def _squash(key: str) -> str:
    """A compact key with the generic words cut out, so 'vervetowerb' and 'verveb' are one."""
    return _GENERIC_PARTS.sub("", key)


def _tower(text: str) -> tuple[str, str] | None:
    """``(stem, letter)`` of a letter tower such as "Verve Tower B"; digit towers use markers."""
    found = _TOWER.fullmatch(_plain_key(text))
    return (found[1], found[2]) if found and found[2].isalpha() else None


def _first(fields: Mapping[str, Any], *names: str) -> str:
    for name in names:
        if not _is_blank(fields.get(name)):
            return clean_label(fields[name])
    return ""


class PlaceIndex:
    def __init__(
        self,
        buildings: Iterable[Mapping[str, Any]],
        project_aliases: Mapping[str, str],
        master_aliases: Mapping[str, str],
    ):
        rows = list(buildings)
        self._project_aliases = dict(project_aliases)
        self._master_aliases = dict(master_aliases)
        self._communities = {_plain_key(row.get("community_key")) for row in rows} | {
            _plain_key(label) for label in self._master_aliases.values()
        }
        self._communities.discard("")
        self._known_cache: dict[str, bool] = {}
        self._community_squashed = {_squash(community) for community in self._communities}
        self._known_names = self._hierarchy(rows)
        self._homes = self._home_communities(rows)
        # communities the hierarchy actually holds buildings in ("City Walk" is only an alias)
        self._real = {_plain_key(row.get("community_key")) for row in rows} - {""}

    def source_place(self, fields: Mapping[str, Any]) -> Place | None:
        area = _first(fields, "area_name")
        master = _first(fields, "master_project", "master_project_land")
        project = _first(fields, "project_name", "project_land")
        building = fields.get("building_name")
        # A master the hierarchy knows only as a name ("City Walk", "Victory Heights") stays a
        # master: such a label cannot be told apart from a sub-project ("ELO 2"), so a sub-project
        # is only recognised through a "Community - Building" label below.
        *heads, tail = _split_dash(clean_label(building)) or [""]
        if (
            heads
            and not self._is_known(place_key(clean_label(building)))
            and self._is_known(place_key(tail))
        ):
            # "DAMAC HILLS (2) - ELO 2": the community, then the building
            building, area = tail, " - ".join(label for label in (area, *heads) if label)
        place = self._place(
            area=area, master=master, project=project, building=building, known_only=True
        )
        no_where = not place.community and not place.project
        if no_where and all(_GENERIC_BUILDING.fullmatch(key) for key in place.buildings):
            return None  # "Tower 1" exists in many communities
        return place

    def event_place(self, event: Mapping[str, Any]) -> Place:
        # DLD (Transactions) rows carry the ``_en`` columns; DXBI events do not
        registry = any(
            not _is_blank(event.get(name))
            for name in ("master_project_en", "project_name_en", "area_name_en")
        )
        return self._place(
            area=_first(event, "area_name", "area_name_en"),
            master=_first(event, "master_project", "master_project_en"),
            project=_first(event, "project_name", "project_name_en"),
            building=event.get("building_name") or event.get("building_name_en"),
            community=_first(event, "community_name"),
            registry=registry,
        )

    def same_place(self, a: Place, b: Place) -> bool:
        if self._numbers_conflict(a, b):
            return False
        communities_agree = None
        if a.community_labels and b.community_labels:
            # Whole labels only: "villa" is inside "jumeirahvillagetriangle", "hills" inside
            # "emirateshills", "spring" inside "springs3"; none of those is the same community.
            communities_agree = bool(a.community_labels & b.community_labels)
            if not communities_agree:
                return False
        if a.buildings and b.buildings and not self._buildings_agree(a, b):
            return False
        names_agree = None
        if a.names and b.names:
            names_agree = _overlap(a.names, b.names) or self._markers_agree(a, b)
            if not names_agree:
                return False
        return bool(communities_agree or names_agree)

    @staticmethod
    def _numbers_conflict(a: Place, b: Place) -> bool:
        """The same numbered label ("Springs - N") with different numbers on the two sides, or a
        registry row of the numbered family ("Springs 4") that carries no such number at all."""
        for head in {h for h, _ in a.numbered} & {h for h, _ in b.numbered}:
            ours = {n for h, n in a.numbered if h == head}
            theirs = {n for h, n in b.numbered if h == head}
            if ours.isdisjoint(theirs):
                return True
        return any(
            head in y.families and (head, number) not in y.numbered
            for x, y in ((a, b), (b, a))
            for head, number in x.numbered
        )

    @staticmethod
    def _markers_agree(a: Place, b: Place) -> bool:
        """A shared "Tower 2" marker agrees only when the name stems in front of it are close:
        "Glamz Residence Tower 2" is not "Starz Tower 2". A missing or abbreviated stem ("CW")
        cannot contradict."""
        for marker in a.markers & b.markers:
            ours = {s for m, s in a.marker_stems if m == marker}
            theirs = {s for m, s in b.marker_stems if m == marker}
            if not ours or not theirs:
                return True
            for x in ours:
                for y in theirs:
                    short = min(len(x), len(y))
                    if short < _MIN_STEM or _close(x, y):
                        return True
        return False

    def _buildings_agree(self, a: Place, b: Place) -> bool:
        return (
            _overlap(a.buildings, b.buildings)
            or self._markers_agree(a, b)
            or any(
                letter == other and _close(stem, rest)
                for stem, letter in a.towers
                for rest, other in b.towers
            )
            # a side that names a project where the other has a building: the same name, exactly
            or bool({b.project} & set(a.buildings))
            or bool({a.project} & set(b.buildings))
        )

    # ------------------------------------------------------------------ what the hierarchy knows

    def _hierarchy(self, rows: list[Mapping[str, Any]]) -> set[str]:
        """Squashed names of every known building and project, except the communities themselves."""
        raw = {_plain_key(row.get(c)) for row in rows for c in ("name_key", "project_key")}
        for alias, project in self._project_aliases.items():
            raw |= {alias, *self._keys(clean_label(_split_dash(project)[-1]))}
        return {_squash(name) for name in raw} - self._community_squashed - {""}

    def _contradicts(self, found: set[str], masters: set[str]) -> bool:
        """Does a label that names a hierarchy community disagree with the row's own master?"""
        return bool(masters) and masters.isdisjoint(found) and not self._real.isdisjoint(found)

    @staticmethod
    def _home_communities(rows: list[Mapping[str, Any]]) -> dict[str, frozenset[str]]:
        """Squashed building / project name -> the communities the hierarchy holds it in."""
        homes: dict[str, set[str]] = {}
        for row in rows:
            community = _plain_key(row.get("community_key"))
            for column in ("name_key", "project_key"):
                name = _squash(_plain_key(row.get(column)))
                if name and community:
                    homes.setdefault(name, set()).add(community)
        return {name: frozenset(found) for name, found in homes.items()}

    def _is_known(self, key: str) -> bool:
        """Is this label a building or project the hierarchy has? DLD packages and phases are not.

        An unknown label cannot say that a property is elsewhere, so it must not veto a unit and
        price that agree inside the community. A project named like the community is no project.
        """
        cached = self._known_cache.get(key)
        if cached is None:
            squashed = _squash(key)
            cached = (
                bool(squashed)
                and not squashed.isdigit()
                and squashed not in self._community_squashed
                and (
                    squashed in self._known_names
                    or any(_close(squashed, name) for name in self._known_names)
                )
            )
            self._known_cache[key] = cached
        return cached

    def _building_is_known(
        self,
        keys: tuple[str, ...],
        markers: frozenset[str],
        towers: frozenset[tuple[str, str]],
    ) -> bool:
        # "Building 11B" or "Tower B" is a building designator whether or not the hierarchy
        # lists it; a package or phase label has none.
        return bool(markers or towers) or any(self._is_known(key) for key in keys)

    # ------------------------------------------------------------------ building the place

    def _keys(self, text: str) -> set[str]:
        """Keys of a label and of its ``A - B`` parts; broad words and bare numbers say nothing."""
        pieces = (text, *_split_dash(text)) if text else ()
        # "DAMAC Hills 2 (Akoya by DAMAC)": the bracketed qualifier is not part of the name
        bare = (_ABBREVIATION.sub("", piece) for piece in pieces)
        keys = {place_key(piece) for piece in (*pieces, *map(_drop_initialism, pieces), *bare)}
        return {key for key in keys if key and not key.isdigit() and key not in _BROAD}

    def _community_labels(self, text: str) -> set[str]:
        keys = self._keys(text)
        for key in list(keys):
            if key in self._master_aliases:
                keys |= self._keys(clean_label(self._master_aliases[key]))
        return keys

    def _project_labels(self, text: str, follow: bool = True) -> tuple[set[str], set[str]]:
        """(community labels, specific names) of a project label like "Arabian Ranches III - Ruba"."""
        if not text:
            return set(), set()
        *heads, tail = _split_dash(text)
        names = self._keys(tail)
        communities = self._community_labels(text if heads else tail)
        for head in heads:
            communities |= self._community_labels(head)
        if follow:
            for key in names | {place_key(text)}:
                if key in self._project_aliases:
                    more_communities, more_names = self._project_labels(
                        clean_label(self._project_aliases[key]), follow=False
                    )
                    communities |= more_communities
                    names |= more_names
        return communities, names

    @staticmethod
    def _resolved_key(text: str, aliases: Mapping[str, str]) -> str:
        key = place_key(text)
        if not key or key.isdigit() or key in _BROAD:
            return ""
        return place_key(aliases.get(key, key))

    def _place(
        self,
        *,
        area: str,
        master: str,
        project: str,
        building: Any,
        community: str = "",
        known_only: bool = False,
        registry: bool = False,
    ) -> Place:
        labels: set[str] = set()
        masters: set[str] = set()  # the labels that come from a master / community field
        community_key = ""
        for text in (master, area, community):
            found = self._community_labels(text)
            labels |= found
            if text in (master, community):
                masters |= found
            community_key = community_key or self._resolved_key(text, self._master_aliases)
        project_communities, names = self._project_labels(project)
        # A project named like a community says where the row is only when no master says it
        # ("AL FURJAN" under the DLD master Business Bay is a misfiled project).
        if (
            known_only
            or len(_split_dash(project)) > 1
            or not self._contradicts(project_communities, masters)
        ):
            labels |= project_communities
        if not community_key and len(_split_dash(project)) > 1:
            community_key = self._resolved_key(_split_dash(project)[0], self._master_aliases)
        building_text = clean_label(building)
        keys, stems = self._building_keys(building, building_text)
        markers = frozenset(marker for marker, _ in stems)
        # "Jumeirah Village Triangle (JVT)": the abbreviation does not change the community
        named = clean_label(_ABBREVIATION.sub("", str(building or "")))
        if keys and _plain_key(named) in self._communities:
            # DXBI files some buildings under a legal area: area "Jabal Ali 1", building "Al Furjan"
            if known_only or not self._contradicts(self._community_labels(named), masters):
                labels |= self._community_labels(named)
                community_key = place_key(named)
            keys, markers, stems = (), frozenset(), frozenset()
        towers = frozenset(t for t in map(_tower, (building_text,) if keys else ()) if t)
        if known_only:
            # A sheet label restricts the place only if it is a known building or project
            names = {name for name in names if self._is_known(name)}
            if not self._building_is_known(keys, frozenset(markers), towers):
                keys, markers, towers, stems = (), frozenset(), frozenset(), frozenset()
        else:
            # DLD files some projects under a master that contradicts the hierarchy ("Reem - Mira
            # Oasis" under DAMAC HILLS 2). A known building's own community outranks the master
            # label, when something else on the row (its legal area) corroborates it.
            home = frozenset().union(
                *(self._homes.get(_squash(key), frozenset()) for key in (*keys, place_key(project)))
            )
            others = labels - masters
            contradicted = {label for label in masters - home if label in self._real}
            if others & home and contradicted:
                labels = others | (masters - contradicted)
                community_key = community_key if community_key in labels else min(labels)
        names |= set(keys)
        numbered = frozenset(
            (place_key(found[1]), found[2])
            for text in (master, area, community, project)
            if (found := _NUMBERED.fullmatch(text))
        )
        families = frozenset(
            place_key(found[1])
            for text in (project, building_text)
            if registry and (found := _FAMILY.fullmatch(_split_dash(text)[-1]))
        )
        return Place(
            community_key,
            self._resolved_key(project, self._project_aliases),
            keys[0] if keys else "",
            frozenset(labels),
            frozenset(names),
            keys,
            frozenset(markers),
            towers,
            stems,
            numbered,
            families,
        )

    @staticmethod
    def _building_keys(raw: Any, text: str) -> tuple[tuple[str, ...], frozenset[tuple[str, str]]]:
        """Building keys, and the ``(marker, stem)`` pairs of its "Tower 2" designators."""
        listed = _LISTED.fullmatch(str(raw or ""))
        if listed:
            # "NO. 4A, NO.4B, NO.5 CITYWALK RESIDENTIAL" is three buildings
            codes = [code.lower() for code in _LISTED_CODE.findall(listed[1])]
            keys = tuple(place_key(f"{listed[2]} {code}") for code in codes)
            return keys, frozenset((f"bldg{code}", place_key(listed[2])) for code in codes)
        key = place_key(text)
        marker = _MARKER.search(text)
        stems = (
            frozenset({(f"bldg{marker[1].lower()}", place_key(_MARKER.sub(" ", text)))})
            if marker
            else frozenset()
        )
        return ((key,) if key else ()), stems


class CachedPlaceIndex(PlaceIndex):
    """Event places are a function of a few labels; 2.7M events share a few thousand of them."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._event_places: dict[tuple[Any, ...], Place] = {}
        self._same: dict[tuple[Any, ...], dict[int, bool]] = {}
        self.same_place_hits = 0

    def same_place(self, a: Place, b: Place) -> bool:
        """Memoised by what ``a`` says and which cached event place ``b`` is (they live forever)."""
        known = self._same.setdefault(
            (
                a.community,
                a.project,
                a.building,
                a.community_labels,
                a.names,
                a.buildings,
                a.markers,
                a.towers,
                a.marker_stems,
                a.numbered,
                a.families,
            ),
            {},
        )
        answer = known.get(id(b))
        if answer is None:
            answer = known[id(b)] = super().same_place(a, b)
        else:
            self.same_place_hits += 1
        return answer

    def event_place(self, event: Any) -> Place:
        labels = (
            event.get("area_name"),
            event.get("area_name_en"),
            event.get("master_project"),
            event.get("master_project_en"),
            event.get("project_name"),
            event.get("project_name_en"),
            event.get("building_name"),
            event.get("building_name_en"),
            event.get("community_name"),
        )
        place = self._event_places.get(labels)
        if place is None:
            place = self._event_places[labels] = super().event_place(event)
        return place
