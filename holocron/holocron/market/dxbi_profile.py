"""One complete profile per DXBI sale and per DXBI lease.

DXBI is the row source the product shows; DLD is the official register. Each profile carries the
location chain Area -> Master Project -> Project -> Building -> Unit, the property type, the
bedrooms and (for sales) whether the unit was sold off-plan or ready, with the source of every
value in a ``*_source`` column, so a reader can tell a DXBI value from a DLD fill.

Evidence, strongest first:

* ``dld_pair``: the DLD registration paired one-to-one with the DXBI row (market_*_matches).
* ``dld_evidence`` (sales): an unpaired DXBI sale's best DLD registration within a dirham, three
  days and 1% of floor area. It may also be another DXBI row's pair (DXBI lists some sales twice);
  location and status are shared by both, so the values still apply.
* ``building``: what the paired sales of the same DXBI building agree on (>= 60% of >= 2).
* ``project``: the master project DLD gives a project elsewhere (its other registrations and
  the projects register).
* ``dxbi_sale`` (leases): the DXBI sale of the same unit (DLD area, unit number and floor area,
  one building only), which always names its building.
* ``dld_unit`` (leases): the DLD unit register entry with the same area, unit number and floor
  area. Areas without a DLD project (Al Barsha 1, Karama, ...) have no building names in any
  DLD source; the profile then carries DLD's building reference (land / building number).
* ``dxbi``: DXBI's own value.

Values are never invented: a field no source supports stays empty with source ``none``, and
fields that do not apply (bedrooms of an office) are ``not_applicable``.

Built by ``scripts/build_dxbi_profiles.py`` after the market releases; each table is rebuilt in
a staging table and swapped in with EXCHANGE TABLES.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from holocron.market import transforms as t
from holocron.platform.clickhouse_schema import schema_sql_path
from holocron.sources.dxbi.sales_units import location_key_sql

PROFILE_TABLES = ("dxbi_sale_profile", "dxbi_rental_profile")

# Each table's columns, in order; the builds select them by name.
SALE_PROFILE_COLUMNS = (
    "sale_key",
    "transaction_date",
    "area_name",
    "area_source",
    "master_project",
    "master_project_source",
    "project_name",
    "project_source",
    "building_name",
    "building_source",
    "unit_number",
    "unit_source",
    "property_type",
    "bedrooms",
    "bedrooms_source",
    "completion_status",
    "completion_source",
    "dld_link",
    "dld_transaction_key",
    "size_sqft",
    "size_source",
    "location",
    "latitude",
    "longitude",
    "map_url",
    "built_at",
)
RENTAL_PROFILE_COLUMNS = (
    "contract_key",
    "lease_start",
    "area_name",
    "area_source",
    "master_project",
    "master_project_source",
    "project_name",
    "project_source",
    "building_name",
    "building_source",
    "dld_building_ref",
    "floor",
    "unit_number",
    "unit_source",
    "property_type",
    "property_type_source",
    "bedrooms",
    "bedrooms_source",
    "completion_status",
    "completion_source",
    "dld_link",
    "size_sqft",
    "size_source",
    "location",
    "latitude",
    "longitude",
    "map_url",
    "built_at",
)

# Property types that have a bedroom count, in DXBI's words.
RESIDENTIAL_TYPES = ("Apartment", "Villa", "Townhouse", "Hotel Apartment", "Penthouse", "Duplex")


def _bedrooms_from_dld(expr: str) -> str:
    """DLD's room text in DXBI's words: "1 B/R", "1bed room+Hall" -> "1 Bed"; studios kept."""
    low = f"lowerUTF8(trimBoth({expr}))"
    return f"""multiIf(
        {low} IN ('studio', 'single room'), 'Studio',
        match({low}, '^[0-9]+ ?(b/r|bed)'), concat(extract({low}, '^([0-9]+)'), ' Bed'),
        '')"""


def _completion(offplan_en: str, reg_type_en: str) -> str:
    return f"""multiIf(
        {offplan_en} = 'Off-Plan', 'Off-Plan',
        {offplan_en} = 'Ready', 'Ready',
        {reg_type_en} = 'Off-Plan Properties', 'Off-Plan',
        {reg_type_en} = 'Existing Properties', 'Ready',
        '')"""


def _norm(expr: str) -> str:
    return f"lowerUTF8(trimBoth({expr}))"


# Project -> master project wherever DLD states both: its registrations, the projects register
# and the unit register. The most frequent master wins.
_PROJECT_MASTER = """
    project_master AS (
        SELECT project_key, argMax(master, n) AS master
        FROM (
            SELECT project_key, master, sum(n) AS n FROM (
                SELECT lowerUTF8(trimBoth(project_en)) AS project_key,
                       trimBoth(master_project_en) AS master, count() AS n
                FROM dld_od_transactions_bronze
                WHERE project_en != '' AND master_project_en != ''
                GROUP BY project_key, master
                UNION ALL
                SELECT lowerUTF8(trimBoth(project_en)), trimBoth(master_project_en), count()
                FROM dld_od_projects_bronze
                WHERE project_en != '' AND master_project_en != ''
                GROUP BY 1, 2
                UNION ALL
                SELECT lowerUTF8(trimBoth(project_en)), trimBoth(master_project_en), count()
                FROM dld_od_units_bronze
                WHERE project_en != '' AND master_project_en != ''
                GROUP BY 1, 2
            )
            GROUP BY project_key, master
        )
        GROUP BY project_key
    )"""


def _building_directory(*, source: str) -> str:
    """Per DXBI building (name + area), the DLD value its paired sales agree on."""
    return f"""
    building_votes AS (
        SELECT building_key, field, value, count() AS n
        FROM {source}
        ARRAY JOIN ['area', 'project', 'master'] AS field,
                   [ref_area, ref_project, ref_master] AS value
        WHERE ref_kind = 'dld_pair' AND value != ''
        GROUP BY building_key, field, value
    ),
    building_dir AS (
        SELECT building_key,
               argMaxIf(value, n, field = 'area') AS area,
               maxIf(n, field = 'area') / greatest(sumIf(n, field = 'area'), 1) AS area_share,
               sumIf(n, field = 'area') AS area_n,
               argMaxIf(value, n, field = 'project') AS project,
               maxIf(n, field = 'project') / greatest(sumIf(n, field = 'project'), 1)
                   AS project_share,
               sumIf(n, field = 'project') AS project_n,
               argMaxIf(value, n, field = 'master') AS master,
               maxIf(n, field = 'master') / greatest(sumIf(n, field = 'master'), 1) AS master_share,
               sumIf(n, field = 'master') AS master_n
        FROM building_votes
        GROUP BY building_key
    )"""


_SALE_RESOLVED = f"""
WITH
    {t._SALE_MATCH_INPUTS},
    {_PROJECT_MASTER},
    {t._RENTAL_AREA_CTES},
    dld_rows AS (
        SELECT line_id AS dld_key, area_en, project_en, master_project_en, building_name_en,
               rooms_en, is_offplan_en, reg_type_en, procedure_area
        FROM ({t.DLD_SALES_BASE})
        WHERE group_en = 'Sales'
    ),
    paired AS (
        SELECT dxbi_sale_key AS sale_key, dld_transaction_number AS dld_key, 'dld_pair' AS kind
        FROM market_sale_matches
        WHERE dld_transaction_number != ''
    ),
    evidence AS (
        SELECT sale_key, dld_key, 'dld_evidence' AS kind
        FROM same_price
        WHERE day_gap <= 3 AND size_gap <= 0.01
          AND sale_key NOT IN (SELECT sale_key FROM paired)
        ORDER BY sale_key, price_gap, day_gap, size_gap, dld_key
        LIMIT 1 BY sale_key
    ),
    refs AS (SELECT * FROM paired UNION ALL SELECT * FROM evidence),
    base AS (
        SELECT x.sale_key AS sale_key, x.transaction_date AS transaction_date,
               x.building_name AS building_name, x.project_name AS dxbi_project,
               x.area_name AS dxbi_area, x.unit_number AS unit_number,
               x.property_type AS property_type, x.bedrooms AS dxbi_bedrooms,
               x.market_status AS market_status, toUInt32(round(x.size_sqft)) AS size_key,
               concat({_norm("x.building_name")}, '|', x.area_key) AS building_key,
               if(r.kind != '', r.kind, 'none') AS ref_kind, r.dld_key AS ref_key,
               trimBoth(d.area_en) AS ref_area, trimBoth(d.project_en) AS ref_project,
               trimBoth(d.master_project_en) AS ref_master,
               trimBoth(d.building_name_en) AS ref_building,
               {_bedrooms_from_dld("d.rooms_en")} AS ref_bedrooms,
               x.size_sqft AS dxbi_size, d.procedure_area * {t.SQFT_PER_SQM} AS ref_size,
               {_completion("d.is_offplan_en", "d.reg_type_en")} AS ref_completion
        FROM ({t.DXBI_SALES_BASE}) AS x
        LEFT JOIN refs AS r ON r.sale_key = x.sale_key
        LEFT JOIN dld_rows AS d ON d.dld_key = r.dld_key
    ),
    {_building_directory(source="base")},
    -- The same unit's bedrooms as its other DXBI sales give them.
    unit_beds AS (
        SELECT building_key, upperUTF8(trimBoth(unit_number)) AS unit_key,
               argMax(dxbi_bedrooms, transaction_date) AS bedrooms
        FROM base
        WHERE unit_number != '' AND dxbi_bedrooms != ''
        GROUP BY building_key, unit_key
    ),
    -- A home type: the bedrooms >= 80% of the building's other DXBI sales of the same size have.
    type_beds AS (
        SELECT building_key, size_key, argMax(dxbi_bedrooms, n) AS bedrooms
        FROM (
            SELECT building_key, size_key, dxbi_bedrooms, count() AS n
            FROM base
            WHERE dxbi_bedrooms != '' AND size_key > 0
            GROUP BY building_key, size_key, dxbi_bedrooms
        )
        GROUP BY building_key, size_key
        HAVING max(n) / sum(n) >= 0.8 AND sum(n) >= 2
    ),
    resolved AS (
        SELECT b.sale_key AS sale_key, b.transaction_date AS transaction_date, b.building_name AS building_name, b.dxbi_project AS dxbi_project, b.dxbi_area AS dxbi_area, b.unit_number AS unit_number, b.property_type AS property_type, b.dxbi_bedrooms AS dxbi_bedrooms, b.market_status AS market_status, b.size_key AS size_key, b.building_key AS building_key, b.ref_kind AS ref_kind, b.ref_key AS ref_key, b.ref_area AS ref_area, b.ref_project AS ref_project, b.ref_master AS ref_master, b.ref_building AS ref_building, b.ref_bedrooms AS ref_bedrooms, b.ref_completion AS ref_completion, b.dxbi_size AS dxbi_size, b.ref_size AS ref_size,
               multiIf(b.ref_area != '', b.ref_area,
                       bd.area_share >= 0.6 AND bd.area_n >= 2, bd.area,
                       sm.dld_area != '', sm.dld_area, b.dxbi_area) AS area_name,
               multiIf(b.ref_area != '', b.ref_kind,
                       bd.area_share >= 0.6 AND bd.area_n >= 2, 'building',
                       sm.dld_area != '', 'area_map', b.dxbi_area != '', 'dxbi', 'none')
                   AS area_source,
               multiIf(b.ref_project != '', b.ref_project,
                       bd.project_share >= 0.6 AND bd.project_n >= 2, bd.project,
                       b.dxbi_project) AS project_name,
               multiIf(b.ref_project != '', b.ref_kind,
                       bd.project_share >= 0.6 AND bd.project_n >= 2, 'building',
                       b.dxbi_project != '', 'dxbi', 'none') AS project_source
        FROM base AS b
        LEFT JOIN building_dir AS bd ON bd.building_key = b.building_key
        LEFT JOIN sales_area_map AS sm ON sm.dxbi_area = b.dxbi_area
    )
SELECT
    r.sale_key,
    r.transaction_date,
    r.area_name,
    r.area_source,
    multiIf(r.ref_master != '', r.ref_master,
            pm.master != '', pm.master,
            bd.master_share >= 0.6 AND bd.master_n >= 2, bd.master, '') AS master_project,
    multiIf(r.ref_master != '', r.ref_kind,
            pm.master != '', 'project',
            bd.master_share >= 0.6 AND bd.master_n >= 2, 'building', 'none')
        AS master_project_source,
    r.project_name,
    r.project_source,
    if(r.building_name != '', r.building_name, r.ref_building) AS building_name,
    multiIf(r.building_name != '', 'dxbi', r.ref_building != '', r.ref_kind, 'none')
        AS building_source,
    r.unit_number,
    if(r.unit_number != '', 'dxbi', 'none') AS unit_source,
    r.property_type,
    multiIf(r.property_type NOT IN {RESIDENTIAL_TYPES}, '',
            r.dxbi_bedrooms != '', r.dxbi_bedrooms,
            r.ref_bedrooms != '', r.ref_bedrooms,
            ub.bedrooms != '', ub.bedrooms,
            tb.bedrooms != '', tb.bedrooms, '') AS bedrooms,
    multiIf(r.property_type NOT IN {RESIDENTIAL_TYPES}, 'not_applicable',
            r.dxbi_bedrooms != '', 'dxbi',
            r.ref_bedrooms != '', r.ref_kind,
            ub.bedrooms != '', 'dxbi_unit',
            tb.bedrooms != '', 'same_type', 'none') AS bedrooms_source,
    multiIf(r.ref_completion != '', r.ref_completion,
            r.market_status = 'Offplan', 'Off-Plan',
            r.market_status = 'Ready', 'Ready', '') AS completion_status,
    multiIf(r.ref_completion != '', r.ref_kind,
            r.market_status IN ('Offplan', 'Ready'), 'dxbi', 'none') AS completion_source,
    r.ref_kind AS dld_link,
    r.ref_key AS dld_transaction_key,
    r.dxbi_project AS dxbi_project,
    r.dxbi_area AS dxbi_community,
    '' AS dld_building_ref,
    multiIf(r.dxbi_size > 0, r.dxbi_size, r.ref_size > 0, r.ref_size, 0) AS size_sqft,
    multiIf(r.dxbi_size > 0, 'dxbi', r.ref_size > 0, r.ref_kind, 'none') AS size_source
FROM resolved AS r
LEFT JOIN project_master AS pm ON pm.project_key = {_norm("r.project_name")}
LEFT JOIN building_dir AS bd ON bd.building_key = r.building_key
LEFT JOIN unit_beds AS ub
    ON ub.building_key = r.building_key AND ub.unit_key = upperUTF8(trimBoth(r.unit_number))
LEFT JOIN type_beds AS tb ON tb.building_key = r.building_key AND tb.size_key = r.size_key
"""


# A lease DXBI lists only as "Commercial" takes the type its matched DLD contract records, in
# DXBI's own words (the names DXBI's sales use), so a tower's leases and sales line up as Office,
# Shop or Warehouse. Only exact equivalents map; any other DLD type, or one that contradicts DXBI
# (a "Flat"), leaves the lease "Commercial".
DLD_COMMERCIAL_TYPES = {
    "Office": ("office",),
    "Shop": ("shop", "shop with a mezzanine", "kiosk"),
    "Show Rooms": ("showroom", "showroom with mezzanine"),
    "Warehouse": ("warehouse", "warehouse complex", "complex warehouse", "store", "storage"),
    "Workshop": ("workshop",),
    "Clinic": ("clinic",),
    "Hotel": ("hotel",),
    "Gymnasium": ("gym", "health club"),
}


def _dld_commercial_type(alias: str) -> str:
    label = (
        f"lowerUTF8(trimBoth(if({alias}.prop_sub_type_en != '', {alias}.prop_sub_type_en, "
        f"{alias}.prop_type_en)))"
    )
    branches = ", ".join(
        f"{label} IN ({', '.join(repr(name) for name in names)}), '{dxbi}'"
        for dxbi, names in DLD_COMMERCIAL_TYPES.items()
    )
    return f"multiIf({branches}, '')"


_RENTAL_RESOLVED = f"""
WITH
    {t._RENTAL_AREA_CTES},
    {_PROJECT_MASTER},
    dld_rows AS (
        SELECT dld_rent_key, area_en, project_en, master_project_en, rooms, actual_area,
               prop_type_en, prop_sub_type_en
        FROM ({t._DLD_RENTS_MATCH_BASE})
        WHERE dld_rent_key IN (
            SELECT dld_rent_key FROM market_rental_matches WHERE dld_rent_key != 0)
    ),
    lease AS (
        SELECT r.contract_key AS contract_key, r.lease_start AS lease_start,
               r.building_name AS building_name, r.project_name AS dxbi_project,
               r.area_name AS dxbi_area, r.unit_number AS unit_number,
               r.property_type AS property_type, r.bedrooms AS dxbi_bedrooms,
               r.size_sqft AS size_sqft,
               trimBoth(arrayElement(splitByChar(',', r.location_name), -1)) AS registry_text,
               {t._RENTAL_DLD_AREA} AS mapped_area,
               multiIf(rp.dld_area != '', 'dxbi_registry', sm.dld_area != '', 'area_map',
                  n.dld_area != '', 'dxbi', 'none') AS mapped_area_source
        FROM dxbi_rental_events AS r FINAL
        {t._rental_area_joins("r")}
    ),
    base AS (
        SELECT l.contract_key AS contract_key, l.lease_start AS lease_start, l.building_name AS building_name, l.dxbi_project AS dxbi_project, l.dxbi_area AS dxbi_area, l.unit_number AS unit_number, l.property_type AS property_type, l.dxbi_bedrooms AS dxbi_bedrooms, l.size_sqft AS size_sqft, l.mapped_area AS mapped_area, l.mapped_area_source AS mapped_area_source,
               l.registry_text AS registry_text,
               if(m.dld_rent_key != 0, 'dld_pair', 'none') AS ref_kind,
               trimBoth(d.area_en) AS ref_area, trimBoth(d.project_en) AS ref_project,
               trimBoth(d.master_project_en) AS ref_master,
               multiIf(match(trimBoth(d.rooms), '^[0-9]+$') AND toUInt32OrZero(d.rooms) > 0,
                       concat(trimBoth(d.rooms), ' Bed'), '') AS ref_bedrooms,
               -- DXBI's own area text when no DLD spelling matches it ("Al Qusais First").
               multiIf(d.area_en != '', trimBoth(d.area_en), l.mapped_area != '', l.mapped_area,
                       l.registry_text != '', l.registry_text, l.dxbi_area) AS dld_area,
               d.actual_area * {t.SQFT_PER_SQM} AS ref_size,
               {_dld_commercial_type("d")} AS ref_type,
               upperUTF8(trimBoth(l.unit_number)) AS unit_key,
               toUInt32(round(l.size_sqft)) AS size_key
        FROM lease AS l
        LEFT JOIN market_rental_matches AS m ON m.dxbi_contract_key = l.contract_key
        LEFT JOIN dld_rows AS d ON d.dld_rent_key = m.dld_rent_key
    ),
    -- DXBI sales by unit: one building only for (DLD area, unit number, floor area).
    sale_units AS (
        SELECT lowerUTF8(p.area_name) AS area_key, upperUTF8(trimBoth(p.unit_number)) AS unit_key,
               toUInt32(round(x.size_sqft)) AS size_key,
               uniqExact(lowerUTF8(p.building_name)) AS buildings,
               any(p.building_name) AS s_building, any(p.project_name) AS s_project,
               any(p.master_project) AS s_master,
               argMax(p.bedrooms, p.transaction_date) AS s_bedrooms
        FROM dxbi_sale_profile AS p
        INNER JOIN (SELECT sale_key, size_sqft FROM ({t.DXBI_SALES_BASE})) AS x
            ON x.sale_key = p.sale_key
        WHERE p.unit_number != '' AND p.area_name != '' AND p.building_name != ''
        GROUP BY area_key, unit_key, size_key
        HAVING buildings = 1
    ),
    -- DLD's unit register: one entry for (area, unit number, floor area).
    dld_units AS (
        SELECT lowerUTF8(trimBoth(area_en)) AS area_key,
               upperUTF8(trimBoth(unit_number)) AS unit_key,
               toUInt32(round(actual_area * {t.SQFT_PER_SQM})) AS size_key,
               uniqExact(land_number, building_number) AS places,
               any(trimBoth(project_en)) AS u_project,
               any(trimBoth(master_project_en)) AS u_master,
               any(land_number) AS u_land, any(building_number) AS u_building,
               any(floor) AS u_floor, any(rooms_en) AS u_rooms
        FROM dld_od_units_bronze
        WHERE unit_number != '' AND actual_area > 0
        GROUP BY area_key, unit_key, size_key
        HAVING places = 1
    ),
    -- Failing the floor area, a unit number DLD holds once in the area (126k more leases).
    dld_units_by_number AS (
        SELECT lowerUTF8(trimBoth(area_en)) AS area_key,
               upperUTF8(trimBoth(unit_number)) AS unit_key,
               uniqExact(land_number, building_number) AS places,
               any(trimBoth(project_en)) AS n_project,
               any(trimBoth(master_project_en)) AS n_master,
               any(land_number) AS n_land, any(building_number) AS n_building,
               any(floor) AS n_floor, any(rooms_en) AS n_rooms,
               any(actual_area) AS n_area
        FROM dld_od_units_bronze
        WHERE unit_number != ''
        GROUP BY area_key, unit_key
        HAVING places = 1
    ),
    -- A home type: the bedrooms >= 80% of the building's other DXBI leases of the same size have.
    lease_type_beds AS (
        SELECT building_key, size_key, argMax(dxbi_bedrooms, n) AS bedrooms
        FROM (
            SELECT concat(lowerUTF8(building_name), '|', lowerUTF8(dld_area)) AS building_key,
                   size_key, dxbi_bedrooms, count() AS n
            FROM base
            WHERE building_name != '' AND dxbi_bedrooms != '' AND size_key > 0
            GROUP BY building_key, size_key, dxbi_bedrooms
        )
        GROUP BY building_key, size_key
        HAVING max(n) / sum(n) >= 0.8 AND sum(n) >= 2
    ),
    -- DLD's buildings register: the project and master project of a land / building number.
    dld_building_projects AS (
        SELECT land_number AS b_land, building_number AS b_building,
               any(trimBoth(project_en)) AS b_project,
               any(trimBoth(master_project_en)) AS b_master
        FROM dld_od_buildings_bronze
        WHERE project_en != '' OR master_project_en != ''
        GROUP BY land_number, building_number
    ),
    -- What the leases of one DXBI building agree on (leases that name their building).
    lease_building_votes AS (
        SELECT concat(lowerUTF8(building_name), '|', lowerUTF8(dld_area)) AS building_key,
               field, value, count() AS n
        FROM base
        ARRAY JOIN ['project', 'master'] AS field, [ref_project, ref_master] AS value
        WHERE building_name != '' AND ref_kind = 'dld_pair' AND value != ''
        GROUP BY building_key, field, value
    ),
    lease_building_dir AS (
        SELECT building_key,
               argMaxIf(value, n, field = 'project') AS project,
               maxIf(n, field = 'project') / greatest(sumIf(n, field = 'project'), 1)
                   AS project_share,
               sumIf(n, field = 'project') AS project_n,
               argMaxIf(value, n, field = 'master') AS master,
               maxIf(n, field = 'master') / greatest(sumIf(n, field = 'master'), 1) AS master_share,
               sumIf(n, field = 'master') AS master_n
        FROM lease_building_votes
        GROUP BY building_key
    ),
    resolved AS (
        SELECT b.contract_key AS contract_key, b.lease_start AS lease_start, b.building_name AS building_name, b.dxbi_project AS dxbi_project, b.dxbi_area AS dxbi_area, b.unit_number AS unit_number, b.property_type AS property_type, b.dxbi_bedrooms AS dxbi_bedrooms, b.size_sqft AS size_sqft, b.mapped_area AS mapped_area, b.mapped_area_source AS mapped_area_source, b.ref_kind AS ref_kind, b.ref_area AS ref_area, b.ref_project AS ref_project, b.ref_master AS ref_master, b.ref_bedrooms AS ref_bedrooms, b.dld_area AS dld_area, b.unit_key AS unit_key, b.size_key AS size_key, b.ref_size AS ref_size, b.ref_type AS ref_type,
               su.s_building AS sale_building, su.s_project AS sale_project,
               su.s_master AS sale_master, su.s_bedrooms AS sale_bedrooms,
               multiIf(du.u_land != '' AND du.u_project != '', du.u_project,
                       du.u_land = '' AND dn.n_project != '', dn.n_project, bp.b_project) AS unit_project,
               multiIf(du.u_land != '' AND du.u_master != '', du.u_master,
                       du.u_land = '' AND dn.n_master != '', dn.n_master, bp.b_master) AS unit_master,
               if(du.u_land != '', du.u_land, dn.n_land) AS land_number,
               if(du.u_land != '', du.u_building, dn.n_building) AS building_number,
               if(du.u_land != '', du.u_floor, dn.n_floor) AS floor,
               dn.n_area * {t.SQFT_PER_SQM} AS unit_size, {_bedrooms_from_dld("if(du.u_land != '', du.u_rooms, dn.n_rooms)")} AS unit_bedrooms,
               if(b.building_name != '', b.building_name, su.s_building) AS building_resolved,
               tb.bedrooms AS type_bedrooms,
               bd.project AS dir_project, bd.project_share >= 0.6 AND bd.project_n >= 2 AS dir_project_ok,
               bd.master AS dir_master, bd.master_share >= 0.6 AND bd.master_n >= 2 AS dir_master_ok
        FROM base AS b
        LEFT JOIN sale_units AS su
            ON su.area_key = lowerUTF8(b.dld_area) AND su.unit_key = b.unit_key
           AND su.size_key = b.size_key AND b.unit_key NOT IN ('', '0')
        LEFT JOIN dld_units AS du
            ON du.area_key = lowerUTF8(b.dld_area) AND du.unit_key = b.unit_key
           AND du.size_key = b.size_key AND b.unit_key NOT IN ('', '0')
        LEFT JOIN dld_units_by_number AS dn
            ON dn.area_key = lowerUTF8(b.dld_area) AND dn.unit_key = b.unit_key
           AND b.unit_key NOT IN ('', '0')
        LEFT JOIN lease_type_beds AS tb
            ON tb.building_key = concat(lowerUTF8(b.building_name), '|', lowerUTF8(b.dld_area))
           AND tb.size_key = b.size_key AND b.building_name != ''
        LEFT JOIN dld_building_projects AS bp
            ON bp.b_land = if(du.u_land != '', du.u_land, dn.n_land)
           AND bp.b_building = if(du.u_land != '', du.u_building, dn.n_building)
        LEFT JOIN lease_building_dir AS bd
            ON bd.building_key = concat(lowerUTF8(b.building_name), '|', lowerUTF8(b.dld_area))
           AND b.building_name != ''
    ),
    projected AS (
        SELECT r.*,
               multiIf(r.ref_project != '', r.ref_project, r.sale_project != '', r.sale_project,
                       r.unit_project != '', r.unit_project, r.dir_project_ok, r.dir_project,
                       r.dxbi_project) AS project_name,
               multiIf(r.ref_project != '', 'dld_pair', r.sale_project != '', 'dxbi_sale',
                       r.unit_project != '', 'dld_unit', r.dir_project_ok, 'building',
                       r.dxbi_project != '', 'dxbi', 'none') AS project_source
        FROM resolved AS r
    )
SELECT
    p.contract_key,
    p.lease_start,
    p.dld_area AS area_name,
    multiIf(p.ref_area != '', 'dld_pair', p.mapped_area != '', p.mapped_area_source,
            p.dld_area != '', 'dxbi', 'none') AS area_source,
    multiIf(p.ref_master != '', p.ref_master, pm.master != '', pm.master,
            p.sale_master != '', p.sale_master, p.unit_master != '', p.unit_master,
            p.dir_master_ok, p.dir_master, '') AS master_project,
    multiIf(p.ref_master != '', 'dld_pair', pm.master != '', 'project',
            p.sale_master != '', 'dxbi_sale', p.unit_master != '', 'dld_unit',
            p.dir_master_ok, 'building', 'none') AS master_project_source,
    p.project_name,
    p.project_source,
    p.building_resolved AS building_name,
    multiIf(p.building_name != '', 'dxbi', p.sale_building != '', 'dxbi_sale', 'none')
        AS building_source,
    -- DLD's own reference for the building when no source names it (areas without projects).
    if(p.land_number != '', concat(p.land_number,
                                   if(p.building_number NOT IN ('', '0'),
                                      concat(' / ', p.building_number), '')), '')
        
        AS dld_building_ref,
    p.floor AS floor,
    p.unit_number,
    if(p.unit_key NOT IN ('', '0'), 'dxbi', 'none') AS unit_source,
    if(p.property_type = 'Commercial' AND p.ref_type != '', p.ref_type, p.property_type)
        AS property_type,
    multiIf(p.property_type = 'Commercial' AND p.ref_type != '', 'dld_pair',
            p.property_type != '', 'dxbi', 'none') AS property_type_source,
    multiIf(p.property_type NOT IN {RESIDENTIAL_TYPES}, '',
            p.dxbi_bedrooms != '', p.dxbi_bedrooms, p.sale_bedrooms != '', p.sale_bedrooms,
            p.unit_bedrooms != '', p.unit_bedrooms, p.ref_bedrooms != '', p.ref_bedrooms,
            p.type_bedrooms != '', p.type_bedrooms, '')
        AS bedrooms,
    multiIf(p.property_type NOT IN {RESIDENTIAL_TYPES}, 'not_applicable',
            p.dxbi_bedrooms != '', 'dxbi', p.sale_bedrooms != '', 'dxbi_sale',
            p.unit_bedrooms != '', 'dld_unit', p.ref_bedrooms != '', 'dld_pair',
            p.type_bedrooms != '', 'same_type', 'none')
        AS bedrooms_source,
    -- A leased unit is a completed unit.
    'Ready' AS completion_status,
    'lease' AS completion_source,
    p.ref_kind AS dld_link,
    p.dxbi_project AS dxbi_project,
    p.dxbi_area AS dxbi_community,
    multiIf(p.size_sqft > 0, p.size_sqft, p.ref_size > 0, p.ref_size,
            p.unit_size > 0, p.unit_size, 0) AS size_sqft,
    multiIf(p.size_sqft > 0, 'dxbi', p.ref_size > 0, 'dld_pair', p.unit_size > 0, 'dld_unit',
            'none') AS size_source
FROM projected AS p
LEFT JOIN project_master AS pm ON pm.project_key = {_norm("p.project_name")}
"""


def _name_key(expr: str) -> str:
    return f"lowerUTF8(replaceRegexpAll({expr}, '[^A-Za-z0-9]', ''))"


# What DLD defines per area: the master project nearly all its units sit in (>= 60% of >= 20),
# and whether the area has projects or master projects at all (>= 5% of its units). Areas DLD
# organises without them (Al Barsha 1, Karama, Al Qusais) have none to show.
_AREA_FACTS = """
    area_facts AS (
        SELECT area_key,
               argMax(master, n) AS dominant_master,
               max(n) / greatest(sum(n), 1) AS dominant_share,
               sum(n) AS master_units,
               max(units) AS units, max(project_units) AS project_units
        FROM (
            SELECT lowerUTF8(trimBoth(area_en)) AS area_key, trimBoth(master_project_en) AS master,
                   count() AS n, 0 AS units, 0 AS project_units
            FROM dld_od_units_bronze WHERE master_project_en != '' GROUP BY area_key, master
            UNION ALL
            SELECT lowerUTF8(trimBoth(area_en)), '', 0, count(), countIf(project_en != '')
            FROM dld_od_units_bronze GROUP BY 1
        )
        GROUP BY area_key
    )"""

# Coordinates: the PropertyFinder tower the building name is an alias of (one tower only), else
# the building's coordinates in DXBI's own building list.
_COORDINATES = """
    tower_points AS (
        SELECT a.normalized_alias AS name_key, uniqExact(n.canonical_location_id) AS towers,
               any(n.latitude) AS lat, any(n.longitude) AS lng
        FROM geo_tower_aliases AS a
        INNER JOIN geo_location_nodes AS n ON n.canonical_location_id = a.canonical_location_id
        WHERE a.active = 1 AND n.location_type = 'TOWER' AND n.latitude != 0
        GROUP BY name_key
        HAVING towers = 1
    ),
    dxbi_points AS (
        SELECT name_key, area_key,
               toFloat64OrZero(splitByChar(',', coordinates)[1]) AS lat,
               toFloat64OrZero(splitByChar(',', coordinates)[2]) AS lng
        FROM (
            SELECT lowerUTF8(replaceRegexpAll(
                       JSONExtractString(payload_json, 'Building', 'location'), '[^A-Za-z0-9]', ''))
                       AS name_key,
                   lowerUTF8(JSONExtractString(payload_json, 'Building', 'area_name')) AS area_key,
                   any(JSONExtractString(payload_json, 'Building', 'building_coordinates'))
                       AS coordinates
            FROM dxbi_heatmap_buildings_bronze
            WHERE JSONExtractString(payload_json, 'Building', 'building_coordinates') != ''
            GROUP BY name_key, area_key
        )
        WHERE lat != 0
    )"""


def _place_key(expr: str) -> str:
    """A place name without DXBI's bracketed short form, in letters and digits ("JVC")."""
    return (
        f"lowerUTF8(replaceRegexpAll(replaceRegexpOne(trimBoth({expr}), "
        f"'\\s*\\([^)]*\\)$', ''), '[^A-Za-z0-9]', ''))"
    )


def _display(expr: str) -> str:
    """DLD writes many names in capitals ("TOWN SQUARE"); show them in title case."""
    return (
        f"if({expr} = upperUTF8({expr}) AND match({expr}, '[A-Z]{{3}}'), "
        f"initcapUTF8(lowerUTF8({expr})), {expr})"
    )


def _location(*parts: str) -> str:
    """The parts that are present, each once (case-insensitively), joined, ending in Dubai."""
    array = "[" + ", ".join(f"trimBoth({part})" for part in parts) + ", 'Dubai']"
    present = f"arrayFilter(x -> x != '', {array})"
    return (
        f"arrayStringConcat(arrayFilter((x, i) -> indexOf(arrayMap(y -> lowerUTF8(y), "
        f"{present}), lowerUTF8(x)) = i, {present}, arrayEnumerate({present})), ', ')"
    )


_UNIT = "if(f.unit_number NOT IN ('', '0'), concat('Unit ', f.unit_number), '')"
# DXBI sometimes cuts a building name inside a bracket ("Cinderella (Living Legends Phase 5"):
# the location text drops the unclosed part.
_PLACES = (
    _display("replaceRegexpOne(f.building_name, '\\s*\\([^)]*$', '')"),
    *(_display(f"f.{column}") for column in ("project_name", "master_project", "area_name")),
)


# Master projects no data source gives, confirmed by a web search (each row cites its page).
# A row applies to a project whose name contains the pattern (letters and digits, lower case),
# in the given DLD area when one is set; an empty pattern covers the whole area.
MASTER_OVERRIDES_CSV = Path(__file__).with_name("data") / "master_project_overrides.csv"


def _sql_text(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _web_master(project: str, area: str) -> str:
    """The first web-verified master whose pattern the project (and area) matches, else ''."""
    with MASTER_OVERRIDES_CSV.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    entries = ", ".join(
        f"({_sql_text(row['project_contains'])}, {_sql_text(row['area'])}, "
        f"{_sql_text(row['master_project'])})"
        for row in rows
    )
    key, area_key = _name_key(project), f"lowerUTF8(trimBoth({area}))"
    return (
        f"tupleElement(arrayFirst(m -> (m.1 = '' OR position({key}, m.1) > 0) "
        f"AND (m.2 = '' OR m.2 = {area_key}), [{entries}]), 3)"
    )


def _finished(*, table: str, columns: tuple[str, ...], resolved: str, key: str, lease: bool) -> str:
    """The resolved profile with every remaining field filled from the next evidence.

    * Master project: DLD's master of the final project, then DXBI's own master community (the
      middle of DXBI's path, "Damac Islands", or its community when that is not the DLD area,
      "Damac Lagoons"), then the master DLD uses for nearly all of the area ("Business Bay").
    * Project: a building no source places in a project is its own DLD project (DLD registers a
      standalone tower, "BAYZ 101 BY DANUBE", as a project; source ``own_building``); a villa or
      plot sold directly in a community is in that community. A "building" that is the name of a
      place DLD or DXBI knows as an area or master project ("Jumeirah Village Circle (JVC)",
      "Mirdif") is not a project (source ``place_name``), nor is a DXBI or DXBI-sale project of
      such a name (a lease copies "Jumeirah Village Circle (JVC)" from its unit's sale).
    * Building (leases): DLD's plot / building number where no source names the building.
    * Master project and project are not applicable in an area DLD defines none in.
    """
    building = (
        "if(s.building_name != '', s.building_name, "
        "if(s.dld_building_ref != '', concat('DLD plot ', s.dld_building_ref), ''))"
    )
    building_source = (
        "multiIf(s.building_name != '', s.building_source, "
        "s.dld_building_ref != '', 'dld_unit_ref', 'none')"
    )
    project_key, building_key = _norm("s.project_name"), _norm("s.building_name")
    dxbi_project, community = _norm("s.dxbi_project"), _norm("s.dxbi_community")
    dxbi_master = f"""multiIf(
            {dxbi_project} != '' AND {dxbi_project} != {project_key}
              AND {dxbi_project} != {building_key}
              AND {t._area_name_key("s.dxbi_project")} NOT IN (SELECT area_key FROM dld_area_keys),
            s.dxbi_project,
            {community} != ''
              AND ngramDistanceUTF8({t._area_name_key("s.dxbi_community")},
                                    lowerUTF8(s.area_name)) > 0.3
              AND {community} != {project_key} AND {community} != {building_key}
              AND {t._area_name_key("s.dxbi_community")} NOT IN (SELECT area_key FROM dld_area_keys),
            s.dxbi_community, '')"""
    # An area DLD named after its community in 2026 (no numeral, not in the unit register).
    renamed_area = (
        f"(s.area_name != '' AND NOT match(lowerUTF8(s.area_name), "
        f"'([0-9]|first|second|third|fourth|fifth|sixth)$') AND "
        f"{t._area_name_key('s.area_name')} NOT IN (SELECT area_key FROM register_area_keys))"
    )
    web_master = _web_master(
        "if(s.project_name != '', s.project_name, s.building_name)", "s.area_name"
    )
    no_projects = "(af.units > 0 AND af.project_units < 0.05 * af.units)"
    no_masters = "(af.units > 0 AND af.master_units < 0.05 * af.units)"
    lease_only = (
        ", s.dld_building_ref AS dld_building_ref, s.floor AS floor"
        ", s.property_type_source AS property_type_source"
        if lease
        else ""
    )
    lease_dld = "" if lease else ", s.dld_transaction_key AS dld_transaction_key"
    date = "lease_start" if lease else "transaction_date"
    return f"""
INSERT INTO `{table}` ({", ".join(columns)})
-- Selected by name, so a missing or misnamed column fails instead of shifting.
SELECT {", ".join(columns)}
FROM (
WITH
    {_PROJECT_MASTER},
    {_AREA_FACTS},
    {_COORDINATES},
    -- Area and master-project names DLD and DXBI use: a DXBI "building" of such a name is a
    -- place, not its own project.
    place_keys AS (
        SELECT DISTINCT {_place_key("n")} AS place_key FROM (
            SELECT arrayJoin([area_en, master_project_en]) AS n FROM dld_od_transactions_bronze
            UNION ALL
            SELECT arrayJoin([area_en, master_project_en]) FROM dld_od_units_bronze
            UNION ALL
            SELECT area_name FROM dxbi_sales_unit_events
            UNION ALL
            SELECT area_label FROM dxbi_places
        )
        WHERE n != ''
    ),
    -- Every DLD area name, as compared with a DXBI name (numerals spelled as DLD writes them).
    dld_area_keys AS (
        SELECT DISTINCT {t._area_name_key("area_en")} AS area_key FROM dld_od_units_bronze
        UNION DISTINCT
        SELECT DISTINCT {t._area_name_key("area_en")} FROM dld_od_transactions_bronze
    ),
    -- DLD's master project names. DLD's 2026 open data renamed areas after communities
    -- ("JUMEIRAH VILLAGE CIRCLE", "MAJAN"): such an area is the master project its older
    -- registrations name.
    dld_masters AS (
        SELECT lowerUTF8(replaceRegexpAll(m, '[^A-Za-z0-9]', '')) AS master_key,
               argMax(m, n) AS master_name
        FROM (
            SELECT trimBoth(master_project_en) AS m, count() AS n FROM dld_od_transactions_bronze
            WHERE master_project_en != '' GROUP BY m
            UNION ALL
            SELECT trimBoth(master_project_en), count() FROM dld_od_units_bronze
            WHERE master_project_en != '' GROUP BY 1
        )
        GROUP BY master_key
    ),
    -- Area names of DLD's unit register (before the 2026 renaming).
    register_area_keys AS (
        SELECT DISTINCT {t._area_name_key("area_en")} AS area_key FROM dld_od_units_bronze
    ),
    -- DXBI community -> DLD area by the matched sales, whatever DXBI's capitalisation.
    community_area AS (
        SELECT community_key, argMax(dld_area, n) AS dld_area
        FROM (
            SELECT lowerUTF8(trimBoth(x.area_name)) AS community_key, e.area_name_en AS dld_area,
                   count() AS n
            FROM market_sale_events AS e
            INNER JOIN (SELECT sale_key, area_name FROM dxbi_sales_unit_events FINAL) AS x
                ON x.sale_key = e.dxbi_sale_key
            WHERE e.match_status = 'matched' AND e.area_name_en != '' AND x.area_name != ''
            GROUP BY community_key, dld_area
        )
        GROUP BY community_key
        HAVING max(n) / sum(n) >= 0.5 AND sum(n) >= 20
    ),
    -- The PropertyFinder community a project or building name is an alias of (one place only).
    pf_communities AS (
        SELECT a.normalized_alias AS name_key, uniqExact(n.canonical_location_id) AS places,
               any(trimBoth(splitByString(', ', n.path_name)[2])) AS community
        FROM geo_tower_aliases AS a
        INNER JOIN geo_location_nodes AS n ON n.canonical_location_id = a.canonical_location_id
        WHERE a.active = 1 AND length(splitByString(', ', n.path_name)) >= 3
        GROUP BY name_key
        HAVING places = 1
    ),
    filled AS (
        SELECT s.{key} AS {key}, s.{date} AS {date},
               if(s.area_source IN ('dxbi', 'none') AND ca.dld_area != '', ca.dld_area,
                  s.area_name) AS area_name,
               if(s.area_source IN ('dxbi', 'none') AND ca.dld_area != '', 'area_map',
                  s.area_source) AS area_source, s.unit_number AS unit_number,
               s.unit_source AS unit_source, s.property_type AS property_type,
               s.bedrooms AS bedrooms, s.bedrooms_source AS bedrooms_source,
               s.size_sqft AS size_sqft, s.size_source AS size_source,
               s.completion_status AS completion_status,
               -- Land has no completion stage.
               if(s.completion_status = '' AND s.property_type IN ('Plot', 'Land'),
                  'not_applicable', s.completion_source) AS completion_source, s.dld_link AS dld_link,
               s.dxbi_community AS dxbi_community{lease_only}{lease_dld},
               {building} AS building_name, {building_source} AS building_source,
               multiIf(s.project_name != '', s.project_name,
                       s.building_name != '', s.building_name, '') AS project_name,
               multiIf(s.project_name != '' AND s.project_source IN ('dxbi', 'dxbi_sale')
                         AND {_place_key("s.project_name")} IN (SELECT place_key FROM place_keys),
                       'place_name',
                       s.project_name != '', s.project_source,
                       {_place_key("s.building_name")} IN (SELECT place_key FROM place_keys),
                       'place_name',
                       s.building_name != '', 'own_building',
                       {no_projects}, 'not_applicable', 'none') AS project_source,
               multiIf(s.master_project != '', s.master_project,
                       pm.master != '', pm.master,
                       {web_master} != '', {web_master},
                       {dxbi_master} != '', {dxbi_master},
                       pc.community != '' AND {_norm("pc.community")} != {project_key}
                         AND {t._area_name_key("pc.community")}
                             NOT IN (SELECT area_key FROM dld_area_keys),
                       pc.community,
                       am.master_name != '', am.master_name,
                       {renamed_area}, s.area_name,
                       af.dominant_share >= 0.6 AND af.master_units >= 20, af.dominant_master,
                       '') AS master_project,
               multiIf(s.master_project != '', s.master_project_source,
                       pm.master != '', 'project',
                       {web_master} != '', 'web_verified',
                       {dxbi_master} != '', 'dxbi_community',
                       pc.community != '' AND {_norm("pc.community")} != {project_key}
                         AND {t._area_name_key("pc.community")}
                             NOT IN (SELECT area_key FROM dld_area_keys),
                       'pf_community',
                       am.master_name != '', 'area_is_master',
                       {renamed_area}, 'area_is_master',
                       af.dominant_share >= 0.6 AND af.master_units >= 20, 'area',
                       {no_masters}, 'not_applicable', 'none') AS master_project_source,
               {_name_key("s.building_name")} AS building_name_key
        FROM ({resolved}) AS s
        LEFT JOIN community_area AS ca ON ca.community_key = lowerUTF8(trimBoth(s.area_name))
        LEFT JOIN area_facts AS af
            ON af.area_key = lowerUTF8(if(s.area_source IN ('dxbi', 'none') AND ca.dld_area != '',
                                          ca.dld_area, s.area_name))
        LEFT JOIN dld_masters AS am ON am.master_key = {_name_key("s.area_name")}
        LEFT JOIN pf_communities AS pc
            ON pc.name_key = {
        _name_key("if(s.project_name != '', s.project_name, s.building_name)")
    }
        LEFT JOIN project_master AS pm
            ON pm.project_key = {
        _norm("multiIf(s.project_name != '', s.project_name, s.building_name)")
    }
    )
SELECT f.* REPLACE (
           -- DLD's own spelling of a master it knows, so Analytics sees one name per master;
           -- any other in title case ("DUBAI SOUTH", an area's capitals, is "Dubai South").
           if(dm.master_name != '', dm.master_name, {_display("f.master_project")})
               AS master_project
       ),
       {_location(_UNIT, *_PLACES)} AS location,
       multiIf(tp.lat != 0, tp.lat, dp.lat != 0, dp.lat, NULL) AS latitude,
       multiIf(tp.lat != 0, tp.lng, dp.lat != 0, dp.lng, NULL) AS longitude,
       -- A located building opens at its point; otherwise Maps searches the place's name.
       if(latitude IS NOT NULL,
          concat('https://www.google.com/maps/search/?api=1&query=',
                 toString(latitude), '%2C', toString(longitude)),
          concat('https://www.google.com/maps/search/?api=1&query=',
                 encodeURLComponent({_location(*_PLACES)})))
           AS map_url,
       now64(3) AS built_at
FROM filled AS f
LEFT JOIN dld_masters AS dm ON dm.master_key = {_name_key("f.master_project")}
LEFT JOIN tower_points AS tp ON tp.name_key = f.building_name_key AND f.building_name_key != ''
LEFT JOIN dxbi_points AS dp
    ON dp.name_key = f.building_name_key AND dp.area_key = lowerUTF8(f.dxbi_community)
   AND f.building_name_key != ''
)
{t._HEAVY_QUERY_SETTINGS}
"""


SALE_PROFILE_SQL = _finished(
    table="dxbi_sale_profile",
    columns=SALE_PROFILE_COLUMNS,
    resolved=_SALE_RESOLVED,
    key="sale_key",
    lease=False,
)
RENTAL_PROFILE_SQL = _finished(
    table="dxbi_rental_profile",
    columns=RENTAL_PROFILE_COLUMNS,
    resolved=_RENTAL_RESOLVED,
    key="contract_key",
    lease=True,
)

# The records the Transactions pages list, once each, for the Analytics pages. The identity rules
# are those of backend/app/transaction/queries.py (``_sales_source`` / ``_rentals_source``) over
# all dates; keep the two in step. A sale: its latest load (the most complete listing among
# conflicting ones); a CSV-export copy of a scraped sale (same area, building, numbered unit,
# date and price, one DXBI link, the same facts) counts once. A lease: identical rows of one
# numbered unit count once, and a lease listed without its unit that equals a numbered lease's
# building path, area and terms is that lease.
LISTED_TABLES = ("dxbi_sales_listed", "dxbi_leases_listed")
SALES_LISTED_COLUMNS = (
    "sale_key", "transaction_date", "unit_number", "building_name", "project_name", "area_name",
    "property_type",
    "bedrooms", "market_status", "size_sqft", "sale_amount_aed", "price_per_sqft_aed",
    "profile_area", "profile_master", "profile_project", "profile_project_source",
    "profile_bedrooms", "profile_status", "profile_size", "built_at",
)  # fmt: skip
LEASES_LISTED_COLUMNS = (
    "contract_key", "lease_start", "lease_end", "unit_number", "building_name", "project_name",
    "area_name",
    "property_type", "bedrooms", "size_sqft", "annual_rent_aed", "contract_amount_aed",
    "contract_term_months", "contract_state", "profile_area", "profile_master",
    "profile_project", "profile_project_source", "profile_bedrooms", "profile_size", "built_at",
)  # fmt: skip
_SALE_TERMS = (
    "if(match(unit_number, '[0-9]') AND building_key != '' AND {area} != '', "
    "concat({area}, '|', building_key, '|', unit_number, '|', toString(transaction_date), '|', "
    "toString(sale_amount_aed)), sale_key)"
).format(area=f"if(area_key != '', area_key, {location_key_sql('area_name')})")
SALES_LISTED_SQL = f"""
INSERT INTO `dxbi_sales_listed` ({", ".join(SALES_LISTED_COLUMNS)})
SELECT x.sale_key, x.transaction_date, x.unit_number, x.building_name, x.project_name,
       x.area_name,
       x.property_type, x.bedrooms, x.market_status, x.size_sqft, x.sale_amount_aed,
       if(x.price_per_sqft_aed > 0, x.price_per_sqft_aed, NULL),
       p.area_name, p.master_project, p.project_name, p.project_source, p.bedrooms,
       p.completion_status, p.size_sqft, now64(3)
FROM (
    SELECT * FROM (
        SELECT *, if(
            uniqExactIf(detail_url, detail_url != '') OVER terms != 1
            OR uniqExactIf(dld_transaction_number, dld_transaction_number != '') OVER terms > 1
            OR uniqExact(tuple(project_name, property_type, size_sqft, bedrooms, market_status))
                OVER terms > 1,
            sale_key, sale_terms) AS same_sale
        FROM (
            SELECT *, {_SALE_TERMS} AS sale_terms
            FROM (
                SELECT * FROM dxbi_sales_unit_events FINAL
                ORDER BY sale_key, loaded_at DESC, area_name = '', bedrooms = '',
                         market_status = '', length(building_name), building_key, bedrooms,
                         size_key
                LIMIT 1 BY sale_key
            )
        )
        WINDOW terms AS (PARTITION BY sale_terms)
    )
    ORDER BY same_sale, detail_url = '', loaded_at DESC, sale_key
    LIMIT 1 BY same_sale
) AS x
LEFT JOIN dxbi_sale_profile AS p ON p.sale_key = x.sale_key
{t._HEAVY_QUERY_SETTINGS}
"""
_LEASE_TERMS = (
    "cityHash64(location_name, building_name, area_name, property_type, bedrooms, size_sqft, "
    "lease_start, lease_end, contract_amount_aed, contract_state)"
)
_SAME_LEASE = (
    "if(unit_number != '', cityHash64(unit_number, location_name, property_type, bedrooms, "
    "size_sqft, lease_start, lease_end, contract_amount_aed, contract_state), "
    "cityHash64(contract_key))"
)
LEASES_LISTED_SQL = f"""
INSERT INTO `dxbi_leases_listed` ({", ".join(LEASES_LISTED_COLUMNS)})
SELECT x.contract_key, x.lease_start, x.lease_end, x.unit_number, x.building_name,
       x.project_name, x.area_name,
       -- DXBI's "Commercial" is refined from the matched DLD contract (Office, Shop).
       if(p.property_type_source = 'dld_pair', p.property_type, x.property_type), x.bedrooms, x.size_sqft, x.annual_rent_aed, x.contract_amount_aed,
       x.contract_term_months, x.contract_state,
       p.area_name, p.master_project, p.project_name, p.project_source, p.bedrooms, p.size_sqft,
       now64(3)
FROM (
    SELECT *, {_SAME_LEASE} AS same_lease
    FROM dxbi_rental_events FINAL
    WHERE unit_number != '' OR building_name = '' OR area_name = ''
       OR {_LEASE_TERMS} NOT IN (
           SELECT {_LEASE_TERMS} FROM dxbi_rental_events FINAL WHERE unit_number != '')
    ORDER BY same_lease, occurrence_index, contract_key
    LIMIT 1 BY same_lease
) AS x
LEFT JOIN dxbi_rental_profile AS p ON p.contract_key = x.contract_key
{t._HEAVY_QUERY_SETTINGS}
"""

PROFILE_STATEMENTS = {
    "dxbi_sale_profile": SALE_PROFILE_SQL,
    "dxbi_rental_profile": RENTAL_PROFILE_SQL,
    "dxbi_sales_listed": SALES_LISTED_SQL,
    "dxbi_leases_listed": LEASES_LISTED_SQL,
}


def _create_statement(table: str) -> str:
    schema = schema_sql_path().read_text()
    match = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \(.*?;", schema, re.DOTALL)
    if match is None:
        raise RuntimeError(f"{table} is missing from the ClickHouse schema")
    return match.group(0).rstrip(";")


def create_tables(clickhouse: Any) -> None:
    """Create only the profile and listed tables (the full schema run also replaces views)."""
    for table in (*PROFILE_TABLES, *LISTED_TABLES):
        clickhouse.command(_create_statement(table))


def build_profile(clickhouse: Any, table: str) -> int:
    """Fill a staging copy, then swap it in; an empty build leaves the served table unchanged."""
    staging = f"{table}__staging"
    clickhouse.command(f"DROP TABLE IF EXISTS {staging}")
    # From the schema, not AS the served table, so a new column reaches the served table.
    clickhouse.command(_create_statement(table).replace(table, staging, 1))
    clickhouse.command(PROFILE_STATEMENTS[table].replace(f"`{table}`", staging))
    rows = int(clickhouse.query(f"SELECT count() FROM {staging}").result_rows[0][0])
    if rows == 0:
        clickhouse.command(f"DROP TABLE {staging}")
        raise RuntimeError(f"{table}: the build produced no rows; the served table is unchanged")
    clickhouse.command(f"EXCHANGE TABLES {staging} AND {table}")
    clickhouse.command(f"DROP TABLE {staging}")
    return rows


def build_profiles(clickhouse: Any) -> dict[str, int]:
    """Both profiles, sales first (the lease profile reads the sale profile), then the listed
    records that read them."""
    create_tables(clickhouse)
    return {table: build_profile(clickhouse, table) for table in (*PROFILE_TABLES, *LISTED_TABLES)}


def build_listed(clickhouse: Any) -> dict[str, int]:
    """The listed records alone, with the profiles as built last: after a DXBI load, so the
    Analytics pages see new records before the next profile build names their DLD project."""
    create_tables(clickhouse)
    return {table: build_profile(clickhouse, table) for table in LISTED_TABLES}
