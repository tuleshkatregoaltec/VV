"""Shared name normalization for market-facing labels and search aliases."""

from __future__ import annotations

import re
from dataclasses import dataclass

AREA_ALIASES = {
    "jvc": "Jumeirah Village Circle",
    "jumeirah village circle": "Jumeirah Village Circle",
    "dubai marina": "Dubai Marina",
    "jlt": "Jumeirah Lakes Towers",
    "jumeirah lake towers": "Jumeirah Lakes Towers",
    "jumeirah lakes towers": "Jumeirah Lakes Towers",
    "jbr": "Jumeirah Beach Residence",
    "jumeirah beach residence": "Jumeirah Beach Residence",
    "downtown": "Downtown Dubai",
    "downtown dubai": "Downtown Dubai",
}

AREA_CONTAINS_ALIASES = (
    (("jvc", "jumeirah village circle"), "Jumeirah Village Circle"),
    (("jbr", "jumeirah beach residence"), "Jumeirah Beach Residence"),
    (("jlt", "jumeirah lake towers", "jumeirah lakes towers"), "Jumeirah Lakes Towers"),
)

DEVELOPER_BRAND_ALIASES = {
    "ALFURJAN ( L.L.C )": "Nakheel",
    "BUSINESS BAY (L.L.C)": "Dubai Properties",
    "DISTRICT ONE - FZ": "Meydan",
    "DUBAI AVIATION CITY CORPORATION": "Dubai South Developers",
    "DUBAI CREEK HARBOUR L.L.C": "Emaar",
    "DUBAI HILLS ESTATE L.L.C": "Emaar",
    "DUBAI LAND (L.L.C)": "Dubai Properties",
    "DUBAI LAND RESIDENCES (L.L.C)": "Dubai Properties",
    "DUBAI PROPERTIES(L.L.C)": "Dubai Properties",
    "DUBAI PROPERTIES (L.L.C)": "Dubai Properties",
    "EMAAR DEVELOPMENT (P.J.S.C)": "Emaar",
    "EMAAR DEVELOPMENT P.J.S.C.": "Emaar",
    "EMAAR PROPERTIES (P.J.S.C)": "Emaar",
    "INTERNATIONAL CITY ( L.L.C )": "Nakheel",
    "JUMAIRAH VILLAGE L.L.C": "Nakheel",
    "MERAAS ESTATES (L.L.C)": "Meraas",
    "NAKHEEL .(P J S C)": "Nakheel",
    "LIWAN (L.L.C)": "Dubai Properties",
    "REMRAAM L.L.C": "Dubai Properties",
    "SHAMAL ESTATES L.L.C": "Shamal",
    "DHAM FZ-LLC": "Dubai Holding",
    "DAMAC PROPERTIES CO. LLC": "DAMAC",
    "DAMAC WORLD REAL ESTATE L.L.C": "DAMAC",
    "BINGHATTI DEVELOPERS FZE": "Binghatti",
    "MEYDAN GROUP (L.L.C)": "Meydan",
    "MEYDAN CITY CORPORATION": "Meydan",
    "SOBHA L.L.C": "Sobha",
    "DUBAI HEALTHCARE CITY FZ - LLC": "Dubai Healthcare City",
    "JUMEIRAH HILLS DEVELOPMENT L.L.C": "Jumeirah Hills",
    "CITYWALK RESIDENTIAL 1 L.L.C": "Meraas",
    "DUBAI MARITIME CITY FZE": "Dubai Maritime City",
    "TECOM INVESTMENTS FZ-LLC": "TECOM",
    "DUBAI INVESTMENT REAL ESTATE (L L C)": "Dubai Investments",
    "MINA RASHID PROPERTIES L.L.C": "Mina Rashid",
    "AL KHAIL HEIGHTS L.L.C": "Al Khail Heights",
    "AL HABTOOR CITY REAL ESTATE DEVELOPMENT (BR. OF DUBAI NATIONAL INVESTMENT CO L.L.C)": "Al Habtoor",
    "ONE ZAABEEL L.L.C": "One Za'abeel",
    "MERAAS BAY AND RESIDENCE L.L.C": "Meraas",
    "THE LAGOONS PHASE ONE L.L.C": "Emaar",
    "THE PALM - DEIRA (L.L.C)": "Nakheel",
    "THE PALM - JEBEL ALI CO. (L.L.C)": "Nakheel",
    "THE PALM - JUMEIRAH CO. (L.L.C)": "Nakheel",
    "THE WORLD ( L.L.C )": "Nakheel",
}

DEVELOPER_LEGAL_ENTITY_PATTERN = re.compile(
    r"\b(l\.?\s*l\.?\s*c\.?|fz-?\s*llc|fze|fzco|p\.?\s*j\.?\s*s\.?\s*c\.?|p\.?\s*s\.?\s*c\.?|limited)\b",
    re.IGNORECASE,
)


def area_search_text(area: str) -> str:
    normalized = " ".join(area.lower().replace("(", " ").replace(")", " ").split())
    for tokens, canonical_name in AREA_CONTAINS_ALIASES:
        if any(token in normalized for token in tokens):
            return canonical_name
    return AREA_ALIASES.get(normalized, area.strip())


def listing_area_terms(area: str) -> list[str]:
    search_text = area_search_text(area)
    terms = [area.strip(), search_text]
    if search_text == "Jumeirah Village Circle":
        terms.append("JVC")
    elif search_text == "Jumeirah Beach Residence":
        terms.append("JBR")
    elif search_text == "Jumeirah Lakes Towers":
        terms.extend(["JLT", "Jumeirah Lake Towers"])

    unique_terms: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = " ".join(str(term).strip().split())
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            unique_terms.append(cleaned)
    return unique_terms


def developer_match_key(value: str | None) -> str:
    text_value = (value or "").lower().replace("&", " and ")
    legal_suffixes = (
        r"l\.?\s*l\.?\s*c\.?",
        r"p\.?\s*j\.?\s*s\.?\s*c\.?",
        r"fze",
        r"company",
        r"co",
        r"owned\s+by",
    )
    for suffix in legal_suffixes:
        text_value = re.sub(rf"\b{suffix}\b", " ", text_value)
    text_value = re.sub(r"[^a-z0-9]+", " ", text_value)
    return "".join(part for part in text_value.split() if len(part) > 1)


DEVELOPER_ALIAS_MATCH_KEYS = {
    developer_match_key(alias): brand for alias, brand in DEVELOPER_BRAND_ALIASES.items()
}


def developer_brand_name(developer_name: str) -> str:
    return DEVELOPER_ALIAS_MATCH_KEYS.get(developer_match_key(developer_name), developer_name)


def developer_filter_names(developer_name: str) -> list[str]:
    normalized = developer_name.strip()
    if not normalized:
        return []
    names = {normalized.lower()}
    for source_name, brand_name in DEVELOPER_BRAND_ALIASES.items():
        if brand_name.lower() == normalized.lower():
            names.add(source_name.lower())
    return sorted(names)


def is_rankable_developer_brand(developer_name: str) -> bool:
    return DEVELOPER_LEGAL_ENTITY_PATTERN.search(developer_name) is None


SQM_TO_SQFT = 10.7639


@dataclass(frozen=True, slots=True)
class CommunityLocation:
    """Raw DLD names that make up one community, all lower-case.

    Dubai Pulse rows (to 2025) carry the official DLD area plus a master project; open-data
    rows (from 2026) carry an upper-case community name in the area column, often without a
    master project; rentals carry only the official area. `master_projects` and `areas`
    identify the community itself. `official_areas` are DLD areas that also contain other
    communities and match only rows without a master project. `note` names what such an area
    adds, so an answer can disclose it.
    """

    name: str
    master_projects: tuple[str, ...] = ()
    areas: tuple[str, ...] = ()
    official_areas: tuple[str, ...] = ()
    note: str = ""


# Measured on the 2026-09-30 canonical release (served area/master pairs per community).
COMMUNITY_LOCATIONS = {
    location.name.lower(): location
    for location in (
        CommunityLocation(
            "Jumeirah Village Circle",
            master_projects=("jumeirah village circle",),
            areas=("jumeirah village circle", "al barsha south fourth"),
        ),
        CommunityLocation(
            "Jumeirah Lakes Towers",
            master_projects=("jumeirah lakes towers",),
            areas=("jumeirah lakes towers",),
            official_areas=("al thanyah fifth",),
            note="DLD area Al Thanyah Fifth also contains Jumeirah Islands, Jumeirah Park "
            "and DMCC plots; rentals and DXBI-only rows can only be located at that level.",
        ),
        CommunityLocation(
            "Dubai Marina",
            master_projects=("dubai marina",),
            areas=("dubai marina",),
            official_areas=("marsa dubai",),
            note="DLD area Marsa Dubai also contains JBR, Dubai Harbour and Bluewaters; "
            "rentals and DXBI-only rows can only be located at that level.",
        ),
        CommunityLocation(
            "Business Bay",
            master_projects=("business bay",),
            areas=("business bay",),
        ),
        CommunityLocation(
            "Downtown Dubai",
            master_projects=("downtown dubai",),
            areas=("downtown dubai",),
            official_areas=("burj khalifa",),
            note="DLD area Burj Khalifa also contains part of the Business Bay master "
            "project; rentals and open-data rows without a master project are located there.",
        ),
        CommunityLocation(
            "Dubai Hills Estate",
            master_projects=("dubai hills estate", "dubai hills"),
            areas=("dubai hills", "dubai hills estate"),
            official_areas=("hadaeq sheikh mohammed bin rashid",),
            note="DLD area Hadaeq Sheikh Mohammed Bin Rashid is wider than Dubai Hills Estate.",
        ),
        CommunityLocation(
            "Dubai South",
            master_projects=("dubai south residential district", "dubai south"),
            areas=("dubai south",),
            official_areas=("madinat al mataar",),
            note="DLD area Madinat Al Mataar also contains Dubai World Central.",
        ),
    )
}


def community_location(name: str) -> CommunityLocation:
    """Resolve a community name or alias; unknown names match area or master project exactly."""
    canonical = area_search_text(name)
    found = COMMUNITY_LOCATIONS.get(canonical.lower())
    if found:
        return found
    key = " ".join(name.lower().split())
    return CommunityLocation(name.strip(), master_projects=(key,), areas=(key,))
