"""DXBI sales and rental records for the Transactions pages.

The Transactions pages show DXBInteract (DXBI) records only (decision 2026-10-06): every row and
every value comes from Holocron's DXBI tables, ``dxbi_sales_unit_events`` and
``dxbi_rental_events``. No DLD row and no DLD-filled value reaches them; the Analytics pages keep
the combined market layer (``ch_transactions`` / ``ch_rent_contracts``).

Every record DXBI lists is shown, with its unit as DXBI shows it, so rows and totals match DXBI
(decision 2026-10-09). DXBI lists a day's sales before their units and fills them in about a day
later; the morning re-scrape of the last three days (``dxbi-sales-morning``) reads them.

Each request reads one de-duplicated, normalised DXBI source with its date window applied before
de-duplication (``_sales_source`` / ``_rentals_source``), and one WHERE clause built from the
filters (``_sales_where`` / ``_rentals_where``), so the list, its total, the filter options and
the export always describe the same rows.
"""

from typing import Optional

from app.clickhouse.client import query
from app.transaction.models import RentalFilters, SalesFilters

# DXBI names a property type but no usage; the page's Residential / Commercial switch groups the
# types. Plots and rows DXBI gives no type appear under "All" only.
RESIDENTIAL_TYPES = ("Apartment", "Villa", "Townhouse", "Hotel Apartment")
COMMERCIAL_TYPES = (
    "Office",
    "Shop",
    "Show Rooms",
    "Warehouse",
    "Workshop",
    "Clinic",
    "Gymnasium",
    "Hotel",
    "Sized Partition",
    "Building",
    "Commercial",
)


def _sql_list(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


_USAGE = (
    f"multiIf(property_type IN {_sql_list(RESIDENTIAL_TYPES)}, 'Residential', "
    f"property_type IN {_sql_list(COMMERCIAL_TYPES)}, 'Commercial', '')"
)

# DXBI writes '1 Bed', '2 Bed' and '2 Beds' for the same counts: one label per count.
_BEDROOMS = r"""multiIf(
    bedrooms = 'Studio', 'Studio',
    match(bedrooms, '^[0-9]+ Beds?$'),
    concat(extract(bedrooms, '^([0-9]+)'), if(extract(bedrooms, '^([0-9]+)') = '1', ' Bed', ' Beds')),
    '')"""

# DXBI spells a few places two ways ('City of Arabia' / 'City Of Arabia', 'Dubai Land' /
# 'Dubailand', 'Jumeirah Village Circle Dubai'). Each place shows DXBI's commonest spelling of the
# same letters and digits, and a trailing ' Dubai' is dropped when DXBI also names the place
# without it. An area that is a unit marker ('No. 630', a 2026 plot format the loader misreads)
# is not a location.
_LOCATION_SPELLING = r"""(
        SELECT (groupArray(k), groupArray(name)) FROM (
            SELECT k, argMax(name, n) AS name FROM (
                SELECT replaceRegexpAll(lowerUTF8(area_name), '[^a-z0-9]', '') AS k,
                       area_name AS name, count() AS n
                FROM (SELECT area_name FROM dxbi_sales_unit_events
                      UNION ALL SELECT area_name FROM dxbi_rental_events)
                WHERE area_name != ''
                GROUP BY k, name
            )
            GROUP BY k
        )
    ) AS location_spelling"""
_LOCATION = r"""multiIf(
    area_name = '' OR match(area_name, '^No\\.'), '',
    transform(
        if(match(area_name, '\\sDubai$')
           AND has(location_spelling.1,
                   replaceRegexpAll(lowerUTF8(replaceRegexpOne(area_name, '\\s+Dubai$', '')),
                                    '[^a-z0-9]', '')),
           replaceRegexpAll(lowerUTF8(replaceRegexpOne(area_name, '\\s+Dubai$', '')),
                            '[^a-z0-9]', ''),
           replaceRegexpAll(lowerUTF8(area_name), '[^a-z0-9]', '')),
        location_spelling.1, location_spelling.2, area_name))"""


# DXBI's Location choices are its own areas, sub-areas and master communities, and a record
# belongs to them as DXBI's area pages count it (decision 2026-10-07: totals match the website).
# Those pages can count a record under a different place than the area printed on it: JVC's page
# counts buildings printed "Al Barsha South 4", and Dubai Marina's leaves out 27 of 181 sales
# printed "Dubai Marina" (August 2026). dxbi_location_members holds the sales each location's
# search returned over the last sweep (holocron/scripts/dxbi_location_sweep.py), and
# dxbi_location_lease_members the leases. A record takes, in order: the locations that returned
# it; else those that returned other sales in its building; else the location named like its
# printed area, with the areas above it.
_SEARCH_KEY = r"""replaceRegexpAll(replaceAll(replaceAll(replaceAll(lowerUTF8({value}),
    'jumeriah', 'jumeirah'), 'residences', 'residence'), 'apartments', 'apartment'),
    '[^a-z0-9]+', '')"""
_BUILDING_LOCATIONS = """(
        SELECT building_key AS swept_building_key, area_key AS swept_area_key,
               groupUniqArray(location_name) AS building_locations
        FROM dxbi_location_members
        WHERE building_key != ''
        GROUP BY building_key, area_key
    )"""
_PRINTED_LOCATIONS = """(
        SELECT name_key AS printed_key,
               arrayDistinct(arrayFlatten(groupArray(lineage))) AS printed_locations
        FROM dxbi_locations
        GROUP BY name_key
    )"""
# Building and Project as DXBI's location list gives them (dxbi_places, loaded with each sweep):
# DXBI prints a record's location as one place's path, and the first part is a building (B), a
# project (P) or an area. A sale keys its path by its first and last parts, a lease by the whole
# path. A record whose path is not in the list keeps the parsed names. A single-name place DXBI
# lists as an area or community is the record's area, not its building.
_SALE_PLACES = """(
        SELECT building_key AS place_building_key, area_key AS place_area_key, flag AS place_flag,
               building_label AS place_building, project_label AS place_project,
               area_label AS place_area
        FROM dxbi_places
        ORDER BY building_key, area_key, match_rank, location_id
        LIMIT 1 BY building_key, area_key
    )"""
_LEASE_PLACES = """(
        SELECT path_key AS place_path_key, flag AS place_flag,
               building_label AS place_building, project_label AS place_project
        FROM dxbi_places
        ORDER BY path_key, match_rank, location_id
        LIMIT 1 BY path_key
    )"""
_PLACE_LABELS = """if(place_flag != '', place_building, building_name) AS building_name,
                if(place_flag != '', place_project, project_name) AS project_name"""
_DXBI_LOCATIONS = """multiIf(
            notEmpty(building_locations), building_locations,
            notEmpty(printed_locations), printed_locations,
            location_name != '', [location_name], [])"""

# The DXBI record's profile (holocron.market.dxbi_profile, rebuilt after each market release):
# DLD's official area and master project, and the DLD or same-unit value for a project,
# building, bedroom count or completion status DXBI left empty. DXBI's own values always win, and
# the profile's copies of DXBI's raw path parts are not used: the place labels above decide
# those (a lease path whose first part is a project has no building).
_SALE_PROFILE = """(
        SELECT sale_key AS profile_sale_key,
               if(project_source != 'dxbi', project_name, '') AS profile_project,
               master_project AS profile_master, area_name AS profile_area,
               bedrooms AS profile_bedrooms, completion_status AS profile_status,
               location AS profile_location, map_url AS profile_map_url,
               size_sqft AS profile_size
        FROM dxbi_sale_profile
    )"""
_LEASE_PROFILE = """(
        SELECT contract_key AS profile_contract_key,
               -- DLD's plot reference stays in the location text: it is not a building name
               -- to filter by.
               if(building_source = 'dxbi_sale', building_name, '') AS profile_building,
               if(project_source != 'dxbi', project_name, '') AS profile_project,
               master_project AS profile_master,
               area_name AS profile_area, bedrooms AS profile_bedrooms,
               location AS profile_location, map_url AS profile_map_url,
               size_sqft AS profile_size
        FROM dxbi_rental_profile
    )"""
_PROFILE_BEDROOMS = _BEDROOMS.replace("bedrooms", "profile_bedrooms")


def _sales_source(date_clause: str) -> str:
    """One row per DXBI sale, in DXBI's own units: sizes in sq ft, prices in AED.

    De-duplication: the source table keeps a second version of a sale whose address was
    re-normalised (latest load wins). DXBI itself lists some sales twice in one scrape with
    conflicting details (an agent's name glued to the building, a missing bedroom count): the
    more complete listing wins (location, bedrooms and status present, then the shorter building
    name). A sale loaded both from a CSV export (no DXBI link) and from a scrape has two keys; one
    real unit sold on the same day at the same price is one sale.

    Size and price per sq ft are DXBI's own figures, as DXBInteract shows them (decision
    2026-10-07). For some villas DXBI divides the price by the built-up area rather than the size
    it shows; only a sale without DXBI's figure gets price / size.
    """
    area_identity = f"if(area_key != '', area_key, {_SEARCH_KEY.format(value='area_name')})"
    same_sale = (
        f"if(match(unit_number, '[0-9]') AND building_key != '' AND {area_identity} != '', "
        f"concat({area_identity}, '|', building_key, '|', unit_number, '|', "
        "toString(transaction_date), '|', toString(sale_amount_aed)), sale_key)"
    )
    return rf"""
        WITH {_LOCATION_SPELLING}
        SELECT
            sale_key AS transaction_id,
            transaction_date,
            unit_number,
            building_name,
            if(project_name != '', project_name, profile_project) AS project_name,
            profile_master AS master_project,
            profile_area AS dld_area,
            profile_location AS location,
            profile_map_url AS map_url,
            {_LOCATION} AS location_name,
            property_type,
            {_USAGE} AS property_usage,
            if(bedrooms != '', {_BEDROOMS}, {_PROFILE_BEDROOMS}) AS bedrooms,
            multiIf(market_status = 'Offplan', 'Off-Plan', market_status = 'Ready', 'Ready',
                    profile_status) AS status,
            multiIf(size_sqft > 0, size_sqft, profile_size > 0, profile_size, NULL) AS size_sqft,
            sale_amount_aed AS price_aed,
            multiIf(price_per_sqft_aed > 0, toInt64(round(price_per_sqft_aed)),
                    size_sqft > 0, toInt64(round(sale_amount_aed / size_sqft)), NULL)
                AS price_per_sqft,
            if(notEmpty(sale_locations), sale_locations, {_DXBI_LOCATIONS}) AS dxbi_locations
        FROM (
            SELECT * REPLACE (
                {_PLACE_LABELS},
                if(area_name = '', place_area, area_name) AS area_name
            )
            FROM (
                SELECT *, {same_sale} AS same_sale
                FROM (
                    SELECT * FROM dxbi_sales_unit_events FINAL
                    WHERE {date_clause}
                    ORDER BY sale_key, loaded_at DESC, area_name = '', bedrooms = '',
                             market_status = '', length(building_name), building_key, bedrooms,
                             size_key
                    LIMIT 1 BY sale_key
                )
                ORDER BY same_sale, detail_url = '', loaded_at DESC, sale_key
                LIMIT 1 BY same_sale
            ) AS deduped
            LEFT JOIN {_SALE_PLACES} AS place
                ON place.place_building_key = deduped.building_key
                AND place.place_area_key = deduped.area_key
        ) AS sale
        LEFT JOIN (
            SELECT sale_key AS swept_sale_key, groupUniqArray(location_name) AS sale_locations
            FROM dxbi_location_members
            GROUP BY sale_key
        ) AS swept_sale ON swept_sale.swept_sale_key = sale.sale_key
        LEFT JOIN {_BUILDING_LOCATIONS} AS swept_building
            ON swept_building.swept_building_key = sale.building_key
            AND swept_building.swept_area_key = sale.area_key
        LEFT JOIN {_PRINTED_LOCATIONS} AS printed ON printed.printed_key = sale.area_key
        LEFT JOIN {_SALE_PROFILE} AS profile ON profile.profile_sale_key = sale.sale_key
    """


def _rentals_source(date_clause: str) -> str:
    """One row per DXBI lease of one unit, in DXBI's own units: sizes in sq ft, amounts in AED.

    DXBI lists a multi-unit lease once per unit. Its report can also repeat one row (identical
    unit, dates, amount and state, same raw fingerprint) when paging shifts during a scrape: a
    numbered unit cannot hold two identical leases, so those collapse to one. DXBI also lists
    some leases both with their unit number and without it (two report views): a lease without
    a unit whose building path, area and commercial terms equal a numbered lease's is
    that lease (2026-10-07: 90 of Business Bay's 2,121 leases in June 2026). Other identical
    rows without a unit number cannot be told apart and are all kept.
    """
    lease_terms = (
        "cityHash64(location_name, building_name, area_name, property_type, bedrooms, "
        "size_sqft, lease_start, lease_end, "
        "contract_amount_aed, contract_state)"
    )
    same_lease = (
        "if(unit_number != '', cityHash64(unit_number, location_name, property_type, bedrooms, "
        "size_sqft, lease_start, lease_end, contract_amount_aed, contract_state), "
        "cityHash64(contract_key))"
    )
    # A lease's building and area keyed as the sales loader keys them (sales_units.location_key).
    building_key = _SEARCH_KEY.format(value="building_name")
    area_key = _SEARCH_KEY.format(value="area_name")
    path_key = _SEARCH_KEY.format(value="location_name")
    return rf"""
        WITH {_LOCATION_SPELLING}
        SELECT
            contract_key AS contract_id,
            lease_start,
            lease_end,
            unit_number,
            if(building_name != '', building_name, profile_building) AS building_name,
            if(project_name != '', project_name, profile_project) AS project_name,
            profile_master AS master_project,
            profile_area AS dld_area,
            profile_location AS location,
            profile_map_url AS map_url,
            {_LOCATION} AS location_name,
            property_type,
            {_USAGE} AS property_usage,
            if(bedrooms != '', {_BEDROOMS}, {_PROFILE_BEDROOMS}) AS bedrooms,
            multiIf(size_sqft > 0, size_sqft, profile_size > 0, profile_size, NULL) AS size_sqft,
            if(annual_rent_aed > 0, annual_rent_aed, NULL) AS annual_rent_aed,
            if(contract_amount_aed > 0, contract_amount_aed, NULL) AS contract_amount_aed,
            contract_term_months AS term_months,
            contract_state AS contract_type,
            if(notEmpty(lease_locations), lease_locations, {_DXBI_LOCATIONS}) AS dxbi_locations
        FROM (
            SELECT * REPLACE ({_PLACE_LABELS})
            FROM (
                SELECT *, {same_lease} AS same_lease,
                       {building_key} AS lease_building_key, {area_key} AS lease_area_key,
                       {path_key} AS lease_path_key
                FROM dxbi_rental_events FINAL
                WHERE {date_clause}
                  AND (unit_number != '' OR building_name = '' OR area_name = ''
                       OR {lease_terms} NOT IN (
                      SELECT {lease_terms} FROM dxbi_rental_events FINAL
                      WHERE {date_clause} AND unit_number != ''))
                ORDER BY same_lease, occurrence_index, contract_key
                LIMIT 1 BY same_lease
            ) AS deduped
            LEFT JOIN {_LEASE_PLACES} AS place ON place.place_path_key = deduped.lease_path_key
        ) AS lease
        LEFT JOIN (
            SELECT contract_key AS swept_contract_key,
                   groupUniqArray(location_name) AS lease_locations
            FROM dxbi_location_lease_members
            GROUP BY contract_key
        ) AS swept_lease ON swept_lease.swept_contract_key = lease.contract_key
        LEFT JOIN {_BUILDING_LOCATIONS} AS swept_building
            ON swept_building.swept_building_key = lease.lease_building_key
            AND swept_building.swept_area_key = lease.lease_area_key
        LEFT JOIN {_PRINTED_LOCATIONS} AS printed ON printed.printed_key = lease.lease_area_key
        LEFT JOIN {_LEASE_PROFILE} AS profile ON profile.profile_contract_key = lease.contract_key
    """


def _date_window(column: str, timeframe_days: Optional[int], params: dict) -> str:
    """The last ``timeframe_days`` calendar days up to and including today (warehouse clock)."""
    if timeframe_days is None:
        return "1 = 1"
    params["timeframe_days"] = timeframe_days
    return f"{column} > today() - {{timeframe_days:Int32}} AND {column} <= today()"


def _equals(clauses: list[str], params: dict, column: str, name: str, value) -> None:
    if value:
        clauses.append(f"{column} = {{{name}:String}}")
        params[name] = value


def _location(clauses: list[str], params: dict, value) -> None:
    """A DXBI location holds every record its area page counts (``dxbi_locations``)."""
    if value:
        clauses.append("has(dxbi_locations, {location:String})")
        params["location"] = value


def _band(clauses: list[str], params: dict, column: str, name: str, low, high) -> None:
    """Range filters are half-open, [low, high): a boundary value belongs to one band only."""
    if low is not None:
        clauses.append(f"{column} >= {{{name}_min:Float64}}")
        params[f"{name}_min"] = low
    if high is not None:
        clauses.append(f"{column} < {{{name}_max:Float64}}")
        params[f"{name}_max"] = high


def _sales_where(filters: SalesFilters, params: dict) -> str:
    clauses: list[str] = []
    _equals(clauses, params, "property_usage", "property_usage", filters.property_usage)
    _equals(clauses, params, "property_type", "property_type", filters.property_type)
    _equals(clauses, params, "bedrooms", "bedrooms", filters.bedrooms)
    _equals(clauses, params, "status", "status", filters.status)
    _location(clauses, params, filters.location)
    _equals(clauses, params, "building_name", "building", filters.building)
    _equals(clauses, params, "project_name", "project", filters.project)
    _band(clauses, params, "size_sqft", "size", filters.size_min, filters.size_max)
    _band(clauses, params, "price_aed", "price", filters.price_min, filters.price_max)
    _band(
        clauses,
        params,
        "price_per_sqft",
        "price_per_sqft",
        filters.price_per_sqft_min,
        filters.price_per_sqft_max,
    )
    return " AND ".join(clauses) or "1 = 1"


def _rentals_where(filters: RentalFilters, params: dict) -> str:
    clauses: list[str] = []
    _equals(clauses, params, "property_usage", "property_usage", filters.property_usage)
    _equals(clauses, params, "property_type", "property_type", filters.property_type)
    _equals(clauses, params, "bedrooms", "bedrooms", filters.bedrooms)
    _equals(clauses, params, "contract_type", "contract_type", filters.contract_type)
    _location(clauses, params, filters.location)
    _equals(clauses, params, "building_name", "building", filters.building)
    _equals(clauses, params, "project_name", "project", filters.project)
    _band(clauses, params, "size_sqft", "size", filters.size_min, filters.size_max)
    _band(clauses, params, "annual_rent_aed", "rent", filters.rent_min, filters.rent_max)
    return " AND ".join(clauses) or "1 = 1"


_SALE_COLUMNS = """transaction_id, transaction_date, unit_number, building_name, project_name,
            master_project, dld_area, location, map_url, location_name, property_type, property_usage, bedrooms, status, size_sqft,
            price_aed, price_per_sqft"""
_RENTAL_COLUMNS = """contract_id, lease_start, lease_end, unit_number, building_name,
            project_name, master_project, dld_area, location, map_url, location_name, property_type, property_usage, bedrooms, size_sqft,
            annual_rent_aed, contract_amount_aed, term_months, contract_type"""


async def fetch_sales_rows(
    filters: SalesFilters, limit: int, offset: int
) -> tuple[list[dict], int]:
    """One page of sales, newest first, and the total matching the filters."""
    params: dict = {"limit": limit, "offset": offset}
    source = _sales_source(_date_window("transaction_date", filters.timeframe_days, params))
    where = _sales_where(filters, params)
    total = await query(f"SELECT count() AS total FROM ({source}) WHERE {where}", params)
    rows = await query(
        f"""
        SELECT {_SALE_COLUMNS}
        FROM ({source})
        WHERE {where}
        ORDER BY transaction_date DESC, transaction_id
        LIMIT {{limit:Int32}} OFFSET {{offset:Int32}}
        """,
        params,
    )
    return rows, int(total[0]["total"]) if total else 0


async def fetch_rental_rows(
    filters: RentalFilters, limit: int, offset: int
) -> tuple[list[dict], int]:
    """One page of leases, latest start first, and the total matching the filters."""
    params: dict = {"limit": limit, "offset": offset}
    source = _rentals_source(_date_window("lease_start", filters.timeframe_days, params))
    where = _rentals_where(filters, params)
    total = await query(f"SELECT count() AS total FROM ({source}) WHERE {where}", params)
    rows = await query(
        f"""
        SELECT {_RENTAL_COLUMNS}
        FROM ({source})
        WHERE {where}
        ORDER BY lease_start DESC, contract_id
        LIMIT {{limit:Int32}} OFFSET {{offset:Int32}}
        """,
        params,
    )
    return rows, int(total[0]["total"]) if total else 0


def _ids(value: Optional[str]) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


async def export_sales_rows(
    filters: SalesFilters, transaction_ids: Optional[str], max_rows: int
) -> list[dict]:
    """Sales for an export: the selected rows when ids are given, else the filtered rows."""
    params: dict = {"max_rows": max_rows}
    ids = _ids(transaction_ids)
    if ids:
        params["ids"] = ids
        source, where = _sales_source("1 = 1"), "transaction_id IN {ids:Array(String)}"
    else:
        source = _sales_source(_date_window("transaction_date", filters.timeframe_days, params))
        where = _sales_where(filters, params)
    return await query(
        f"""
        SELECT {_SALE_COLUMNS}
        FROM ({source})
        WHERE {where}
        ORDER BY transaction_date DESC, transaction_id
        LIMIT {{max_rows:Int32}}
        """,
        params,
    )


async def export_rental_rows(
    filters: RentalFilters, contract_ids: Optional[str], max_rows: int
) -> list[dict]:
    """Leases for an export: the selected rows when ids are given, else the filtered rows."""
    params: dict = {"max_rows": max_rows}
    ids = _ids(contract_ids)
    if ids:
        params["ids"] = ids
        source, where = _rentals_source("1 = 1"), "contract_id IN {ids:Array(String)}"
    else:
        source = _rentals_source(_date_window("lease_start", filters.timeframe_days, params))
        where = _rentals_where(filters, params)
    return await query(
        f"""
        SELECT {_RENTAL_COLUMNS}
        FROM ({source})
        WHERE {where}
        ORDER BY lease_start DESC, contract_id
        LIMIT {{max_rows:Int32}}
        """,
        params,
    )


async def fetch_sales_facets(filters: SalesFilters) -> dict:
    """Filter options narrowed by the current filters, in one scan."""
    params: dict = {}
    source = _sales_source(_date_window("transaction_date", filters.timeframe_days, params))
    rows = await query(
        f"""
        SELECT
            groupUniqArrayIf(property_type, property_type != '') AS property_type_options,
            groupUniqArrayIf(bedrooms, bedrooms != '') AS bedroom_options,
            groupUniqArrayIf(status, status != '') AS status_options,
            groupUniqArrayArray(dxbi_locations) AS location_options,
            groupUniqArrayIf(building_name, building_name != '') AS building_options,
            groupUniqArrayIf(project_name, project_name != '') AS project_options
        FROM ({source})
        WHERE {_sales_where(filters, params)}
        """,
        params,
    )
    return rows[0] if rows else {}


async def fetch_rental_facets(filters: RentalFilters) -> dict:
    """Filter options narrowed by the current filters, in one scan."""
    params: dict = {}
    source = _rentals_source(_date_window("lease_start", filters.timeframe_days, params))
    rows = await query(
        f"""
        SELECT
            groupUniqArrayIf(property_type, property_type != '') AS property_type_options,
            groupUniqArrayIf(bedrooms, bedrooms != '') AS bedroom_options,
            groupUniqArrayIf(contract_type, contract_type != '') AS contract_type_options,
            groupUniqArrayArray(dxbi_locations) AS location_options,
            groupUniqArrayIf(building_name, building_name != '') AS building_options,
            groupUniqArrayIf(project_name, project_name != '') AS project_options
        FROM ({source})
        WHERE {_rentals_where(filters, params)}
        """,
        params,
    )
    return rows[0] if rows else {}
