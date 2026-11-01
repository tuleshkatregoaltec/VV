"""Literal keyword matching shared by DXBI location searches.

Every word must match a location field; numeric tokens match whole words so 02
cannot select 03 or 102. Provider labels and transaction identities stay intact.
"""

import re
import unicodedata


def location_keywords(value: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).lower())))


def location_keyword_clause(expression: str, value: str, params: dict) -> str:
    tokens = location_keywords(value)
    if not tokens:
        return "1 = 1"
    # SQL string escaping leaves the Unicode character classes intact for RE2.
    normalized = rf"replaceRegexpAll(lowerUTF8(normalizeUTF8NFKC({expression})), '[^\\p{{L}}\\p{{N}}]+', ' ')"
    clauses = []
    for i, token in enumerate(tokens):
        key = f"location_word_{i}"
        params[key] = token
        if token.isdecimal():
            clauses.append(f"has(splitByChar(' ', {normalized}), {{{key}:String}})")
        else:
            clauses.append(f"positionUTF8({normalized}, {{{key}:String}}) > 0")
    return " AND ".join(clauses)
