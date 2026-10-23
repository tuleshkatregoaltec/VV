"""Remove agents' names that older DXBI loads glued in front of a sale's building.

A stop-gap: delete this module (and its call in ``load_dxbi_sales_units.py``) once the July 2026
scrapes are re-scraped. DXBI's row text holds the buyer's or seller's agent, hidden on screen,
right before the building; sales parsed from that text before the loader read the location title
(``location_title``, commit d406840) carry the agent in front of the building: "Sheetal
Lakeshore Tower 1" is Lakeshore Tower 1. Measured 2026-10-13: 14,056 sales, all from the
``dxbi_sales_dynamic_2026-07-08..10`` files, whose raw text cannot be re-parsed; loads of the
current scraper have none, and leases are not affected. A person's name must not reach any
table, page or export.

Nothing is stripped on a guess. A leading one-to-three-word prefix is removed only when
* what remains is a building DXBI lists in the same area at least three times as often;
* the prefix is not itself a known place name (DXBI's "Binghatti Aquarise Tower C" keeps its
  project name); and
* the prefix reads as a person: none of its words occurs in any place name DLD or DXBI uses,
  or it stands in front of three or more different buildings (an agent sells in many; a
  building's own qualifier, "Hillsedge", "Golden Dream", pairs with one or two), or each of its
  words is a word of a prefix already identified that way ("Ahmed", "Ali").

Every repair is recorded in ``dxbi_building_name_repairs`` (raw name, clean name, the removed
prefix, the rule and the sales that carried the name) and applied to ``dxbi_sales_unit_events``
as a newer version of the sale, with the old version deleted. The step is idempotent and runs
after every sales load.

A review can keep a raw name ("Madina Tower" is a building): a newer row of the name whose clean
name is the raw name (rule ``reviewed``) undoes the repair, and the sales it changed get the raw
name back.
"""

from __future__ import annotations

from typing import Any

from holocron.sources.dxbi.sales_units import location_key_sql

REPAIRS_TABLE = "dxbi_building_name_repairs"
SALES_TABLE = "dxbi_sales_unit_events"

CREATE_REPAIRS_SQL = f"""
CREATE TABLE IF NOT EXISTS {REPAIRS_TABLE} (
    area_key String,
    raw_building_name String,
    building_name String,
    removed_prefix String,
    rule LowCardinality(String),
    sales UInt32,
    built_at DateTime64(3, 'UTC'),
    sale_keys Array(String) DEFAULT []
)
ENGINE = MergeTree()
ORDER BY (area_key, raw_building_name)
"""
# Tables created before the repaired sales were recorded.
ADD_COLUMNS_SQL = [
    f"ALTER TABLE {REPAIRS_TABLE} ADD COLUMN IF NOT EXISTS sale_keys Array(String) DEFAULT []"
]
INSERT_COLUMNS = (
    "area_key, raw_building_name, building_name, removed_prefix, rule, sales, built_at, sale_keys"
)
# Repairs that are weaker evidence of an agent: a one-word prefix whose word occurs in a place
# name ("Madina", "Hayat", "alef" in front of three buildings), and the rules that lean on
# earlier repairs. They are not used to confirm further agents.
DOUBTFUL = (
    "(rule IN ('confirmed_agent', 'person_prefix', 'person_words') "
    "OR (rule = 'many_buildings' AND position(removed_prefix, ' ') = 0))"
)


def _words(expr: str) -> str:
    return f"arrayFilter(t -> t != '', splitByRegexp('[^a-z0-9]+', lowerUTF8({expr})))"


def _name_key(expr: str) -> str:
    return f"replaceRegexpAll(lowerUTF8({expr}), '[^a-z0-9]+', '')"


FIND_REPAIRS_SQL = f"""
INSERT INTO {REPAIRS_TABLE} ({INSERT_COLUMNS})
WITH
    place_names AS (
        SELECT arrayJoin([building_name_en, project_en, master_project_en]) AS name
        FROM dld_od_transactions_bronze
        UNION ALL
        SELECT arrayJoin([project_en, master_project_en]) FROM dld_od_units_bronze
        UNION ALL
        SELECT arrayJoin([building_label, project_label, area_label]) FROM dxbi_places
    ),
    place_words AS (SELECT DISTINCT arrayJoin({_words("name")}) AS word FROM place_names),
    known_names AS (
        SELECT DISTINCT {_name_key("name")} AS name_key FROM place_names WHERE name != ''
    ),
    buildings AS (
        SELECT building_name AS name, lowerUTF8(area_name) AS area_key, count() AS sales,
               groupArray(sale_key) AS sale_keys
        FROM (
            SELECT * FROM {SALES_TABLE} FINAL ORDER BY sale_key, loaded_at DESC
            LIMIT 1 BY sale_key
        )
        WHERE building_name != ''
        GROUP BY name, area_key
    ),
    split AS (
        SELECT b.name AS name, b.area_key AS area_key, b.sales AS sales,
               b.sale_keys AS sale_keys, k,
               arrayStringConcat(arraySlice(splitByChar(' ', b.name), 1, k), ' ') AS prefix,
               arrayStringConcat(arraySlice(splitByChar(' ', b.name), k + 1), ' ') AS rest
        FROM buildings AS b
        ARRAY JOIN [1, 2, 3] AS k
        WHERE length(splitByChar(' ', b.name)) > k
    ),
    -- The rest is a building DXBI lists in the area at least three times as often.
    candidates AS (
        SELECT s.* FROM split AS s
        INNER JOIN buildings AS known ON known.name = s.rest AND known.area_key = s.area_key
        WHERE known.sales >= 3 * s.sales AND known.sales >= 5
          AND {_name_key("s.prefix")} NOT IN (SELECT name_key FROM known_names)
    ),
    spread AS (SELECT prefix, uniqExact(rest) AS buildings FROM candidates GROUP BY prefix),
    first_pass AS (
        SELECT c.*, sp.buildings AS buildings,
               arrayAll(t -> t NOT IN (SELECT word FROM place_words), {_words("c.prefix")})
                   AS no_place_word
        FROM candidates AS c INNER JOIN spread AS sp USING prefix
    ),
    -- Words of prefixes the first two signals already identify as people.
    person_words AS (
        SELECT word FROM (
            SELECT DISTINCT prefix, arrayJoin({_words("prefix")}) AS word
            FROM first_pass WHERE no_place_word OR buildings >= 3
        )
        GROUP BY word HAVING count() >= 2
    ),
    judged AS (
        SELECT *,
               multiIf(no_place_word, 'no_place_word', buildings >= 3, 'many_buildings',
                       arrayAll(t -> t IN (SELECT word FROM person_words),
                                {_words("prefix")}), 'person_words', '') AS rule
        FROM first_pass
    )
SELECT area_key, name, rest, prefix, rule, sales, now64(3), sale_keys
FROM (
    SELECT * FROM judged WHERE rule != ''
    -- The shortest prefix that qualifies: the longest building name survives.
    ORDER BY area_key, name, k
    LIMIT 1 BY area_key, name
)
WHERE (area_key, name) NOT IN (SELECT area_key, raw_building_name FROM {REPAIRS_TABLE})
"""


# A second pass for agents in front of a rarely sold building, where the rest is not common
# enough for the first. The leading part is removed only when it is a full agent name already
# confirmed above (of two words or more), or at least two words each of which is a person's word
# (a word of confirmed agent names, or no place's word at all), and what remains is a known
# building or place name.
# One word alone is never enough: "Hayat Boulevard-1b", "Hamza Tower" and "Madina Tower" are
# buildings.
FIND_RARE_REPAIRS_SQL = f"""
INSERT INTO {REPAIRS_TABLE} ({INSERT_COLUMNS})
WITH
    place_names AS (
        SELECT arrayJoin([building_name_en, project_en, master_project_en]) AS name
        FROM dld_od_transactions_bronze
        UNION ALL
        SELECT arrayJoin([project_en, master_project_en, area_en]) FROM dld_od_units_bronze
        UNION ALL
        SELECT arrayJoin([building_label, project_label, area_label]) FROM dxbi_places
        UNION ALL
        SELECT building_name FROM {REPAIRS_TABLE}
    ),
    place_words AS (SELECT DISTINCT arrayJoin({_words("name")}) AS word FROM place_names),
    known_names AS (
        SELECT DISTINCT {_name_key("name")} AS name_key FROM place_names WHERE name != ''
    ),
    agents AS (
        SELECT DISTINCT removed_prefix AS prefix FROM {REPAIRS_TABLE}
        WHERE rule IN ('no_place_word', 'many_buildings') AND NOT {DOUBTFUL}
    ),
    person_words AS (
        SELECT word FROM (SELECT DISTINCT prefix, arrayJoin({_words("prefix")}) AS word FROM agents)
        GROUP BY word HAVING count() >= 2
    ),
    buildings AS (
        SELECT building_name AS name, lowerUTF8(area_name) AS area_key, count() AS sales,
               groupArray(sale_key) AS sale_keys
        FROM (
            SELECT * FROM {SALES_TABLE} FINAL ORDER BY sale_key, loaded_at DESC
            LIMIT 1 BY sale_key
        )
        WHERE building_name != ''
        GROUP BY name, area_key
    ),
    split AS (
        SELECT b.name AS name, b.area_key AS area_key, b.sales AS sales,
               b.sale_keys AS sale_keys, k,
               arrayStringConcat(arraySlice(splitByChar(' ', b.name), 1, k), ' ') AS prefix,
               arrayStringConcat(arraySlice(splitByChar(' ', b.name), k + 1), ' ') AS rest
        FROM buildings AS b
        ARRAY JOIN range(1, 7) AS k
        WHERE length(splitByChar(' ', b.name)) > k
    ),
    judged AS (
        SELECT *,
               k >= 2 AND prefix IN (SELECT prefix FROM agents) AS confirmed_agent,
               k >= 2 AND arrayAll(t -> t IN (SELECT word FROM person_words)
                                        OR t NOT IN (SELECT word FROM place_words),
                                   {_words("prefix")}) AS person_prefix
        FROM split
        WHERE {_name_key("prefix")} NOT IN (SELECT name_key FROM known_names)
          AND {_name_key("rest")} IN (SELECT name_key FROM known_names)
    )
SELECT area_key, name, rest, prefix,
       if(confirmed_agent, 'confirmed_agent', 'person_prefix'), sales, now64(3), sale_keys
FROM (
    SELECT * FROM judged WHERE confirmed_agent OR person_prefix
    ORDER BY area_key, name, k
    LIMIT 1 BY area_key, name
)
WHERE (area_key, name) NOT IN (SELECT area_key, raw_building_name FROM {REPAIRS_TABLE})
"""


def latest_repairs() -> str:
    return f"""(
        SELECT * FROM {REPAIRS_TABLE}
        ORDER BY area_key, raw_building_name, built_at DESC
        LIMIT 1 BY area_key, raw_building_name
    )"""


# A repair in force: every one a review did not undo.
APPLIED_SQL = f"""(
    SELECT area_key, raw_building_name, building_name FROM {latest_repairs()}
    WHERE building_name != raw_building_name
)"""
# Raw names a review kept, with the sales an earlier repair changed and the clean name it gave
# them.
KEPT_SQL = f"""(
    SELECT arrayJoin(sale_keys) AS sale_key, raw_building_name,
           trimBoth(substring(raw_building_name, length(removed_prefix) + 1)) AS repaired_name
    FROM {latest_repairs()}
    WHERE building_name = raw_building_name AND notEmpty(sale_keys)
)"""
# Raw names that are not to be served or learned as aliases (all but the ones a review kept).
UNSERVED_NAMES_SQL = f"""
SELECT raw_building_name FROM {latest_repairs()} WHERE building_name != raw_building_name
"""


def _latest_sales() -> str:
    return f"""(
    SELECT * FROM {SALES_TABLE} FINAL ORDER BY sale_key, loaded_at DESC LIMIT 1 BY sale_key
)"""


def _rewrite(columns: list[str], name: str) -> str:
    return ", ".join(
        name
        if column == "building_name"
        else location_key_sql(name)
        if column == "building_key"
        else "now64(3)"
        if column == "loaded_at"
        else f"s.{column}"
        for column in columns
    )


def apply_repairs_sql(columns: list[str]) -> str:
    """Insert each affected sale again under its clean building name (a newer load)."""
    return f"""
INSERT INTO {SALES_TABLE} ({", ".join(columns)})
SELECT {_rewrite(columns, "r.building_name")}
FROM {_latest_sales()} AS s
INNER JOIN {APPLIED_SQL} AS r
    ON r.raw_building_name = s.building_name AND r.area_key = lowerUTF8(s.area_name)
"""


DELETE_REPAIRED_SQL = f"""
ALTER TABLE {SALES_TABLE}
DELETE WHERE (lowerUTF8(area_name), building_name) IN (
    SELECT area_key, raw_building_name FROM {APPLIED_SQL}
)
SETTINGS mutations_sync = 2
"""


def restore_kept_sql(columns: list[str]) -> str:
    """Give the sales an earlier repair changed their raw name back (a newer load)."""
    return f"""
INSERT INTO {SALES_TABLE} ({", ".join(columns)})
SELECT {_rewrite(columns, "k.raw_building_name")}
FROM {_latest_sales()} AS s
INNER JOIN {KEPT_SQL} AS k ON k.sale_key = s.sale_key
WHERE s.building_name = k.repaired_name
"""


DELETE_RESTORED_SQL = f"""
ALTER TABLE {SALES_TABLE}
DELETE WHERE (sale_key, building_name) IN (SELECT sale_key, repaired_name FROM {KEPT_SQL})
SETTINGS mutations_sync = 2
"""


def _count(client: Any, sql: str) -> int:
    return int(client.query(sql).result_rows[0][0])


def _columns(client: Any, table: str) -> list[str]:
    return [
        str(row[0])
        for row in client.query(
            "SELECT name FROM system.columns WHERE database = currentDatabase() "
            f"AND table = '{table}' ORDER BY position"
        ).result_rows
    ]


def repair_agent_names(client: Any) -> dict[str, int]:
    """Find new agent-prefixed building names, then rewrite (or restore) the sales."""
    client.command(CREATE_REPAIRS_SQL)
    for statement in ADD_COLUMNS_SQL:
        client.command(statement)
    before = _count(client, f"SELECT count() FROM {REPAIRS_TABLE}")
    client.command(FIND_REPAIRS_SQL)
    client.command(FIND_RARE_REPAIRS_SQL)
    new_names = _count(client, f"SELECT count() FROM {REPAIRS_TABLE}") - before
    affected = _count(
        client,
        f"""SELECT count() FROM {SALES_TABLE}
        WHERE (lowerUTF8(area_name), building_name) IN (
            SELECT area_key, raw_building_name FROM {APPLIED_SQL})""",
    )
    columns = _columns(client, SALES_TABLE)
    if affected:
        client.command(apply_repairs_sql(columns))
        client.command(DELETE_REPAIRED_SQL)
    restored = _count(
        client,
        f"""SELECT count() FROM {_latest_sales()} AS s
        INNER JOIN {KEPT_SQL} AS k ON k.sale_key = s.sale_key
        WHERE s.building_name = k.repaired_name""",
    )
    if restored:
        client.command(restore_kept_sql(columns))
        client.command(DELETE_RESTORED_SQL)
    return {
        "new_names": new_names,
        "rows_rewritten": affected,
        "rows_restored": restored,
        "location_members_rekeyed": _rekey_location_members(client),
    }


def _rekey_location_members(client: Any) -> int:
    """DXBI's location-list members carry the sale's building key: follow the sale's name."""
    exists = client.query(
        "SELECT count() FROM system.tables WHERE database = currentDatabase() "
        "AND name = 'dxbi_location_members'"
    ).result_rows[0][0]
    if not exists:
        return 0
    stale = f"""(
        m.building_key != s.building_key
        AND (m.building_key IN (SELECT {location_key_sql("raw_building_name")} FROM {APPLIED_SQL})
             OR m.sale_key IN (SELECT sale_key FROM {KEPT_SQL}))
    )"""
    joined = f"""dxbi_location_members AS m
        INNER JOIN (SELECT sale_key, building_key FROM {_latest_sales()}) AS s
            ON s.sale_key = m.sale_key"""
    moved = _count(client, f"SELECT count() FROM {joined} WHERE {stale}")
    if not moved:
        return 0
    columns = _columns(client, "dxbi_location_members")
    select = ", ".join(
        "s.building_key" if column == "building_key" else f"m.{column}" for column in columns
    )
    client.command(
        f"INSERT INTO dxbi_location_members ({', '.join(columns)}) "
        f"SELECT {select} FROM {joined} WHERE {stale}"
    )
    client.command(
        f"""ALTER TABLE dxbi_location_members
        DELETE WHERE (sale_key, building_key) NOT IN (
            SELECT sale_key, building_key FROM {_latest_sales()}
        ) AND (building_key IN (SELECT {location_key_sql("raw_building_name")} FROM {APPLIED_SQL})
               OR sale_key IN (SELECT sale_key FROM {KEPT_SQL}))
        SETTINGS mutations_sync = 2"""
    )
    return moved
