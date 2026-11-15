from __future__ import annotations

import asyncio
from typing import Any

from crm_rental_sql import AREA_LEAD_CTE, CANDIDATE_SOURCE, LIVE_LEAD_CTE

from app.clickhouse.client import ClientDisconnected, query, run_cancellable
from app.crm.rental_base import lead_cte


async def fetch_sales_inventory(parameters):
    return await query(
        """
                SELECT
                    sales.building_key,
                    lowerUTF8(sales.unit_number) AS normalized_unit,
                    argMax(sales.sale_key, sales.transaction_date) AS sale_key,
                    argMax(sales.building_name, sales.transaction_date) AS building_name,
                    argMax(sales.unit_number, sales.transaction_date) AS unit_number,
                    argMax(sales.area_name, sales.transaction_date) AS area_name,
                    argMax(sales.property_type, sales.transaction_date) AS property_type,
                    argMax(sales.bedrooms, sales.transaction_date) AS bedrooms,
                    argMax(sales.size_sqft, sales.transaction_date) AS size_sqft,
                    argMax(sales.sale_amount_aed, sales.transaction_date) AS sale_amount_aed,
                    max(sales.transaction_date) AS latest_sale_date
                FROM (
                    SELECT *
                    FROM dxbi_sales_unit_events FINAL
                    WHERE
                        unit_number != ''
                        AND (
                            {area:String} = ''
                            OR positionCaseInsensitiveUTF8(area_name, {area:String}) > 0
                            OR positionCaseInsensitiveUTF8(building_name, {area:String}) > 0
                        )
                ) AS sales
                GROUP BY sales.building_key, normalized_unit
                ORDER BY latest_sale_date DESC
                LIMIT 120
                """,
        parameters,
    )


async def fetch_instruction_evidence(parameters):
    return await query(
        """
                SELECT
                    sale_key,
                    transaction_date,
                    building_name,
                    unit_number,
                    area_name,
                    property_type,
                    bedrooms,
                    size_sqft,
                    sale_amount_aed,
                    ltv_pct,
                    seller_type,
                    detail_url
                FROM dxbi_sales_unit_events FINAL
                WHERE
                    positionCaseInsensitiveUTF8(building_name, {building:String}) > 0
                    AND lowerUTF8(unit_number) = lowerUTF8({unit_number:String})
                ORDER BY transaction_date DESC
                LIMIT 1
                """,
        parameters,
    )


async def fetch_matching_rentals(parameters):
    return await query(
        """
        SELECT
            c.unit_candidate_key,
            c.event_key,
            c.building_name,
            c.project_name,
            c.area_name,
            c.property_type,
            c.bedrooms,
            c.size_sqft,
            c.annual_rent_aed,
            c.purchase_price_aed,
            c.lease_start,
            c.lease_end,
            c.contract_state,
            c.observed_contracts,
            m.unit_number,
            m.last_purchase_date,
            m.matched_sale_price,
            m.match_status,
            m.latest_detail_url
        FROM dxbi_rental_unit_candidates AS c FINAL
        LEFT JOIN dxbi_rental_sale_matches AS m FINAL USING (unit_candidate_key)
        WHERE
            c.lease_end BETWEEN today() - 1825 AND today() + 90
            AND (
                {area:String} = ''
                OR positionCaseInsensitiveUTF8(c.area_name, {area:String}) > 0
                OR positionCaseInsensitiveUTF8(c.project_name, {area:String}) > 0
                OR positionCaseInsensitiveUTF8(c.building_name, {area:String}) > 0
            )
            AND (
                {property_type:String} = ''
                OR lowerUTF8(c.property_type) = lowerUTF8({property_type:String})
            )
        ORDER BY
            abs(dateDiff('day', today(), c.lease_end)) ASC,
            c.annual_rent_aed DESC
        LIMIT 40
        """,
        parameters,
    )


DXBI_TABLE = "dxbi_rental_events"

DXBI_CANDIDATE_TABLE = "dxbi_rental_unit_candidates"

_LEGACY_RENTAL_TABLES = (
    "dxbi_rental_events",
    "dxbi_rental_unit_candidates",
    "dxbi_rental_sale_matches",
)

VALID_BREAKDOWNS = {
    "area": "area_name",
    "project": "project_name",
    "building": "building_name",
}


async def _query_with_legacy_rentals(
    sql: str, params: dict[str, Any], *, saved_candidates: bool = False
) -> list[dict[str, Any]]:
    """Keep saved v1 identities readable without guessing a replacement v2 unit."""
    rows = await query(sql, params)
    legacy_params = dict(params)
    if saved_candidates:
        found = {str(row["saved_candidate_key"]) for row in rows}
        missing = [key for key in params["candidate_keys"] if key not in found]
        if not missing:
            return rows
        legacy_params["candidate_keys"] = missing
    elif rows:
        return rows
    required = [name for name in _LEGACY_RENTAL_TABLES if name in sql]
    available = await query(
        "SELECT count() AS tables FROM system.tables "
        "WHERE database=currentDatabase() AND name IN {names:Array(String)}",
        {"names": [name + "_legacy" for name in required]},
    )
    if not required or not available or int(available[0]["tables"]) != len(required):
        return rows
    legacy_sql = sql
    for name in required:
        legacy_sql = legacy_sql.replace(name, name + "_legacy")
    legacy_rows = await query(legacy_sql, legacy_params)
    return [*rows, *[{**row, "_legacy_identity": True} for row in legacy_rows]]


_LEAD_CTE = LIVE_LEAD_CTE


def _narrowed_lead_cte(selector: str) -> str:
    """The canonical lead CTE over only the leases that can share a target lease's unit.

    `selector` is a condition on `c2` (dxbi_rental_unit_candidates FINAL) picking the target
    leases. The ranking partitions by property identity, which is either the lease's own
    candidate key or a building/area plus its upper-cased unit number. Every lease that can
    share a target's identity therefore has the target's candidate key or its unit number
    (its own, or the matched sale's when it has none), so ranking that superset gives the
    target rows exactly what ranking all of Dubai gives them, for a few thousand rows.
    """
    units = f"""
        SELECT upperUTF8(coalesce(nullIf(c2.unit_number, ''), m2.unit_number)) AS unit
        FROM dxbi_rental_unit_candidates AS c2 FINAL
        LEFT JOIN dxbi_rental_sale_matches AS m2 FINAL
            ON m2.unit_candidate_key = c2.unit_candidate_key
        WHERE {selector}
    """
    source = f"""FROM (
        SELECT *, event_key
        FROM dxbi_rental_unit_candidates FINAL
        WHERE
            unit_candidate_key IN (
                SELECT c2.unit_candidate_key
                FROM dxbi_rental_unit_candidates AS c2 FINAL
                WHERE {selector}
            )
            OR upperUTF8(unit_number) IN (SELECT unit FROM ({units}) WHERE unit != '')
            OR unit_candidate_key IN (
                SELECT unit_candidate_key
                FROM dxbi_rental_sale_matches FINAL
                WHERE upperUTF8(unit_number) IN (SELECT unit FROM ({units}) WHERE unit != '')
            )
    ) AS c"""
    return LIVE_LEAD_CTE.replace(CANDIDATE_SOURCE, source)


_LEAD_BY_EVENT_CTE = _narrowed_lead_cte("c2.event_key = {lead_id:String}")
_LEADS_BY_EVENTS_CTE = _narrowed_lead_cte("c2.event_key IN {event_keys:Array(String)}")
_LEADS_BY_CANDIDATES_CTE = _narrowed_lead_cte(
    "c2.unit_candidate_key IN {candidate_keys:Array(String)}"
)


async def fetch_leads_by_event_keys(anchor, *, expired_days, event_keys):
    """Full lead rows for one page of event keys, in the page's order (missing keys skipped)."""
    if not event_keys:
        return []
    rows = await query(
        _LEADS_BY_EVENTS_CTE + " SELECT * FROM leads WHERE event_key IN {event_keys:Array(String)}",
        {
            "as_of": anchor.isoformat(),
            "expired_days": expired_days,
            "event_keys": list(event_keys),
        },
    )
    by_key = {str(row["event_key"]): row for row in rows}
    return [by_key[key] for key in event_keys if key in by_key]


def _where_clause(
    *,
    status: str | None,
    priority: str | None,
    area: str | None,
    project: str | None,
    building: str | None,
    search: str | None,
    asset_class: str | None = None,
    property_type: str | None = None,
    unlet_only: bool = False,
) -> tuple[str, dict[str, Any]]:
    conditions = ["1 = 1"]
    params: dict[str, Any] = {}
    if unlet_only:
        # Vacant: the exact unit's lease ended, no later lease is registered and it was not sold.
        conditions.append("lease_evidence_state = 'unlet_signal'")
    if status:
        conditions.append("lead_status = {status:String}")
        params["status"] = status
    if priority:
        conditions.append("priority = {priority:String}")
        params["priority"] = priority
    if area:
        conditions.append("area_name = {area:String}")
        params["area"] = area
    if project:
        conditions.append("project_name = {project:String}")
        params["project"] = project
    if building:
        conditions.append("building_name = {building:String}")
        params["building"] = building
    if asset_class:
        conditions.append("asset_class = {asset_class:String}")
        params["asset_class"] = asset_class
    if property_type:
        conditions.append("property_subtype = {property_type:String}")
        params["property_type"] = property_type
    if search:
        conditions.append(
            """
            positionCaseInsensitiveUTF8(
                concat(
                    building_name,
                    ' ',
                    project_name,
                    ' ',
                    area_name,
                    ' ',
                    bedrooms,
                    ' ',
                    property_subtype,
                    ' ',
                    ifNull(unit_number, '')
                ),
                {search:String}
            ) > 0
            """
        )
        params["search"] = search
    return " AND ".join(conditions), params


def _filter_metadata_sql(facet_where: str, cte: str = _LEAD_CTE) -> str:
    """Return live lead facets so every dropdown option can produce a result."""
    return (
        cte
        + f"""
        SELECT
            (SELECT count() FROM dxbi_rental_events FINAL) AS rows,
            (
                SELECT countIf(match_status = 'unique')
                FROM dxbi_rental_sale_matches FINAL
            ) AS exact_unit_matches,
            min(lease_start) AS min_date,
            max(lease_start) AS max_date,
            (SELECT max(source_shard_date) FROM dxbi_rental_events FINAL)
                AS data_complete_through,
            arraySort(groupUniqArrayIf(area_name, area_name != '')) AS areas,
            arraySort(
                groupUniqArrayIf(
                    project_name,
                    project_name != ''
                    AND {{filter_area:String}} != ''
                    AND area_name = {{filter_area:String}}
                )
            ) AS projects,
            arraySort(
                groupUniqArrayIf(
                    building_name,
                    building_name != ''
                    AND {{filter_area:String}} != ''
                    AND area_name = {{filter_area:String}}
                    AND {{filter_project:String}} != ''
                    AND project_name = {{filter_project:String}}
                )
            ) AS buildings
        FROM leads
        WHERE {facet_where}
        """
    )


async def _tables_exist() -> bool:
    rows = await query(
        """
        SELECT count() AS count
        FROM system.tables
        WHERE
            database = currentDatabase()
            AND name IN (
                {events_table:String},
                {candidate_table:String},
                {sales_table:String},
                {match_table:String}
            )
        """,
        {
            "events_table": DXBI_TABLE,
            "candidate_table": DXBI_CANDIDATE_TABLE,
            "sales_table": "dxbi_sales_unit_events",
            "match_table": "dxbi_rental_sale_matches",
        },
    )
    return bool(rows and rows[0]["count"] == 4)


async def fetch_dashboard(
    anchor,
    area,
    asset_class,
    breakdown,
    building,
    expired_days,
    limit,
    offset,
    priority,
    project,
    property_type,
    search,
    status,
):
    cte = await lead_cte(query)
    where, filter_params = _where_clause(
        status=status,
        priority=priority,
        area=area,
        project=project,
        building=building,
        search=search,
        asset_class=asset_class,
        property_type=property_type,
    )
    asset_where, asset_filter_params = _where_clause(
        status=status,
        priority=priority,
        area=area,
        project=project,
        building=building,
        search=search,
    )
    facet_where, facet_filter_params = _where_clause(
        status=status,
        priority=priority,
        area=None,
        project=None,
        building=None,
        search=search,
        asset_class=asset_class,
        property_type=property_type,
    )
    params = {
        **filter_params,
        "as_of": anchor.isoformat(),
        "expired_days": expired_days,
        "limit": limit,
        "offset": offset,
    }
    dimension = VALID_BREAKDOWNS[breakdown]

    lead_sql = (
        cte
        + f"""
        SELECT *
        FROM leads
        WHERE {where}
        ORDER BY raw_score DESC, lease_end ASC, annual_rent_aed DESC
        LIMIT {{limit:Int32}} OFFSET {{offset:Int32}}
        """
    )
    summary_sql = (
        cte
        + f"""
        SELECT
            count() AS total,
            countIf(priority = 'urgent') AS urgent,
            countIf(
                lead_status = 'expired'
                AND lease_evidence_state = 'unlet_signal'
                AND ownership_timing = 'stable_rental_history'
                AND unit_match_status = 'unique'
            ) AS expired,
            countIf(lead_status = 'expiring_30') AS expiring_30,
            countIf(lead_status = 'expiring_60') AS expiring_60,
            countIf(lead_status = 'expiring_90') AS expiring_90,
            countIf(
                lead_status = 'expired'
                AND lease_evidence_state = 'unlet_signal'
                AND ownership_timing = 'stable_rental_history'
                AND unit_match_status = 'unique'
            ) AS sale_candidates,
            sumIf(
                annual_rent_aed,
                ownership_timing = 'stable_rental_history'
            ) AS annual_rent_at_risk
        FROM leads
        WHERE {where}
        """
    )
    breakdown_sql = (
        cte
        + f"""
        SELECT
            if({dimension} = '', 'Unresolved hierarchy', {dimension}) AS label,
            count() AS total,
            countIf(priority = 'urgent') AS urgent,
            countIf(lead_status = 'expired') AS expired,
            countIf(lead_status = 'expiring_30') AS expiring_30,
            countIf(lead_status = 'expiring_60') AS expiring_60,
            countIf(lead_status = 'expiring_90') AS expiring_90,
            sumIf(
                annual_rent_aed,
                ownership_timing = 'stable_rental_history'
            ) AS potential_value
        FROM leads
        WHERE {where}
        GROUP BY label
        ORDER BY urgent DESC, total DESC
        LIMIT 12
        """
    )
    asset_breakdown_sql = (
        cte
        + f"""
        SELECT
            asset_class,
            count() AS total,
            countIf(priority = 'urgent') AS urgent,
            countIf(unit_match_status = 'unique') AS exact_unit_matches,
            sumIf(
                annual_rent_aed,
                ownership_timing = 'stable_rental_history'
            ) AS annual_rent_at_risk,
            arraySort(groupUniqArray(property_subtype)) AS property_types
        FROM leads
        WHERE {asset_where}
        GROUP BY asset_class
        ORDER BY
            multiIf(asset_class = 'residential', 1, asset_class = 'commercial', 2, 3)
        """
    )
    metadata_sql = _filter_metadata_sql(facet_where, cte)
    metadata_params = {
        **facet_filter_params,
        "as_of": anchor.isoformat(),
        "expired_days": expired_days,
        "filter_area": area or "",
        "filter_project": project or "",
    }

    lead_rows, summary_rows, breakdown_rows, asset_rows, metadata_rows = await asyncio.gather(
        query(lead_sql, params),
        query(summary_sql, params),
        query(breakdown_sql, params),
        query(
            asset_breakdown_sql,
            {
                **asset_filter_params,
                "as_of": anchor.isoformat(),
                "expired_days": expired_days,
            },
        ),
        query(metadata_sql, metadata_params),
    )
    return lead_rows, summary_rows, breakdown_rows, asset_rows, metadata_rows


_AREA_LEAD_CTE = AREA_LEAD_CTE


async def run_until_disconnected(is_disconnected, work):
    """Run `work` with time-limited queries; None (queries stopped) if the caller went away."""
    try:
        return await run_cancellable(is_disconnected, work)
    except ClientDisconnected:
        return None


async def fetch_renewal_leads(anchor, areas, forward_days, lookback_days, limit, offset, kind=None):
    """Return one agent's lease-expiry leads: their areas, inside the forward/look-back windows.

    Only leases tied to a known unit number become leads. `kind` narrows them to vacant units
    (lease ended, no later lease registered) or to leases still running.
    """
    kind_condition = {
        None: "",
        "vacant": "AND lease_evidence_state = 'unlet_signal'",
        "upcoming": "AND lease_end >= {as_of:Date}",
    }[kind]
    params = {
        "as_of": anchor.isoformat(),
        "expired_days": lookback_days,
        "forward_days": forward_days,
        "areas": list(areas),
        "limit": limit,
        "offset": offset,
    }
    # One query: window totals are computed over every match before LIMIT applies.
    cte = await lead_cte(query, areas=True)
    rows = await query(
        cte
        + """
        SELECT
            *,
            count() OVER () AS _window_total,
            countIf(lease_end = addDays({as_of:Date}, {forward_days:Int32})) OVER ()
                AS _window_entered_today
        FROM leads
        WHERE
            has({areas:Array(String)}, area_name)
            AND lease_end <= addDays({as_of:Date}, {forward_days:Int32})
            AND ifNull(unit_number, '') != ''
            """
        + kind_condition
        + """
        ORDER BY lease_end ASC, raw_score DESC, event_key
        LIMIT {limit:Int32} OFFSET {offset:Int32}
        """,
        params,
    )
    # A page past the end has no rows to carry the totals; it reports zero.
    counts = {
        "total": rows[0]["_window_total"] if rows else 0,
        "entered_today": rows[0]["_window_entered_today"] if rows else 0,
    }
    return rows, [counts]


async def fetch_renewals(
    anchor,
    *,
    status,
    unlet_only,
    expired_days,
    area,
    property_type,
    project,
    building,
    limit,
    offset,
):
    """Assets › Renewals: one page of leases with its total, plus the options for its filters.

    Two queries instead of the dashboard's five. With an area picked, leases are narrowed to it
    before the per-unit work (the same narrowing as the agent's renewal leads).
    """
    cte = await lead_cte(query, areas=bool(area))
    where, filter_params = _where_clause(
        status=status,
        priority=None,
        area=area,
        project=project,
        building=building,
        search=None,
        property_type=property_type,
        unlet_only=unlet_only,
    )
    # The options list what the other filters allow, so picking one never empties its own list.
    facet_where, facet_params = _where_clause(
        status=status,
        priority=None,
        area=area,
        project=None,
        building=None,
        search=None,
        unlet_only=unlet_only,
    )
    base = {
        "as_of": anchor.isoformat(),
        "expired_days": expired_days,
        "areas": [area] if area else [],
    }
    rows_sql = (
        cte
        + f"""
        SELECT *, count() OVER () AS _window_total
        FROM leads
        WHERE {where}
        ORDER BY raw_score DESC, lease_end ASC, annual_rent_aed DESC
        LIMIT {{limit:Int32}} OFFSET {{offset:Int32}}
        """
    )
    facets_sql = (
        cte
        + f"""
        SELECT
            arraySort(groupUniqArray(property_subtype)) AS property_types,
            arraySort(
                groupUniqArrayIf(project_name, project_name != '' AND {{filter_area:String}} != '')
            ) AS projects,
            arraySort(
                groupUniqArrayIf(
                    building_name,
                    building_name != ''
                    AND {{filter_project:String}} != ''
                    AND project_name = {{filter_project:String}}
                )
            ) AS buildings
        FROM leads
        WHERE {facet_where}
        """
    )
    rows, facets = await asyncio.gather(
        query(rows_sql, {**base, **filter_params, "limit": limit, "offset": offset}),
        query(
            facets_sql,
            {
                **base,
                **facet_params,
                "filter_area": area or "",
                "filter_project": project or "",
            },
        ),
    )
    total = rows[0]["_window_total"] if rows else 0
    return rows, total, (facets[0] if facets else {})


async def fetch_renewal_areas(anchor):
    """Areas in the lease-expiry dataset, with their leases ending in the next 90 days."""
    cte = await lead_cte(query)
    return await query(
        cte
        + """
        SELECT
            area_name AS area,
            countIf(lease_end >= {as_of:Date}) AS upcoming_90_days
        FROM leads
        WHERE area_name != ''
        GROUP BY area_name
        ORDER BY area_name
        """,
        {"as_of": anchor.isoformat(), "expired_days": 365},
    )


async def fetch_lead(parameters):
    return await _query_with_legacy_rentals(
        _LEAD_BY_EVENT_CTE + " SELECT * FROM leads WHERE event_key = {lead_id:String} LIMIT 1",
        parameters,
    )


async def fetch_lead_rental_history(parameters):
    return await _query_with_legacy_rentals(
        """
        SELECT
            event_key,
            lease_start,
            lease_end,
            annual_rent_aed,
            contract_state
        FROM dxbi_rental_events FINAL
        WHERE unit_candidate_key = {candidate_key:String}
        ORDER BY lease_start DESC
        LIMIT 50
        """,
        parameters,
    )


async def fetch_exact_sale_history(parameters):
    return await query(
        """
                SELECT
                    sale_key,
                    transaction_date AS sale_date,
                    sale_amount_aed,
                    price_per_sqft_aed,
                    capital_gain_pct,
                    ltv_pct,
                    seller_type,
                    seller_transaction_count,
                    market_status,
                    detail_url
                FROM dxbi_sales_unit_events FINAL
                WHERE
                    unit_number = {unit_number:String}
                    AND building_key = {building_key:String}
                ORDER BY transaction_date DESC
                LIMIT 25
                """,
        parameters,
    )


async def fetch_dld_sale_history(parameters):
    return await query(
        """
                SELECT
                    transaction_id,
                    toDate(instance_date) AS sale_date,
                    trans_value,
                    procedure_name_en
                FROM ch_transactions
                WHERE
                    trans_group_en = 'Sales'
                    AND positionCaseInsensitiveUTF8(building_name_en, {building:String}) > 0
                    AND ({bedrooms:String} = '' OR rooms_en = {bedrooms:String})
                    AND (
                        {size_sqft:Float64} = 0
                        OR abs(procedure_area * 10.7639 - {size_sqft:Float64})
                            <= greatest(25, {size_sqft:Float64} * 0.03)
                    )
                ORDER BY instance_date DESC
                LIMIT 25
                """,
        parameters,
    )


async def fetch_candidate_key(parameters):
    return await _query_with_legacy_rentals(
        """
        SELECT unit_candidate_key
        FROM dxbi_rental_unit_candidates FINAL
        WHERE event_key = {lead_id:String}
        LIMIT 1
        """,
        parameters,
    )


async def fetch_saved_leads(parameters):
    rows = await _query_with_legacy_rentals(
        _LEADS_BY_CANDIDATES_CTE
        + """
        SELECT
            i.unit_candidate_key AS saved_candidate_key,
            l.*
        FROM identified_unit AS i
        ANY INNER JOIN leads AS l USING (property_identity_key)
        WHERE i.unit_candidate_key IN {candidate_keys:Array(String)}
        """,
        parameters,
        saved_candidates=True,
    )

    # ClickHouse qualifies joined l.* columns when identified_unit has the same names.
    # Keep the response contract identical to SELECT * FROM leads, including legacy flags.
    return [{key.removeprefix("l."): value for key, value in row.items()} for row in rows]
