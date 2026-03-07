import re
from typing import Literal

Usage = Literal["residential", "commercial", "mixed_use", "unknown"]
Stage = Literal["existing", "off_plan", "upcoming", "all"]


def normalize_whitespace(value: str) -> str:
    return " ".join((value or "").strip().split())


def normalize_unit_type(value: str) -> str:
    raw = normalize_whitespace(value).lower()
    if not raw or raw in {"na", "n/a", "unknown"}:
        return "other"

    patterns = [
        (r"^studio$", "studio"),
        (r"^(1|one)\s*(b\/r|br|bed(room)?s?\+?hall?)$", "1br"),
        (r"^(2|two)\s*(b\/r|br|bed(room)?s?\+?hall?)$", "2br"),
        (r"^(3|three)\s*(b\/r|br|bed(room)?s?\+?hall?)$", "3br"),
        (r"^(4|four)\s*(b\/r|br|bed(room)?s?\+?hall?)$", "4br"),
        (r"^(5|six|7|8|9|10|\d+)\s*(b\/r|br|bed(room)?s?\+?hall?)$", "4br+"),
        (r"penthouse", "4br+"),
        (r"villa", "villa"),
        (r"townhouse", "townhouse"),
        (r"office", "office"),
        (r"shop|retail|store|showroom|kiosk|restaurant", "retail"),
        (
            r"warehouse|workshop|industrial|factory|labor camp|staff accommod",
            "industrial",
        ),
        (r"hotel", "hospitality"),
    ]
    normalized = re.sub(r"[\s\-_/]+", "", raw)
    for pattern, canonical in patterns:
        if re.search(pattern, raw) or re.search(pattern, normalized):
            return canonical
    return "other"


def infer_usage_from_plot(
    land_use_values: list[str], gfa_type: str, general_notes: list[str]
) -> Usage:
    haystack = " ".join(
        [
            *(land_use_values or []),
            gfa_type or "",
            *(general_notes or []),
        ]
    ).lower()
    has_res = any(
        token in haystack
        for token in ["residential", "villa", "apartment", "townhouse", "dwelling"]
    )
    has_com = any(
        token in haystack
        for token in [
            "commercial",
            "office",
            "retail",
            "shopping center",
            "shop",
            "hotel",
            "hospitality",
            "warehouse",
            "industrial",
        ]
    )
    if has_res and has_com:
        return "mixed_use"
    if has_res:
        return "residential"
    if has_com:
        return "commercial"
    return "unknown"


def normalize_usage_value(value: str) -> Usage:
    raw = normalize_whitespace(value).lower()
    if not raw:
        return "unknown"
    if "residential" in raw and "commercial" in raw:
        return "mixed_use"
    if "residential" in raw or "hospitality" in raw:
        return "residential"
    if any(token in raw for token in ["commercial", "industrial", "storage"]):
        return "commercial"
    return "unknown"


def normalize_project_stage(value: str) -> Stage:
    raw = normalize_whitespace(value).upper()
    if raw in {"FINISHED"}:
        return "existing"
    if raw in {"ACTIVE"}:
        return "off_plan"
    if raw in {"NOT_STARTED", "PENDING", "CONDITIONAL_ACTIVATING"}:
        return "upcoming"
    return "all"


def transaction_usage_clause(usage: Usage, column: str = "property_usage_en") -> str:
    if usage == "residential":
        return f"({column} IN ('Residential', 'Hospitality ', 'Hospitality'))"
    if usage == "commercial":
        return f"({column} IN ('Commercial', 'Industrial', 'Storage'))"
    if usage == "mixed_use":
        return f"({column} IN ('Residential / Commercial', 'Multi-Use', 'Industrial / Commercial', 'Industrial / Commercial / Residential'))"
    return "1 = 1"


def transaction_stage_clause(stage: Stage, column: str = "reg_type_en") -> str:
    if stage == "existing":
        return f"{column} = 'Existing Properties'"
    if stage == "off_plan":
        return f"{column} = 'Off-Plan Properties'"
    return "1 = 1"


def canonical_unit_type_case_sql(column: str = "rooms_en") -> str:
    return f"""
    multiIf(
        match(lowerUTF8(trimBoth({column})), '^studio$'), 'studio',
        match(lowerUTF8(trimBoth({column})), '^(1|one)\\s*(b/r|br|bed(room)?s?\\+?hall?)$'), '1br',
        match(lowerUTF8(trimBoth({column})), '^(2|two)\\s*(b/r|br|bed(room)?s?\\+?hall?)$'), '2br',
        match(lowerUTF8(trimBoth({column})), '^(3|three)\\s*(b/r|br|bed(room)?s?\\+?hall?)$'), '3br',
        match(lowerUTF8(trimBoth({column})), '^(4|four)\\s*(b/r|br|bed(room)?s?\\+?hall?)$'), '4br',
        match(lowerUTF8(trimBoth({column})), '^(5|6|7|8|9|10|\\d+)\\s*(b/r|br|bed(room)?s?\\+?hall?)$'), '4br+',
        match(lowerUTF8(trimBoth({column})), 'penthouse'), '4br+',
        match(lowerUTF8(trimBoth({column})), 'villa'), 'villa',
        match(lowerUTF8(trimBoth({column})), 'townhouse'), 'townhouse',
        match(lowerUTF8(trimBoth({column})), 'office'), 'office',
        match(lowerUTF8(trimBoth({column})), 'shop|retail|store|showroom|kiosk|restaurant'), 'retail',
        match(lowerUTF8(trimBoth({column})), 'warehouse|workshop|industrial|factory|labor camp|staff accommod'), 'industrial',
        match(lowerUTF8(trimBoth({column})), 'hotel'), 'hospitality',
        'other'
    )
    """
