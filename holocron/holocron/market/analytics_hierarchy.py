"""One master -> project -> building hierarchy for the Analytics pages, and unit counts per level.

The DXBI profiles (holocron.market.dxbi_profile) name a project and a master per record, from
whatever DLD registration the record paired with, so the same project could sit under several
masters and appear in several spellings ("MERANO TOWER" / "Merano Tower"). This module turns the
records' names into one hierarchy, built after the profiles and before the listed tables, which
carry its keys (decisions 2026-10-21, docs/data-pipelines/ANALYTICS_HIERARCHY_PLAN.md):

* A name's key is its letters and digits in lower case; a DXBI project label "X (all buildings)"
  is X. One key is one project, merged further only by ``project_aliases.csv`` (with evidence).
* A project shows DXBI's spelling where DXBI uses the name, else DLD's (title case for capitals).
* A project has one master: the most common master of its records after ``master_aliases.csv``
  (spellings, DLD sub-communities folded into their community, projects DLD uses as masters),
  unless ``project_masters.csv`` names it. A master shows DXBI's spelling where DXBI has it.
* A building is a DXBI building name in its DXBI community. A name most of whose records sit in
  one project is that project's building; a name several projects share without a majority
  ("Tower 2") is one building per project that holds a fifth of its records. Place names,
  DXBI project labels and DLD plot references are not
  buildings. One name in one project is one building whatever DXBI community its records carry,
  unless they sit on different DLD buildings. Two names of one project matching the same DLD
  building by unit numbers, one name extending the other ("Merano" / "Merano Tower"), are one
  building.
* Records keep their own project (the user reviews the ones filed elsewhere than their building's
  project first); ``stray`` marks them on the listed tables.
* Units name their source: DXBI's building list, then DLD's unit register (a building matched by
  unit numbers, at their floor areas where towers repeat the numbers, or the project), then DLD's
  land register (villa plots). A project DLD holds under another name, or under no project, is
  linked to it by its unit numbers and floor areas (``analytics_project_dld_keys``). A DLD
  building two buildings match counts for neither. A count below the units that traded there is
  not a count of the stock: those traded units are given instead, marked ``units_at_least``.
  Unit numbers are compared and counted in one form (``unit_key``).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from holocron.market import dxbi_profile as profile
from holocron.market import transforms as t

DATA = Path(__file__).with_name("data")
MASTER_ALIASES_CSV = DATA / "master_aliases.csv"
PROJECT_ALIASES_CSV = DATA / "project_aliases.csv"
PROJECT_MASTERS_CSV = DATA / "project_masters.csv"

HIERARCHY_TABLES = (
    "analytics_master_keys",
    "analytics_project_keys",
    "analytics_projects",
    "analytics_project_dld_keys",
    "analytics_building_keys",
    "analytics_buildings",
    "analytics_unit_stock",
)
WORK_TABLE = "analytics_place_records__work"

# A name most of whose records sit in one project is one building of that project (the rest are
# filed elsewhere, ``stray``). A name with no majority is one building per project that holds at
# least SPLIT_SHARE of its records (and SPLIT_RECORDS); its other records have no building.
BUILDING_PROJECT_SHARE = 0.5
SPLIT_SHARE = 0.2
SPLIT_RECORDS = 5
# A name is one building per project too when its records split between sister projects of one
# master community below this share ("Capria 5" is a building of Capria East and of Capria
# West), or when the name is generic and a second project holds SPLIT_SHARE ("Tower A" of Club
# Drive and of Address Residences, Dubai Hills).
SISTER_SPLIT_SHARE = 0.6
GENERIC_BUILDING = profile.GENERIC_BUILDING
# The name that can name a project: DXBI's project for a generic name it qualifies ("Tower A" of
# Club Drive), else the building's own.
_NAMING_KEY = (
    "if(position({n}.community_key, '/') > 0, splitByChar('/', {n}.community_key)[2], {n}.name_key)"
)
_ID_NAMING_KEY = (
    "if(position(splitByChar('|', f.final_id)[2], '/') > 0,"
    " splitByChar('/', splitByChar('|', f.final_id)[2])[2], splitByChar('|', f.final_id)[1])"
)
# A count below this share of the units that traded is not the building's or project's stock.
UNITS_TRADED_FLOOR = 0.9
# A project DLD's unit register holds under another name: one DLD project (or building) holds
# this share of the project's unit numbers, at least UNIT_MATCH_MIN, each with its floor area
# within SIZE_TOLERANCE.
UNIT_MATCH_SHARE = 0.8
UNIT_MATCH_MIN = 5
SIZE_TOLERANCE = 0.02


# The building statements nest the same CTEs many times over (each CTE is inlined): ClickHouse's
# default cap of 10,000 plan optimizations refuses analytics_buildings.
_SETTINGS = f"{t._HEAVY_QUERY_SETTINGS},\n    query_plan_max_optimizations_to_apply = 100000"

key = profile.name_key
_without_all = profile.without_all
project_key = profile.project_key


def _dxbi_label(expr: str) -> str:
    """A DXBI place name as shown: no "(all …)" suffix, a short bracket in capitals ("(JBR)")."""
    bare = _without_all(expr)
    return (
        f"if(match({bare}, '\\([A-Za-z]{{2,5}}\\)$'), "
        f"concat(replaceRegexpOne({bare}, '\\([A-Za-z]{{2,5}}\\)$', ''), '(', "
        f"upperUTF8(extract({bare}, '\\(([A-Za-z]{{2,5}})\\)$')), ')'), {bare})"
    )


def named_like(name_key: str, project_key: str) -> str:
    """A project named like the building (both as keys): the same name, the building's name
    ending the project's ("Nice 1" / "Damac Lagoons - Nice 1"), or one is the other and "tower",
    "residence" or "building" ("Merano" / "Merano Tower"). A generic name names no project."""
    suffix = "(towers?|residences?|building)$"
    return (
        f"(NOT match({name_key}, '{GENERIC_BUILDING}') AND ({project_key} = {name_key}"
        f" OR (length({name_key}) >= 5 AND endsWith({project_key}, {name_key}))"
        f" OR match({project_key}, concat('^', {name_key}, '{suffix}'))"
        f" OR match({name_key}, concat('^', {project_key}, '{suffix}'))))"
    )


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _array(values: list[str]) -> str:
    return "[" + ", ".join(profile._sql_text(v) for v in values) + "]"


def _lookup(expr: str, pairs: list[tuple[str, str]], default: str) -> str:
    """``transform`` over literal arrays (an empty mapping is the default itself)."""
    if not pairs:
        return default
    sources, targets = zip(*pairs, strict=True)
    return f"transform({expr}, {_array(list(sources))}, {_array(list(targets))}, {default})"


def _master_alias(expr: str) -> str:
    """A record's master after the curated aliases (matched by key), else itself."""
    pairs = [(_py_key(row["alias"]), row["master"]) for row in _csv_rows(MASTER_ALIASES_CSV)]
    return _lookup(key(expr), pairs, expr)


def _project_alias(key_expr: str) -> str:
    pairs = [
        (_py_key(row["alias"]), _py_key(row["project"])) for row in _csv_rows(PROJECT_ALIASES_CSV)
    ]
    return _lookup(key_expr, pairs, key_expr)


def _project_master(key_expr: str) -> str:
    pairs = [(_py_key(row["project"]), row["master"]) for row in _csv_rows(PROJECT_MASTERS_CSV)]
    return _lookup(key_expr, pairs, "''")


def _py_key(name: str) -> str:
    import re

    name = re.sub(r"(?i)\s*\(all (buildings|phases)\)\s*$", "", name)
    return re.sub(r"[^a-z0-9]", "", name.lower())


# Every DXBI or DLD sale and lease, with the names its profile and DXBI give it. Built once per
# hierarchy build and dropped after (the steps below each read it).
_WORK_DDL = f"""CREATE TABLE {WORK_TABLE} (
    record_key String, kind LowCardinality(String), raw_scope String,
    raw_kind LowCardinality(String), project_source LowCardinality(String), building String,
    community String, master String, dld_area String, unit_key String, size_sqft Float64,
    dxbi_project String
) ENGINE = MergeTree ORDER BY record_key"""


def unit_key(expr: str) -> str:
    """A unit number as DXBI and DLD both write it, for matching and counting: a share of a unit
    ("2510 (Q 3)", Ciel's quarter shares) is that unit; "FLAT 415", "Unit No. 415" and "415" are
    one, as are "A-101", "A 101" and "A101", and "0103" and "103". Damac's estate prefixes are
    dropped: DXBI writes a Damac Hills 2 villa "DH2-XR1139B" on a sale and "XR1139B" on a lease
    (2,194 such pairs in 25 buildings), a Damac Lagoons one "DL-K138" and "K138"."""
    upper = f"upperUTF8(trimBoth({expr}))"
    bare = f"replaceRegexpOne({upper}, '\\s*\\([^)]*\\)\\s*$', '')"
    unprefixed = (
        f"replaceRegexpOne({bare}, "
        "'^((UNIT|FLAT|APT|APARTMENT|APPARTMENT)(\\s*NO)?\\s*[.:#-]?|(DH2|DL)\\s*[- ])\\s*', '')"
    )
    return (
        f"replaceRegexpAll(replaceRegexpAll({unprefixed}, '[^A-Z0-9]', ''), "
        "'(^|[^0-9])0+([0-9])', '\\\\1\\\\2')"
    )


def non_residential(key_expr: str) -> str:
    """A unit key DXBI writes for a shop, office, parking bay or store room."""
    return (
        f"match({key_expr}, '(SHOP|RETAIL|SHOWROOM|OFFICE|PARKING|STORE|STORAGE|KIOSK|"
        "RESTAURANT|SUPERMARKET|STALL|GYM|CLINIC|NURSERY|WAREHOUSE|CAFE|COMMERCIAL)')"
    )


_UNIT_KEY = unit_key("x.unit_number")
_BUILDING_OK = (
    "p.building_name != '' AND p.building_source IN ('dxbi', 'dxbi_sale') "
    "AND NOT match(p.building_name, '(?i)\\(all (buildings|phases)\\)\\s*$')"
)
_WORK_SQL = f"""
INSERT INTO {WORK_TABLE}
SELECT p.sale_key, 'sale',
       if(p.project_source = 'place_name', '', p.project_name),
       if(p.project_source = 'own_building', 'Building', 'Project'), p.project_source,
       if({_BUILDING_OK}, p.building_name, ''), x.area_name, p.master_project, p.area_name,
       {_UNIT_KEY}, p.size_sqft, x.project_name
FROM dxbi_sale_profile AS p
INNER JOIN (
    SELECT sale_key, area_name, unit_number, project_name FROM ({t.DXBI_SALES_BASE})
) AS x ON x.sale_key = p.sale_key
UNION ALL
SELECT p.contract_key, 'lease',
       if(p.project_source = 'place_name', '', p.project_name),
       if(p.project_source = 'own_building', 'Building', 'Project'), p.project_source,
       if({_BUILDING_OK}, p.building_name, ''), x.area_name, p.master_project, p.area_name,
       {_UNIT_KEY}, p.size_sqft, x.project_name
FROM dxbi_rental_profile AS p
INNER JOIN (
    SELECT contract_key, any(area_name) AS area_name, any(unit_number) AS unit_number,
           any(project_name) AS project_name
    FROM dxbi_rental_events FINAL GROUP BY contract_key
) AS x ON x.contract_key = p.contract_key
{_SETTINGS}
"""

# Masters as DXBI's location tree spells them, by key (with and without a bracketed short form).
_DXBI_MASTER_NAMES = f"""
    dxbi_master_names AS (
        SELECT k, argMax(name, rank) AS name FROM (
            SELECT arrayJoin([{key("label")}, {profile._place_key("label")}]) AS k,
                   label AS name, multiIf(flag = 'M', 3, flag = 'U', 2, 1) AS rank
            FROM (SELECT {_dxbi_label("name")} AS label, flag FROM dxbi_locations
                  WHERE flag IN ('M', 'U', 'A') AND name != '')
        )
        WHERE k != ''
        GROUP BY k
    )"""
# A record's master, canonical: aliases first, then DXBI's spelling, else DLD's in title case.
_RECORD_MASTERS = f"""
    aliased AS (
        SELECT DISTINCT master AS raw, {_master_alias("master")} AS alias
        FROM {WORK_TABLE} WHERE master != ''
    ),
    record_masters AS (
        SELECT a.raw AS raw,
               if(dn.name != '', dn.name, {profile.title_case("a.alias")}) AS name
        FROM aliased AS a
        LEFT JOIN dxbi_master_names AS dn ON dn.k = {key("a.alias")}
    )"""

MASTER_KEYS_SQL = f"""
INSERT INTO `analytics_master_keys` (raw_key, master_key, master_name, built_at)
WITH {_DXBI_MASTER_NAMES}, {_RECORD_MASTERS}
SELECT {key("raw")} AS raw_key, {key("any(name)")}, any(name), now64(3)
FROM record_masters
GROUP BY raw_key
"""

# Every spelling of a project -> its project (the aliases' targets are keys of other spellings).
_RECORD_PROJECTS = f"""
    record_projects AS (
        SELECT w.kind AS kind, w.raw_scope AS raw_scope, w.raw_kind AS raw_kind,
               w.dld_area AS dld_area, w.community AS community,
               {_project_alias(project_key("w.raw_scope"))} AS project_key,
               mk.mk_master AS master_name
        FROM {WORK_TABLE} AS w
        LEFT JOIN (SELECT raw_key AS mk_raw, master_name AS mk_master
                   FROM analytics_master_keys) AS mk ON mk.mk_raw = {key("w.master")}
        WHERE w.raw_scope != ''
    )"""

PROJECT_KEYS_SQL = f"""
INSERT INTO `analytics_project_keys` (raw_key, project_key, built_at)
SELECT raw_key, any(project_key), now64(3) FROM (
    SELECT DISTINCT {key("raw_scope")} AS raw_key,
           {_project_alias(project_key("raw_scope"))} AS project_key
    FROM {WORK_TABLE} WHERE raw_scope != ''
    UNION ALL
    -- The bare key of "X (all buildings)" too, so a link with either spelling finds X.
    SELECT DISTINCT {project_key("raw_scope")}, {_project_alias(project_key("raw_scope"))}
    FROM {WORK_TABLE} WHERE raw_scope != ''
)
GROUP BY raw_key
"""

# DXBI's own spelling of a name, by key: its projects, buildings and location-tree labels.
_DXBI_NAMES = f"""
    dxbi_names AS (
        SELECT k, argMax(name, n) AS name FROM (
            SELECT {project_key("name")} AS k, {_dxbi_label("name")} AS name, count() AS n
            FROM (
                SELECT arrayJoin([project_name, building_name]) AS name
                FROM dxbi_sales_unit_events
                UNION ALL
                SELECT arrayJoin([project_name, building_name]) FROM dxbi_rental_events
                UNION ALL
                SELECT arrayJoin([project_label, building_label]) FROM dxbi_places
            )
            WHERE name != ''
            GROUP BY k, name
        )
        GROUP BY k
    )"""

PROJECTS_SQL = f"""
INSERT INTO `analytics_projects`
    (project_key, project_name, scope_kind, master_key, master_name, master_source, area_name,
     sales, leases, spellings, built_at)
WITH {_DXBI_NAMES}, {_DXBI_MASTER_NAMES}, {_RECORD_PROJECTS},
    spellings AS (
        SELECT project_key, argMax(raw_scope, n) AS top_spelling,
               groupArray(raw_scope) AS spellings
        FROM (SELECT project_key, raw_scope, count() AS n FROM record_projects
              GROUP BY project_key, raw_scope)
        GROUP BY project_key
    ),
    votes AS (
        SELECT project_key, argMax(master_name, n) AS voted FROM (
            SELECT project_key, master_name, count() AS n FROM record_projects
            WHERE master_name != '' GROUP BY project_key, master_name)
        GROUP BY project_key
    ),
    -- A project DLD gives no master (a tower in Al Barsha 1) is in its DXBI community.
    communities AS (
        SELECT project_key, argMax(community, n) AS community FROM (
            SELECT project_key, community, count() AS n FROM record_projects
            WHERE community != '' GROUP BY project_key, community)
        GROUP BY project_key
    ),
    facts AS (
        SELECT project_key, countIf(kind = 'sale') AS sales, countIf(kind = 'lease') AS leases,
               if(countIf(raw_kind = 'Project') > 0, 'Project', 'Building') AS scope_kind,
               topKIf(1)(dld_area, dld_area != '') AS areas
        FROM record_projects GROUP BY project_key
    ),
    curated AS (
        SELECT DISTINCT project_key, {_project_master("project_key")} AS master
        FROM record_projects
    )
SELECT f.project_key,
       if(dn.name != '', dn.name, {profile.title_case("s.top_spelling")}),
       f.scope_kind,
       {key("multiIf(c.master != '', c.master, v.voted != '', v.voted, cm.master)")},
       multiIf(c.master != '', c.master, v.voted != '', v.voted, cm.master),
       multiIf(c.master != '', 'curated', v.voted != '', 'records',
               cm.master != '', 'dxbi_community', 'none'),
       if(length(f.areas) > 0, f.areas[1], ''),
       f.sales, f.leases, s.spellings, now64(3)
FROM facts AS f
LEFT JOIN spellings AS s ON s.project_key = f.project_key
LEFT JOIN votes AS v ON v.project_key = f.project_key
LEFT JOIN curated AS c ON c.project_key = f.project_key
LEFT JOIN (
    SELECT co.project_key AS project_key,
           if(mn.name != '', mn.name, {profile.title_case("co.community")}) AS master
    FROM communities AS co
    LEFT JOIN dxbi_master_names AS mn ON mn.k = {key("co.community")}
) AS cm ON cm.project_key = f.project_key
LEFT JOIN dxbi_names AS dn ON dn.k = f.project_key
{_SETTINGS}
"""

# DLD's unit register, the newest complete snapshot: one holding at least 90% of the largest
# snapshot's rows, so a partial scan never replaces a full one. A register group is a unit's DLD
# project; a unit DLD files under no project (most older towers) is in its DLD building.
_DLD_UNITS = """(SELECT * FROM dld_od_units_bronze
     WHERE run_id = (
         SELECT argMax(run_id, scraped) FROM (
             SELECT run_id, max(scraped_at) AS scraped, count() AS n
             FROM dld_od_units_bronze GROUP BY run_id)
         WHERE n >= 0.9 * (SELECT max(c) FROM (
             SELECT count() AS c FROM dld_od_units_bronze GROUP BY run_id))))"""
_DLD_GROUP = (
    "if(project_en != '', concat('p:', toString(project_id)), "
    "concat('b:', toString(area_id), '/', land_number, '/', building_number))"
)
# Each register unit with the DXBI project it belongs to: its name's, else the project linked to
# its group by unit numbers (analytics_project_dld_keys).
_DLD_UNIT_PROJECTS = f"""(
        SELECT u.*, if(l.project_key != '', l.project_key, u.name_project) AS project_key
        FROM (SELECT *, {_project_alias(project_key("project_en"))} AS name_project,
                     {_DLD_GROUP} AS dld_group
              FROM {_DLD_UNITS}) AS u
        LEFT JOIN (SELECT dld_group AS l_group, project_key FROM analytics_project_dld_keys) AS l
            ON l.l_group = u.dld_group
    )"""

# A project with no register units under its name, or a DXBI building that no DLD project names
# ("Geepas Tower"): the register group in its DLD area that holds its unit numbers at the same
# floor areas. A group another DXBI project holds by name, or that
# two projects claim, links none (a phase, a duplicate or a mis-filed project, not this one).
PROJECT_DLD_KEYS_SQL = f"""
INSERT INTO `analytics_project_dld_keys`
    (project_key, dld_group, dld_name, matched, unit_numbers, built_at)
WITH
    register AS (
        SELECT {_DLD_GROUP} AS dld_group, project_en,
               {_project_alias(project_key("project_en"))} AS name_key,
               {unit_key("unit_number")} AS unit_key, actual_area * {t.SQFT_PER_SQM} AS sqft,
               lowerUTF8(area_en) AS area, {key("master_project_en")} AS master_key
        FROM {_DLD_UNITS}
        WHERE unit_number != ''
    ),
    -- DLD's 2026 open data renamed areas after their communities ("JUMEIRAH VILLAGE CIRCLE");
    -- the register keeps the older area, whose units name that community as their master.
    candidates AS (
        SELECT project_key, lowerUTF8(area_name) AS area, {key("area_name")} AS area_key
        FROM analytics_projects
        WHERE area_name != ''
          AND project_key NOT IN (SELECT name_key FROM register WHERE name_key != '')
    ),
    unit_sizes AS (
        SELECT {_project_alias(project_key("raw_scope"))} AS project_key, unit_key,
               median(size_sqft) AS sqft
        FROM {WORK_TABLE}
        WHERE raw_scope != '' AND unit_key NOT IN ('', '0') AND size_sqft > 0
        GROUP BY project_key, unit_key
        HAVING project_key IN (SELECT project_key FROM candidates)
    ),
    votes AS (
        SELECT s.project_key AS project_key, r.dld_group AS dld_group,
               any(r.project_en) AS dld_name, uniqExact(s.unit_key) AS n
        FROM unit_sizes AS s
        INNER JOIN candidates AS c ON c.project_key = s.project_key
        INNER JOIN register AS r ON r.unit_key = s.unit_key
        WHERE abs(r.sqft - s.sqft) <= {SIZE_TOLERANCE} * r.sqft
          AND (r.area = c.area OR r.master_key = c.area_key)
        GROUP BY project_key, dld_group
    ),
    links AS (
        SELECT v.project_key AS project_key, argMax((v.dld_group, v.dld_name), v.n) AS best,
               max(v.n) AS matched, any(z.units) AS unit_numbers,
               arrayReverseSort(groupArray(v.n)) AS ranked
        FROM votes AS v
        INNER JOIN (SELECT project_key, count() AS units FROM unit_sizes GROUP BY project_key)
            AS z ON z.project_key = v.project_key
        GROUP BY project_key
        -- Twin towers hold the same numbers at the same areas: a tie links neither.
        HAVING matched >= {UNIT_MATCH_SHARE} * unit_numbers AND matched >= {UNIT_MATCH_MIN}
           AND (length(ranked) = 1 OR ranked[2] < matched)
    )
SELECT project_key, best.1, best.2, matched, unit_numbers, now64(3)
FROM links
WHERE best.1 IN (SELECT best.1 FROM links GROUP BY best.1 HAVING count() = 1)
  AND best.1 NOT IN (
      SELECT dld_group FROM register
      WHERE name_key IN (SELECT project_key FROM analytics_projects))
{_SETTINGS}
"""

# Buildings. A "building" a fifth of whose records are a place name's is a place, not a building.
_BUILDING_LOOSE = (
    "replaceRegexpAll(replaceRegexpAll(lowerUTF8({e}), "
    # A word boundary is \\b in a ClickHouse literal ('\\b' alone is a backspace).
    "'\\\\b(the|tower|towers|residence|residences|building|apartments?)\\\\b', ''), "
    "'[^a-z0-9]', '')"
)
# The building steps, each computed once into a work table the next ones read (inlined as CTEs,
# each statement recomputed the whole chain several times and outgrew 9 GB).
FIRST_IDS_TABLE = "analytics_first_ids__work"
RECORD_IDS_TABLE = "analytics_record_ids__work"
DLD_VOTES_TABLE = "analytics_dld_votes__work"
MERGED_TABLE = "analytics_building_merge__work"
_BUILDING_WORK_DDL = (
    f"""CREATE TABLE {FIRST_IDS_TABLE} (name_key String, community_key String,
    project_key String, building_id String, home_project String)
ENGINE = MergeTree ORDER BY (name_key, community_key, project_key)""",
    f"""CREATE TABLE {RECORD_IDS_TABLE} (record_key String, kind LowCardinality(String),
    building String, community String, unit_key String, size_sqft Float64, project_key String,
    building_id String, home_project String) ENGINE = MergeTree ORDER BY building_id""",
    f"""CREATE TABLE {DLD_VOTES_TABLE} (building_id String, dld_building String)
ENGINE = MergeTree ORDER BY building_id""",
    f"""CREATE TABLE {MERGED_TABLE} (building_id String, final_id String)
ENGINE = MergeTree ORDER BY building_id""",
)
_BUILDING_SOURCE = f"""
    building_records AS (
        SELECT w.record_key AS record_key, w.kind AS kind, w.building AS building,
               {key("w.building")} AS name_key,
               {profile.building_community_key("w.building", "w.community", "w.dxbi_project")}
                   AS community_key,
               w.community AS community, w.unit_key AS unit_key, w.size_sqft AS size_sqft,
               if(w.raw_scope != '', {_project_alias(project_key("w.raw_scope"))}, '')
                   AS project_key,
               w.project_source = 'place_name' AS place
        FROM {WORK_TABLE} AS w
        WHERE w.building != ''
    )"""
_FIRST_IDS = f"""
    name_votes AS (
        SELECT name_key, community_key, project_key, count() AS n
        FROM building_records WHERE NOT place AND project_key != ''
        GROUP BY name_key, community_key, project_key
    ),
    -- A building's project: one named like it (Spring Oasis, though It Plaza pairings
    -- outnumber it; at least 5 records and a tenth of them, any in a building of under 5),
    -- else the most common.
    names AS (
        SELECT name_key, community_key,
               if(named != '', named, top) AS top_project, top_n, voted, named,
               if(length(ranked) > 1, ranked[2].2, '') AS second, ranked[2].1 AS second_n
        FROM (
            SELECT b.name_key AS name_key, b.community_key AS community_key,
                   argMax(v.project_key, v.n) AS top, max(v.n) AS top_n, sum(v.n) AS voted,
                   argMaxIf(v.project_key, v.n,
                            {named_like(_NAMING_KEY.format(n="b"), "v.project_key")})
                       AS named_any,
                   maxIf(v.n, {named_like(_NAMING_KEY.format(n="b"), "v.project_key")})
                       AS named_n,
                   -- In a building of under 5 records one record's name decides
                   -- (Emaar Square 5: 2 records, 1 paired to The Heart Of Europe 2).
                   if((named_n >= 5 AND named_n >= 0.1 * voted) OR (voted < 5 AND named_n >= 1),
                      named_any, '') AS named,
                   arrayReverseSort(x -> x.1, groupArray((v.n, v.project_key))) AS ranked
            FROM (SELECT name_key, community_key FROM building_records
                  GROUP BY name_key, community_key HAVING countIf(place) < 0.2 * count()) AS b
            INNER JOIN name_votes AS v
                ON v.name_key = b.name_key AND v.community_key = b.community_key
            GROUP BY b.name_key, b.community_key
        )
    ),
    -- One building per project: no project holds half the name's records, or the name splits
    -- between sister projects or is generic (SISTER_SPLIT_SHARE).
    name_shapes AS (
        SELECT n.name_key AS name_key, n.community_key AS community_key,
               n.top_project AS top_project, n.voted AS voted,
               n.named = '' AND (
                   n.top_n < {BUILDING_PROJECT_SHARE} * n.voted
                   OR (match(n.name_key, '{GENERIC_BUILDING}')
                       AND position(n.community_key, '/') = 0
                       AND n.second_n >= {SPLIT_SHARE} * n.voted
                       AND n.second_n >= {SPLIT_RECORDS})
                   OR (n.top_n < {SISTER_SPLIT_SHARE} * n.voted AND tm.m_master != ''
                       AND tm.m_master = sm.m_master)
               ) AS split
        FROM names AS n
        LEFT JOIN (SELECT project_key AS m_key, master_key AS m_master FROM analytics_projects)
            AS tm ON tm.m_key = n.top_project
        LEFT JOIN (SELECT project_key AS m_key, master_key AS m_master FROM analytics_projects)
            AS sm ON sm.m_key = n.second
    ),
    -- The building each (name, community[, project]) is before merging spellings.
    first_ids AS (
        SELECT n.name_key AS name_key, n.community_key AS community_key, '' AS project_key,
               concat(n.name_key, '|', n.community_key) AS building_id,
               n.top_project AS home_project
        FROM name_shapes AS n WHERE NOT n.split
        UNION ALL
        SELECT n.name_key, n.community_key, v.project_key,
               concat(n.name_key, '|', n.community_key, '|', v.project_key), v.project_key
        FROM name_shapes AS n
        INNER JOIN name_votes AS v
            ON v.name_key = n.name_key AND v.community_key = n.community_key
        WHERE n.split AND v.n >= {SPLIT_SHARE} * n.voted AND v.n >= {SPLIT_RECORDS}
    )"""
_RECORD_IDS = """
    record_ids AS (
        SELECT r.record_key AS record_key, r.kind AS kind, r.building AS building,
               r.community AS community, r.unit_key AS unit_key, r.size_sqft AS size_sqft,
               r.project_key AS project_key, if(c.c_id != '', c.c_id, s.s_id) AS building_id,
               if(c.c_id != '', c.c_home, s.s_home) AS home_project
        FROM building_records AS r
        LEFT JOIN (SELECT name_key AS c_name, community_key AS c_community, building_id AS c_id,
                          home_project AS c_home
                   FROM first_ids WHERE project_key = '') AS c
            ON c.c_name = r.name_key AND c.c_community = r.community_key
        LEFT JOIN (SELECT name_key AS s_name, community_key AS s_community,
                          project_key AS s_project, building_id AS s_id, home_project AS s_home
                   FROM first_ids WHERE project_key != '') AS s
            ON s.s_name = r.name_key AND s.s_community = r.community_key
           AND s.s_project = r.project_key
        WHERE NOT r.place
    )"""
_DLD_VOTES = f"""
    -- DLD's unit register, keyed by the DXBI project each unit belongs to.
    dld_units AS (
        SELECT project_key, {unit_key("unit_number")} AS unit_key,
               concat(toString(area_id), '/', land_number, '/', building_number) AS dld_building,
               actual_area * {t.SQFT_PER_SQM} AS sqft
        FROM {_DLD_UNIT_PROJECTS}
        WHERE unit_number != '' AND project_key != ''
    ),
    -- The DLD building a building's unit numbers sit in (>= 80% of >= 3 matches). Where the
    -- towers of a project repeat their unit numbers ("101" in each), the numbers at the same
    -- floor area decide.
    dld_votes AS (
        SELECT building_id,
               max(n) >= 0.8 * sum(n) AND sum(n) >= 3 AS by_number,
               if(by_number, argMax(dld_building, n), argMax(dld_building, n_sized))
                   AS dld_building
        FROM (
            SELECT r.building_id AS building_id, d.dld_building AS dld_building,
                   uniqExact(r.unit_key) AS n,
                   uniqExactIf(r.unit_key, abs(d.sqft - r.sqft) <= {SIZE_TOLERANCE} * d.sqft)
                       AS n_sized
            FROM (SELECT building_id, home_project, unit_key, median(size_sqft) AS sqft
                  FROM record_ids
                  WHERE building_id != '' AND unit_key NOT IN ('', '0')
                  GROUP BY building_id, home_project, unit_key) AS r
            INNER JOIN dld_units AS d
                ON d.project_key = r.home_project AND d.unit_key = r.unit_key
            GROUP BY building_id, dld_building
        )
        GROUP BY building_id
        HAVING by_number OR (max(n_sized) >= 0.8 * sum(n_sized) AND sum(n_sized) >= 3)
    )"""
_MERGED = f"""
    id_facts AS (
        SELECT building_id, any(home_project) AS home_project, count() AS records,
               any(building) AS some_name
        FROM record_ids WHERE building_id != '' GROUP BY building_id
    ),
    -- One name in one project is one building, whichever DXBI community its records carry
    -- ("Zaabeel 2" / "Zabeel 2", "Al Furjan" / "Jabal Ali 1"), unless they sit on different DLD
    -- buildings (two "Indigo Tower"s): the one with more records keeps its id.
    name_ids AS (
        SELECT f.building_id AS building_id,
               if(g.lead_id != '', g.lead_id, f.building_id) AS name_id
        FROM id_facts AS f
        LEFT JOIN (
            SELECT f2.home_project AS home_project,
                   splitByChar('|', f2.building_id)[1] AS name_key,
                   argMax(f2.building_id, f2.records) AS lead_id
            FROM id_facts AS f2
            LEFT JOIN dld_votes AS d2 ON d2.building_id = f2.building_id
            GROUP BY home_project, name_key
            HAVING uniqExactIf(d2.dld_building, d2.dld_building != '') <= 1
        ) AS g ON g.home_project = f.home_project
              AND g.name_key = splitByChar('|', f.building_id)[1]
    ),
    name_facts AS (
        SELECT n.name_id AS building_id, any(f.home_project) AS home_project,
               sum(f.records) AS records, argMax(f.some_name, f.records) AS some_name,
               max(dv.dld_building) AS dld_building
        FROM name_ids AS n
        INNER JOIN id_facts AS f ON f.building_id = n.building_id
        LEFT JOIN dld_votes AS dv ON dv.building_id = n.building_id
        GROUP BY n.name_id
    ),
    -- Two spellings in one project on one DLD building, one extending the other, are one
    -- building: the one with more records keeps its id.
    merged AS (
        SELECT n.building_id AS building_id,
               if(g.lead_id != '' AND {_BUILDING_LOOSE.format(e="f.some_name")} != ''
                  AND (startsWith({_BUILDING_LOOSE.format(e="f.some_name")},
                                  {_BUILDING_LOOSE.format(e="g.lead_name")})
                       OR startsWith({_BUILDING_LOOSE.format(e="g.lead_name")},
                                     {_BUILDING_LOOSE.format(e="f.some_name")})),
                  g.lead_id, f.building_id) AS final_id
        FROM name_ids AS n
        INNER JOIN name_facts AS f ON f.building_id = n.name_id
        LEFT JOIN (
            SELECT home_project, dld_building, argMax(building_id, records) AS lead_id,
                   argMax(some_name, records) AS lead_name
            FROM name_facts WHERE dld_building != ''
            GROUP BY home_project, dld_building
        ) AS g ON g.home_project = f.home_project AND g.dld_building = f.dld_building
           AND f.dld_building != ''
    )"""
_RECORD_IDS_READ = f"record_ids AS (SELECT * FROM {RECORD_IDS_TABLE})"
_BUILDING_WORK_SQL = (
    f"""INSERT INTO {FIRST_IDS_TABLE}
WITH {_BUILDING_SOURCE}, {_FIRST_IDS}
SELECT name_key, community_key, project_key, building_id, home_project FROM first_ids
{_SETTINGS}""",
    f"""INSERT INTO {RECORD_IDS_TABLE}
WITH {_BUILDING_SOURCE}, first_ids AS (SELECT * FROM {FIRST_IDS_TABLE}), {_RECORD_IDS}
SELECT record_key, kind, building, community, unit_key, size_sqft, project_key, building_id,
       home_project
FROM record_ids
{_SETTINGS}""",
    f"""INSERT INTO {DLD_VOTES_TABLE}
WITH {_RECORD_IDS_READ}, {_DLD_VOTES}
SELECT building_id, dld_building FROM dld_votes
{_SETTINGS}""",
    f"""INSERT INTO {MERGED_TABLE}
WITH {_RECORD_IDS_READ}, dld_votes AS (SELECT * FROM {DLD_VOTES_TABLE}), {_MERGED}
SELECT building_id, final_id FROM merged
{_SETTINGS}""",
)
_BUILDING_WORK_TABLES = (FIRST_IDS_TABLE, RECORD_IDS_TABLE, DLD_VOTES_TABLE, MERGED_TABLE)
_BUILDING_READS = f"""{_RECORD_IDS_READ},
    merged AS (SELECT * FROM {MERGED_TABLE}),
    dld_votes AS (SELECT * FROM {DLD_VOTES_TABLE})"""

BUILDING_KEYS_SQL = f"""
INSERT INTO `analytics_building_keys`
    (name_key, community_key, project_key, building_id, built_at)
SELECT i.name_key, i.community_key, i.project_key,
       if(m.final_id != '', m.final_id, i.building_id), now64(3)
FROM {FIRST_IDS_TABLE} AS i
LEFT JOIN {MERGED_TABLE} AS m ON m.building_id = i.building_id
{_SETTINGS}
"""

BUILDINGS_SQL = f"""
INSERT INTO `analytics_buildings`
    (building_id, building_name, community, project_key, project_name, master_key, master_name,
     project_share, records, sales, leases, dld_building, dld_claims, named_project, generic_name,
     spellings, built_at)
WITH {_DXBI_NAMES}, {_BUILDING_READS},
    final_records AS (
        SELECT r.kind AS kind, r.building AS building, r.community AS community,
               r.project_key AS project_key, r.home_project AS home_project,
               if(m.final_id != '', m.final_id, r.building_id) AS final_id
        FROM record_ids AS r LEFT JOIN merged AS m ON m.building_id = r.building_id
        WHERE r.building_id != ''
    ),
    spellings AS (
        SELECT final_id, argMax(building, n) AS top_spelling, groupArray(building) AS spellings
        FROM (SELECT final_id, building, count() AS n FROM final_records
              GROUP BY final_id, building)
        GROUP BY final_id
    ),
    facts AS (
        SELECT final_id, argMax(hp, records_in) AS home_project, any(community) AS community,
               count() AS records, countIf(kind = 'sale') AS sales,
               countIf(kind = 'lease') AS leases, countIf(rp = hp) / count() AS share
        FROM (SELECT final_id, community, kind, project_key AS rp, home_project AS hp,
                     count() OVER (PARTITION BY final_id, home_project) AS records_in
              FROM final_records)
        GROUP BY final_id
    ),
    -- How many buildings (after merging spellings) matched each DLD building.
    dld AS (
        SELECT final_id, dld_building, count() OVER (PARTITION BY dld_building) AS claims
        FROM (
            SELECT m.final_id AS final_id, any(dv.dld_building) AS dld_building
            FROM merged AS m INNER JOIN dld_votes AS dv ON dv.building_id = m.building_id
            GROUP BY final_id
        )
    )
SELECT f.final_id,
       if(dn.name != '', dn.name, s.top_spelling),
       f.community, f.home_project, p.project_name, p.master_key, p.master_name,
       f.share, f.records, f.sales, f.leases, d.dld_building, d.claims,
       {named_like(_ID_NAMING_KEY, "f.home_project")},
       match(splitByChar('|', f.final_id)[1], '{GENERIC_BUILDING}')
           AND position(splitByChar('|', f.final_id)[2], '/') = 0,
       s.spellings, now64(3)
FROM facts AS f
LEFT JOIN spellings AS s ON s.final_id = f.final_id
LEFT JOIN dxbi_names AS dn ON dn.k = {key("s.top_spelling")}
LEFT JOIN analytics_projects AS p ON p.project_key = f.home_project
LEFT JOIN dld AS d ON d.final_id = f.final_id
{_SETTINGS}
"""

# DLD's rooms in the Analytics configuration words ("1 B/R", "Studio"); an office is "Office".
_MIX_ROOMS = f"""multiIf(
    {profile._bedrooms_from_dld("rooms_en")} = 'Studio', 'Studio',
    {profile._bedrooms_from_dld("rooms_en")} != '',
    concat(extract({profile._bedrooms_from_dld("rooms_en")}, '^([0-9]+)'), ' B/R'),
    rooms_en IN ('Office', 'Shop', 'Warehouse', 'Hotel', 'Show Rooms', 'Clinic', 'Gymnasium'),
    rooms_en, 'Other')"""
# DXBI's building list: a building card (not a project card) by name and DXBI area.
_CARDS = f"""
    cards AS (
        SELECT {key("JSONExtractString(payload_json, 'Building', 'location')")} AS name_key,
               {key("JSONExtractString(payload_json, 'Building', 'area_name')")} AS area_key,
               {project_key("JSONExtractString(payload_json, 'Building', 'project')")}
                   AS card_project,
               JSONExtractString(payload_json, 'Building', 'display_as') AS display_as,
               JSONExtractUInt(payload_json, 'Building', 'unit_count') AS units
        FROM (SELECT * FROM dxbi_heatmap_buildings_bronze WHERE status = 200
              LIMIT 1 BY location_id)
        WHERE units > 0
    )"""

_W_COMMUNITY = profile.building_community_key("w.building", "w.community", "w.dxbi_project")

UNIT_STOCK_SQL = f"""
INSERT INTO `analytics_unit_stock`
    (scope_level, scope_id, units, units_source, units_at_least, units_traded, buildings,
     mix_rooms, mix_units, mix_median_sqft, mix_source, built_at)
WITH {_CARDS},
    dld_units AS (
        SELECT project_key,
               concat(toString(area_id), '/', land_number, '/', building_number) AS dld_building,
               property_id, {_MIX_ROOMS} AS rooms, actual_area * {t.SQFT_PER_SQM} AS sqft,
               {unit_key("unit_number")} AS unit_key
        FROM {_DLD_UNIT_PROJECTS}
    ),
    -- A unit traded: a unit number, and for a shop, office or parking code one the project's
    -- register holds (DLD registers some shops as units, a parking bay never).
    record_buildings AS (
        SELECT w.kind AS kind, w.unit_key AS unit_key, w.building AS building_text,
               if(w.raw_scope != '', {_project_alias(project_key("w.raw_scope"))}, '')
                   AS project_key,
               if(c.building_id != '', c.building_id, s.building_id) AS building_id,
               w.unit_key NOT IN ('', '0')
                   AND (NOT {non_residential("w.unit_key")} OR rc.rc_unit != '') AS countable
        FROM {WORK_TABLE} AS w
        LEFT JOIN (SELECT DISTINCT project_key AS rc_project, unit_key AS rc_unit FROM dld_units
                   WHERE project_key != '' AND {non_residential("unit_key")}) AS rc
            ON rc.rc_project = if(w.raw_scope != '',
                                  {_project_alias(project_key("w.raw_scope"))}, '')
           AND rc.rc_unit = w.unit_key
        LEFT JOIN (SELECT * FROM analytics_building_keys WHERE project_key = '') AS c
            ON c.name_key = {key("w.building")} AND c.community_key = {_W_COMMUNITY}
           AND w.building != ''
        LEFT JOIN (SELECT * FROM analytics_building_keys WHERE project_key != '') AS s
            ON s.name_key = {key("w.building")} AND s.community_key = {_W_COMMUNITY}
           AND s.project_key = if(w.raw_scope != '',
                                  {_project_alias(project_key("w.raw_scope"))}, '')
           AND w.building != ''
    ),
    building_traded AS (
        SELECT building_id, uniqExactIf(unit_key, countable) AS traded
        FROM record_buildings WHERE building_id != '' GROUP BY building_id
    ),
    building_cards AS (
        SELECT b.building_id AS building_id, max(cd.units) AS units
        FROM analytics_buildings AS b
        INNER JOIN (
            SELECT *, count() OVER (PARTITION BY name_key) AS same_name
            FROM cards WHERE display_as != 'P'
        ) AS cd ON cd.name_key = splitByChar('|', b.building_id)[1]
        -- A name DXBI lists in several areas must be in the building's own community.
        WHERE cd.same_name = 1 OR cd.area_key = {key("b.community")}
        GROUP BY building_id
    ),
    building_dld AS (
        SELECT b.building_id AS building_id, uniqExact(u.property_id) AS units
        FROM analytics_buildings AS b
        INNER JOIN dld_units AS u ON u.dld_building = b.dld_building
        WHERE b.dld_building != '' AND b.dld_claims = 1
        GROUP BY building_id
    ),
    building_mix AS (
        SELECT building_id, groupArray(rooms) AS mix_rooms, groupArray(n) AS mix_units,
               groupArray(med) AS mix_sqft
        FROM (
            SELECT b.building_id AS building_id, u.rooms AS rooms,
                   toUInt32(uniqExact(u.property_id)) AS n, round(median(u.sqft)) AS med
            FROM analytics_buildings AS b
            INNER JOIN dld_units AS u ON u.dld_building = b.dld_building
            WHERE b.dld_building != '' AND b.dld_claims = 1
            GROUP BY building_id, rooms ORDER BY building_id, rooms
        )
        GROUP BY building_id
    ),
    buildings_stock AS (
        SELECT b.building_id AS building_id, b.project_key AS project_key,
               b.records AS records,
               bc.units AS card_units, bd.units AS dld_units, bt.traded AS traded
        FROM analytics_buildings AS b
        LEFT JOIN building_cards AS bc ON bc.building_id = b.building_id
        LEFT JOIN building_dld AS bd ON bd.building_id = b.building_id
        LEFT JOIN building_traded AS bt ON bt.building_id = b.building_id
    ),
    building_choice AS (
        SELECT *,
               multiIf(card_units > 0 AND card_units >= {UNITS_TRADED_FLOOR} * traded,
                       ('dxbi_buildings', card_units),
                       dld_units > 0 AND dld_units >= {UNITS_TRADED_FLOOR} * traded,
                       ('dld_units', dld_units),
                       traded > 0, ('units_traded', traded), ('', 0)) AS pick
        FROM buildings_stock
    ),
    -- Units traded in the project's own buildings; a project without buildings (villas DXBI
    -- lists by project) counts its records' units. A record filed here from another project's
    -- building, from a place name, or (in a project with buildings) without a building is
    -- often a pairing from elsewhere and is not counted; nor is a record of its building whose
    -- pairing named another project (the listed records file it here, but its unit number is
    -- the least certain). Buildings on one DLD building (two spellings, or towers DLD registers
    -- as one) hold one set of unit numbers.
    project_traded AS (
        SELECT project_key, if(in_buildings > 0, in_buildings, without_building) AS traded
        FROM (
            SELECT r.project_key AS project_key,
                   uniqExactIf((if(b.b_dld != '', b.b_dld, r.building_id), r.unit_key),
                               b.b_project = r.project_key AND r.countable)
                       AS in_buildings,
                   uniqExactIf(r.unit_key, r.building_id = '' AND r.building_text = ''
                                           AND r.countable) AS without_building
            FROM record_buildings AS r
            LEFT JOIN (SELECT building_id AS b_id, project_key AS b_project,
                              dld_building AS b_dld
                       FROM analytics_buildings) AS b ON b.b_id = r.building_id
            WHERE r.project_key != ''
            GROUP BY project_key
        )
    ),
    project_cards AS (
        SELECT card_project AS project_key, max(units) AS units
        FROM cards WHERE display_as = 'P' AND card_project != '' GROUP BY project_key
    ),
    -- The project's buildings, when the buildings with a register count hold nearly all its
    -- building records.
    project_buildings AS (
        SELECT project_key, count() AS buildings,
               sumIf(pick.2, pick.1 != 'units_traded') AS units,
               sumIf(records, pick.1 IN ('dxbi_buildings', 'dld_units')) / sum(records)
                   AS covered,
               countIf(pick.1 != 'dxbi_buildings') = 0 AS all_dxbi
        FROM building_choice GROUP BY project_key
    ),
    project_dld AS (
        SELECT project_key, uniqExact(property_id) AS units FROM dld_units
        WHERE project_key != '' GROUP BY project_key
    ),
    project_mix AS (
        SELECT project_key, groupArray(rooms) AS mix_rooms, groupArray(n) AS mix_units,
               groupArray(med) AS mix_sqft
        FROM (
            SELECT project_key, rooms, toUInt32(uniqExact(property_id)) AS n,
                   round(median(sqft)) AS med
            FROM dld_units WHERE project_key != ''
            GROUP BY project_key, rooms ORDER BY project_key, rooms
        )
        GROUP BY project_key
    ),
    -- Villa plots: DLD's land register, residential plots in any snapshot. The snapshots number
    -- a plot alike but tag it differently (area 505 / 0, sub-number '0' / ''): a plot is its
    -- area name, land number and sub-number.
    project_plots AS (
        SELECT {_project_alias(project_key("project_en"))} AS project_key,
               uniqExact(lowerUTF8(area_en), land_number,
                         if(land_sub_number IN ('', '0'), '', land_sub_number)) AS units
        FROM dld_od_lands_bronze
        WHERE project_en != '' AND prop_sub_type_en = 'Residential'
        GROUP BY project_key
    ),
    project_stock AS (
        SELECT p.project_key AS project_key, pt.traded AS traded, pc.units AS card_units,
               if(pb.covered >= 0.95, pb.units, 0) AS building_units,
               if(pb.all_dxbi, 'dxbi_buildings', 'buildings') AS building_source,
               pb.buildings AS buildings, pd.units AS dld_units, pp.units AS plots
        FROM analytics_projects AS p
        LEFT JOIN project_traded AS pt ON pt.project_key = p.project_key
        LEFT JOIN project_cards AS pc ON pc.project_key = p.project_key
        LEFT JOIN project_buildings AS pb ON pb.project_key = p.project_key
        LEFT JOIN project_dld AS pd ON pd.project_key = p.project_key
        LEFT JOIN project_plots AS pp ON pp.project_key = p.project_key
    )
SELECT 'building', c.building_id, c.pick.2, c.pick.1, c.pick.1 = 'units_traded', c.traded, 1,
       m.mix_rooms, m.mix_units, m.mix_sqft,
       if(length(m.mix_rooms) > 0, 'dld_units', ''), now64(3)
FROM building_choice AS c
LEFT JOIN building_mix AS m ON m.building_id = c.building_id
WHERE c.pick.2 > 0
UNION ALL
SELECT 'project', s.project_key, pick.2, pick.1, pick.1 = 'units_traded', s.traded, s.buildings,
       m.mix_rooms, m.mix_units, m.mix_sqft,
       if(length(m.mix_rooms) > 0, 'dld_units', ''), now64(3)
FROM (
    SELECT *,
           multiIf(card_units > 0 AND card_units >= {UNITS_TRADED_FLOOR} * traded,
                   ('dxbi_buildings', card_units),
                   building_units > 0 AND building_units >= {UNITS_TRADED_FLOOR} * traded,
                   (building_source, building_units),
                   dld_units > 0 AND dld_units >= {UNITS_TRADED_FLOOR} * traded,
                   ('dld_units', dld_units),
                   plots > 0 AND plots >= {UNITS_TRADED_FLOOR} * traded,
                   ('dld_land_plots', plots),
                   traded > 0, ('units_traded', traded), ('', 0)) AS pick
    FROM project_stock
) AS s
LEFT JOIN project_mix AS m ON m.project_key = s.project_key
WHERE pick.2 > 0
{_SETTINGS}
"""

STATEMENTS = {
    "analytics_master_keys": MASTER_KEYS_SQL,
    "analytics_project_keys": PROJECT_KEYS_SQL,
    "analytics_projects": PROJECTS_SQL,
    "analytics_project_dld_keys": PROJECT_DLD_KEYS_SQL,
    "analytics_building_keys": BUILDING_KEYS_SQL,
    "analytics_buildings": BUILDINGS_SQL,
    "analytics_unit_stock": UNIT_STOCK_SQL,
}


def create_tables(clickhouse: Any) -> None:
    for table in HIERARCHY_TABLES:
        clickhouse.command(profile._create_statement(table))


def build_hierarchy(clickhouse: Any) -> dict[str, int]:
    """Every hierarchy table in order (each reads the ones before it), from the profiles."""
    create_tables(clickhouse)
    work = (WORK_TABLE, *_BUILDING_WORK_TABLES)
    for table in work:
        clickhouse.command(f"DROP TABLE IF EXISTS {table}")
    clickhouse.command(_WORK_DDL)
    for ddl in _BUILDING_WORK_DDL:
        clickhouse.command(ddl)
    try:
        clickhouse.command(_WORK_SQL)
        built = {}
        for table in HIERARCHY_TABLES:
            if table == "analytics_building_keys":
                # The building steps read the projects and their DLD links built above.
                for statement in _BUILDING_WORK_SQL:
                    clickhouse.command(statement)
            built[table] = profile.build_table(
                clickhouse, table, STATEMENTS[table], allow_empty=True
            )
        return built
    finally:
        for table in work:
            clickhouse.command(f"DROP TABLE IF EXISTS {table}")
