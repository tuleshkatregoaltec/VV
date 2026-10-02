"""Build market_sale_events / market_rental_events from DLD bronze and DXBI evidence.

Rules (measured in docs/data-pipelines/DXBI_RECONCILIATION.md):

- DLD is de-duplicated first: Pulse history before the open-data cut-over, open data from it
  (same rule as the silver layer), latest version of each corrected record.
- Each DXBI record is paired one-to-one with a DLD record. Sales: exact price, date within
  3 days, or within 30 days when the size also agrees within 1%. Rentals: exact start date
  with contract amount (tier 0) or annual amount (tier 1).
- Row status: ``matched`` (DLD row carrying DXBI unit identity), ``dld_only`` (DLD fills what
  DXBI lacks), ``dxbi_only`` (DXBI record with no DLD candidate at all — DXBI adds it),
  ``dxbi_probable_duplicate`` (DXBI record that had DLD candidates but lost the one-to-one
  pairing; kept for audit, not served, so nothing is double counted).
- Label drift is fixed here once: Mortgage -> Mortgages, Renew -> Renewed, off-plan status
  from either DLD field.

Statements name the served tables; ``holocron.market.release`` renders them against a run's
staging tables, so a build never writes to what the backend is reading.
"""

from __future__ import annotations

SQFT_PER_SQM = 10.7639
# Large joins and sorts spill to disk instead of failing when memory is tight.
_HEAVY_QUERY_SETTINGS = """SETTINGS
    join_algorithm = 'grace_hash',
    max_bytes_before_external_sort = 2000000000,
    max_bytes_before_external_group_by = 2000000000"""

# Every column of the legacy ch_transactions / ch_rent_contracts views, in order. The backend
# reads these names; the canonical tables must keep all of them (tests enforce it).
SALE_CONTRACT_COLUMNS = (
    "row_key", "run_id", "scraped_at", "transaction_id", "transaction_number", "instance_date",
    "trans_group_id", "trans_group_en", "trans_group_ar", "procedure_id", "procedure_name_en",
    "procedure_name_ar", "procedure_area", "actual_area", "actual_worth", "trans_value",
    "total_buyer", "total_seller", "property_id", "property_type_id", "property_type_en",
    "property_type_ar", "property_sub_type_id", "property_sub_type_en", "property_sub_type_ar",
    "property_usage_id", "property_usage_en", "property_usage_ar", "rooms_en", "rooms_ar",
    "parking", "has_parking", "building_age", "parcel_id", "area_id", "area_name_en",
    "area_name_ar", "project_name_en", "project_name_ar", "master_project_en",
    "master_project_ar", "is_free_hold", "is_free_hold_en", "is_free_hold_ar", "is_offplan",
    "is_offplan_en", "is_offplan_ar", "nearest_metro_en", "nearest_metro_ar", "nearest_mall_en",
    "nearest_mall_ar", "nearest_landmark_en", "nearest_landmark_ar", "project_number",
    "building_name_en", "building_name_ar", "reg_type_id", "reg_type_en", "reg_type_ar",
    "meter_sale_price", "rent_value", "meter_rent_price", "no_of_parties_role_1",
    "no_of_parties_role_2", "no_of_parties_role_3",
)  # fmt: skip
SALE_EXTRA_COLUMNS = (
    "unit_number", "bedrooms", "market_status", "dxbi_sale_key", "dxbi_building_name",
    "dxbi_transaction_date", "source_system", "primary_source", "match_status", "is_served",
    "built_at",
)  # fmt: skip
RENTAL_CONTRACT_COLUMNS = (
    "row_key", "run_id", "scraped_at", "contract_id", "contract_number", "line_number",
    "registration_date", "contract_start_date", "contract_end_date", "property_id",
    "land_property_id", "ejari_property_type_id", "ejari_property_sub_type_id",
    "ejari_property_type_en", "ejari_property_type_ar", "ejari_property_sub_type_en",
    "ejari_property_sub_type_ar", "property_usage_id", "property_usage_en", "property_usage_ar",
    "rooms", "rooms_en", "parking", "actual_area", "annual_amount", "contract_amount",
    "no_of_prop", "version_number", "version_en", "version_ar", "parcel_id", "area_id",
    "area_name_en", "area_name_ar", "project_name_en", "project_name_ar", "master_project_en",
    "master_project_ar", "is_free_hold", "is_free_hold_en", "is_free_hold_ar",
    "nearest_metro_en", "nearest_metro_ar", "nearest_mall_en", "nearest_mall_ar",
    "nearest_landmark_en", "nearest_landmark_ar", "project_number", "tenant_type_id",
    "tenant_type_en", "tenant_type_ar", "contract_reg_type_id", "contract_reg_type_en",
    "contract_reg_type_ar", "ejari_bus_property_type_id", "ejari_bus_property_type_en",
    "ejari_bus_property_type_ar", "rent_per_sqm",
)  # fmt: skip
RENTAL_EXTRA_COLUMNS = (
    "unit_number", "bedrooms", "dxbi_contract_key", "dxbi_building_name", "source_system",
    "primary_source", "match_status", "is_served", "built_at",
)  # fmt: skip

SALE_COLUMNS = SALE_CONTRACT_COLUMNS + SALE_EXTRA_COLUMNS
RENTAL_COLUMNS = RENTAL_CONTRACT_COLUMNS + RENTAL_EXTRA_COLUMNS

# DLD sales after cut-over and correction handling; one row per transaction_number.
DLD_SALES_BASE = """
    SELECT *
    FROM dld_od_transactions_bronze
    WHERE source_system = 'dld_open_data'
       OR toDate(instance_date) < ifNull(
            (SELECT minOrNull(toDate(instance_date)) FROM dld_od_transactions_bronze
             WHERE source_system = 'dld_open_data'),
            toDate('2149-01-01'))
    ORDER BY transaction_number, scraped_at DESC
    LIMIT 1 BY transaction_number
"""

# DLD rents after cut-over (by registration date, as the silver layer) and exact-duplicate
# collapse. Open-data rows carry no contract_number, so identity is the business content.
_DLD_RENT_KEY = """cityHash64(
        contract_number, line_number, registration_date, start_date, end_date, property_id,
        land_property_id, prop_type_en, prop_sub_type_en, usage_en, rooms, parking, actual_area,
        annual_amount, contract_amount, total_properties, version_number, version_en, parcel_id,
        area_id, project_en, master_project_en, tenant_type_en, contract_reg_type_en,
        ejari_bus_property_type_en, is_free_hold)"""
_DLD_RENTS_BASE_TEMPLATE = f"""
    SELECT *, {_DLD_RENT_KEY} AS dld_rent_key
    FROM dld_od_rents_bronze
    WHERE (source_system = 'dld_open_data'
       OR toDate(registration_date) < ifNull(
            (SELECT minOrNull(toDate(registration_date)) FROM dld_od_rents_bronze
             WHERE source_system = 'dld_open_data'),
            toDate('2149-01-01')))
       {{extra}}
    LIMIT 1 BY dld_rent_key
"""
DLD_RENTS_BASE = _DLD_RENTS_BASE_TEMPLATE.format(extra="")
# Matching only needs the DXBI period; the key is a per-row hash, so filtering first yields the
# same keys as the full base at a fraction of the memory.
_DLD_RENTS_MATCH_BASE = _DLD_RENTS_BASE_TEMPLATE.format(
    extra="AND start_date >= toDateTime('2024-12-01 00:00:00')"
)

# DXBI sales, one row per sale_key. The source table's FINAL collapses on its whole sort key
# (building/size keys included), so a re-normalised address leaves two versions of a sale;
# keep the latest load.
DXBI_SALES_BASE = """
    SELECT * FROM dxbi_sales_unit_events FINAL
    ORDER BY sale_key, loaded_at DESC
    LIMIT 1 BY sale_key
"""

_SALE_MATCHES_SQL = f"""
INSERT INTO `market_sale_matches`
    (dxbi_sale_key, dld_transaction_number, day_gap, size_gap, has_dld_candidate, built_at)
WITH
    dld_sales AS (
        SELECT transaction_number AS dld_key, toDate(instance_date) AS d,
               toUInt64(trans_value) AS price, procedure_area * {SQFT_PER_SQM} AS sqft
        FROM ({DLD_SALES_BASE})
        WHERE group_en = 'Sales' AND trans_value > 0
    ),
    dx AS (
        SELECT sale_key, transaction_date, sale_amount_aed, size_sqft
        FROM ({DXBI_SALES_BASE})
    ),
    -- Every DLD sale at the same price within 30 days: any of these makes a DXBI record a
    -- probable duplicate if it is not paired, so it is never served on top of DLD.
    same_price AS (
        SELECT x.sale_key AS sale_key, s.dld_key AS dld_key, toInt32(abs(x.offset_days)) AS day_gap,
               abs(x.size_sqft - s.sqft) / greatest(s.sqft, 1.0) AS size_gap
        FROM (
            SELECT sale_key, transaction_date + toIntervalDay(offset_days) AS probe_date,
                   offset_days, sale_amount_aed, size_sqft
            FROM dx
            ARRAY JOIN arrayMap(i -> toInt32(i) - 30, range(61)) AS offset_days
        ) AS x
        INNER JOIN dld_sales AS s ON s.d = x.probe_date AND s.price = x.sale_amount_aed
    ),
    -- Pairing needs more: within 3 days, or within 30 days with the same size (±1%).
    candidates AS (SELECT * FROM same_price WHERE day_gap <= 3 OR size_gap <= 0.01),
    best_per_dxbi AS (
        SELECT sale_key, dld_key, day_gap, size_gap FROM candidates
        ORDER BY sale_key, day_gap, size_gap, dld_key
        LIMIT 1 BY sale_key
    ),
    pairs AS (
        SELECT sale_key, dld_key, day_gap, size_gap FROM best_per_dxbi
        ORDER BY dld_key, day_gap, size_gap, sale_key
        LIMIT 1 BY dld_key
    ),
    with_candidate AS (SELECT DISTINCT sale_key FROM same_price)
SELECT
    dx.sale_key,
    p.dld_key,
    toInt16(if(p.dld_key != '', p.day_gap, -1)),
    if(p.dld_key != '', p.size_gap, -1.0),
    toUInt8(dx.sale_key IN (SELECT sale_key FROM with_candidate)),
    now64(3)
FROM dx
LEFT JOIN pairs AS p ON p.sale_key = dx.sale_key
"""

_ROOMS_FROM_BEDROOMS = """multiIf(
    {beds} = 'Studio', 'Studio',
    match({beds}, '^[0-9]+ Beds?$'), concat(extract({beds}, '^([0-9]+)'), ' B/R'),
    '')"""

_OFFPLAN_EN = """multiIf(
    d.is_offplan_en != '', d.is_offplan_en,
    d.reg_type_en = 'Off-Plan Properties', 'Off-Plan',
    d.reg_type_en = 'Existing Properties', 'Ready',
    '')"""
_REG_TYPE_EN = """multiIf(
    d.reg_type_en != '', d.reg_type_en,
    d.is_offplan_en = 'Off-Plan', 'Off-Plan Properties',
    d.is_offplan_en = 'Ready', 'Existing Properties',
    '')"""

_SALE_EVENTS_DLD_SQL = f"""
INSERT INTO `market_sale_events` ({", ".join(SALE_COLUMNS)})
SELECT
    d.row_key, d.run_id, d.scraped_at,
    if(d.transaction_number != '', d.transaction_number, d.row_key),
    d.transaction_number, d.instance_date,
    d.group_id, if(d.group_en = 'Mortgage', 'Mortgages', d.group_en), d.group_ar,
    d.procedure_id, d.procedure_en, d.procedure_ar,
    d.procedure_area, d.actual_area, d.trans_value, d.trans_value,
    d.total_buyer, d.total_seller, d.property_id, d.property_type_id,
    d.prop_type_en, d.prop_type_ar, d.property_sub_type_id, d.prop_sb_type_en, d.prop_sb_type_ar,
    d.usage_id, d.usage_en, d.usage_ar,
    if(d.rooms_en != '', d.rooms_en, {_ROOMS_FROM_BEDROOMS.format(beds="x.bedrooms")}),
    d.rooms_ar, d.parking, d.parking != '', d.building_age, d.parcel_id, d.area_id,
    d.area_en, d.area_ar, d.project_en, d.project_ar, d.master_project_en, d.master_project_ar,
    d.is_free_hold, d.is_free_hold_en, d.is_free_hold_ar,
    toUInt8({_OFFPLAN_EN} = 'Off-Plan'), {_OFFPLAN_EN}, d.is_offplan_ar,
    d.nearest_metro_en, d.nearest_metro_ar, d.nearest_mall_en, d.nearest_mall_ar,
    d.nearest_landmark_en, d.nearest_landmark_ar, d.project_number,
    if(d.building_name_en != '', d.building_name_en, x.building_name), d.building_name_ar,
    d.reg_type_id, {_REG_TYPE_EN}, d.reg_type_ar,
    if(d.meter_sale_price > 0, d.meter_sale_price, d.trans_value / nullIf(d.procedure_area, 0)),
    d.rent_value, d.meter_rent_price,
    d.no_of_parties_role_1, d.no_of_parties_role_2, d.no_of_parties_role_3,
    x.unit_number, x.bedrooms, x.market_status, m.dxbi_sale_key, x.building_name,
    if(m.dxbi_sale_key != '', x.transaction_date, NULL),
    d.source_system,
    if(m.dxbi_sale_key != '', 'dxbi', 'dld'),
    if(m.dxbi_sale_key != '', 'matched', 'dld_only'),
    1,
    now64(3)
FROM ({DLD_SALES_BASE}) AS d
LEFT JOIN (SELECT dxbi_sale_key, dld_transaction_number FROM market_sale_matches
           WHERE dld_transaction_number != '') AS m
    ON m.dld_transaction_number = d.transaction_number
LEFT JOIN ({DXBI_SALES_BASE}) AS x ON x.sale_key = m.dxbi_sale_key
"""


def _learned_name_maps(*, staging: str, dxbi_source: str, dxbi_key: str, staging_key: str) -> str:
    """CTEs mapping DXBI area/project names to the DLD vocabulary.

    Learned from the rows matched in this same build: a DXBI name maps to the DLD name its
    matched rows carry at least 80% of the time (e.g. "Dubai Marina" -> "Marsa Dubai"). Without
    it, DXBI-only rows add pseudo-areas to every area list.
    """
    maps = []
    for field, dld_field in (("area_name", "area_name_en"), ("project_name", "project_name_en")):
        maps.append(
            f"""{field}_map AS (
        SELECT dxbi_name, argMax(dld_name, n) AS dld_name
        FROM (
            SELECT src.{field} AS dxbi_name, s.{dld_field} AS dld_name, count() AS n
            FROM `{staging}` AS s
            INNER JOIN ({dxbi_source}) AS src ON src.{dxbi_key} = s.{staging_key}
            WHERE s.match_status = 'matched' AND s.{dld_field} != '' AND src.{field} != ''
            GROUP BY dxbi_name, dld_name
        )
        GROUP BY dxbi_name
        HAVING max(n) / sum(n) >= 0.8
    )"""
        )
    return "WITH\n    " + ",\n    ".join(maps)


_SALE_EVENTS_DXBI_SQL = f"""
INSERT INTO `market_sale_events` ({", ".join(SALE_COLUMNS)})
{
    _learned_name_maps(
        staging="market_sale_events",
        dxbi_source=DXBI_SALES_BASE,
        dxbi_key="sale_key",
        staging_key="dxbi_sale_key",
    )
}
SELECT
    concat('dxbi:', x.sale_key), '', '', concat('dxbi:', x.sale_key), '',
    toDateTime(x.transaction_date),
    0, 'Sales', '', 0, '', '',
    x.size_sqft / {SQFT_PER_SQM}, x.size_sqft / {SQFT_PER_SQM},
    toInt64(x.sale_amount_aed), toInt64(x.sale_amount_aed),
    0, 0, 0, 0,
    multiIf(x.property_type IN ('Villa', 'Townhouse'), 'Villa', x.property_type = 'Plot', 'Land',
            x.property_type = 'Building', 'Building', x.property_type = '', '', 'Unit'),
    '', 0,
    multiIf(x.property_type = 'Apartment', 'Flat', x.property_type IN ('Villa', 'Townhouse'), 'Villa',
            x.property_type = 'Plot', '', x.property_type),
    '', 0,
    multiIf(x.property_type IN ('Apartment', 'Villa', 'Townhouse'), 'Residential',
            x.property_type IN ('Office', 'Shop', 'Workshop', 'Warehouse'), 'Commercial', ''),
    '',
    {_ROOMS_FROM_BEDROOMS.format(beds="x.bedrooms")}, '', '', 0, 0, '', 0,
    if(am.dld_name != '', am.dld_name, x.area_name), '',
    if(pm.dld_name != '', pm.dld_name, x.project_name), '', '', '',
    0, '', '',
    toUInt8(x.market_status = 'Offplan'),
    multiIf(x.market_status = 'Offplan', 'Off-Plan', x.market_status = 'Ready', 'Ready', ''), '',
    '', '', '', '', '', '', '',
    x.building_name, '',
    0,
    multiIf(x.market_status = 'Offplan', 'Off-Plan Properties',
            x.market_status = 'Ready', 'Existing Properties', ''),
    '',
    x.sale_amount_aed / nullIf(x.size_sqft / {SQFT_PER_SQM}, 0),
    0, 0, 0, 0, 0,
    x.unit_number, x.bedrooms, x.market_status, x.sale_key, x.building_name, x.transaction_date,
    'dxbi', 'dxbi',
    if(m.has_dld_candidate = 1, 'dxbi_probable_duplicate', 'dxbi_only'),
    toUInt8(m.has_dld_candidate = 0),
    now64(3)
FROM market_sale_matches AS m
INNER JOIN ({DXBI_SALES_BASE}) AS x ON x.sale_key = m.dxbi_sale_key
LEFT JOIN area_name_map AS am ON am.dxbi_name = x.area_name
LEFT JOIN project_name_map AS pm ON pm.dxbi_name = x.project_name
WHERE m.dld_transaction_number = ''
"""


# Rent amounts and dates are not location-specific (thousands of leases are "AED 50,000 from
# the 1st"), so pairing on them alone matched contracts across areas. Both sides are keyed by
# location in the DLD area vocabulary. A DXBI area takes the DLD area its matched *sales* carry
# most often (sales pair on exact price, so that link is reliable; >= 50% of >= 20 sales), else
# a DLD area with the same name (old-Dubai areas with few sales, e.g. "Al Karama"). DXBI rows
# with neither stay unpaired and are only labelled. Requires market_sale_events built first.
def _area_name_key(expr: str) -> str:
    """Lower-case area name with DXBI's trailing numeral spelled as DLD writes it.

    DXBI "Jabal Ali Industrial 1" is DLD "Jabal Ali Industrial First".
    """
    low = f"lowerUTF8(trim({expr}))"
    return (
        f"if(match({low}, ' [1-6]$'), concat(substring({low}, 1, length({low}) - 1), "
        f"transform(right({low}, 1), ['1', '2', '3', '4', '5', '6'], "
        f"['first', 'second', 'third', 'fourth', 'fifth', 'sixth'], '')), {low})"
    )


# DXBI rental area -> DLD area, used both to key pairing and to name DXBI-only rows:
# the DLD area its matched *sales* carry most often (>= 50% of >= 20 sales), else the DLD area
# with the same (ordinal-normalised) name. Joined as `sm` and `n` on a rental row `r`/`x`.
_RENTAL_AREA_CTES = f"""
    sales_area_map AS (
        SELECT dxbi_area, argMax(dld_area, n) AS dld_area
        FROM (
            SELECT x.area_name AS dxbi_area, e.area_name_en AS dld_area, count() AS n
            FROM market_sale_events AS e
            INNER JOIN ({DXBI_SALES_BASE}) AS x ON x.sale_key = e.dxbi_sale_key
            WHERE e.match_status = 'matched' AND e.area_name_en != '' AND x.area_name != ''
            GROUP BY dxbi_area, dld_area
        )
        GROUP BY dxbi_area
        HAVING sum(n) >= 20 AND max(n) / sum(n) >= 0.5
    ),
    dld_area_names AS (
        SELECT lowerUTF8(area_en) AS name_key, any(area_en) AS dld_area
        FROM dld_od_rents_bronze WHERE area_en != '' GROUP BY name_key
    )"""


def _rental_area_joins(alias: str) -> str:
    return (
        f"LEFT JOIN sales_area_map AS sm ON sm.dxbi_area = {alias}.area_name\n"
        f"LEFT JOIN dld_area_names AS n ON n.name_key = {_area_name_key(f'{alias}.area_name')}"
    )


_RENTAL_DLD_AREA = "multiIf(sm.dld_area != '', sm.dld_area, n.dld_area != '', n.dld_area, '')"

_RENTAL_MATCH_INPUTS = f"""{_RENTAL_AREA_CTES},
    dld AS (
        SELECT dld_rent_key, toDate(start_date) AS s, toDate(end_date) AS e,
               toUInt64(greatest(contract_amount, 0)) AS contract_amt,
               toUInt64(greatest(annual_amount, 0)) AS annual_amt,
               actual_area * {SQFT_PER_SQM} AS sqft,
               toInt64(round(actual_area)) AS sqm,
               area_en AS loc
        FROM ({_DLD_RENTS_MATCH_BASE})
    ),
    dx AS (
        SELECT r.contract_key AS contract_key, r.lease_start AS lease_start, r.lease_end AS lease_end,
               r.contract_amount_aed AS contract_amount_aed, r.annual_rent_aed AS annual_rent_aed,
               r.size_sqft AS size_sqft, toInt64(round(r.size_sqft / {SQFT_PER_SQM})) AS sqm,
               {_RENTAL_DLD_AREA} AS loc
        FROM dxbi_rental_events AS r FINAL
        {_rental_area_joins("r")}
    )"""


def _rental_rank_pairing_sql(
    *,
    tier: int,
    dx_keys: tuple[str, ...],
    dld_keys: tuple[str, ...],
    dx_filter: str,
    dld_filter: str,
) -> str:
    """Pair still-unpaired DXBI and DLD rentals one-to-one inside each key group.

    Both sides are numbered by floor area within the group and row n pairs with row n, so a
    group of n DXBI and m DLD rows yields min(n, m) pairs with no fan-out; the rest fall
    through to the next tier. (A pairwise candidate join fanned out to ~198M pairs.)
    """
    dx_cols = ", ".join(f"{key} AS k{i}" for i, key in enumerate(dx_keys))
    dld_cols = ", ".join(f"{key} AS k{i}" for i, key in enumerate(dld_keys))
    partition = ", ".join(f"k{i}" for i in range(len(dx_keys)))
    join_on = " AND ".join(f"a.k{i} = b.k{i}" for i in range(len(dx_keys)))
    return f"""
INSERT INTO `market_rental_matches`
    (dxbi_contract_key, dld_rent_key, match_tier, end_day_gap, size_gap, has_dld_candidate, built_at)
WITH {_RENTAL_MATCH_INPUTS}
SELECT a.contract_key, b.dld_rent_key, {tier}, toInt32(abs(dateDiff('day', b.e, a.lease_end))),
       abs(a.size_sqft - b.sqft) / greatest(b.sqft, 1.0), 1, now64(3)
FROM (
    SELECT contract_key, lease_end, size_sqft, {dx_cols},
           row_number() OVER (PARTITION BY {partition} ORDER BY size_sqft, contract_key) AS rn
    FROM dx
    WHERE {dx_filter}
      AND contract_key NOT IN (SELECT dxbi_contract_key FROM `market_rental_matches`)
) AS a
INNER JOIN (
    SELECT dld_rent_key, e, sqft, {dld_cols},
           row_number() OVER (PARTITION BY {partition} ORDER BY sqft, dld_rent_key) AS rn
    FROM dld
    WHERE {dld_filter}
      AND dld_rent_key NOT IN (SELECT dld_rent_key FROM `market_rental_matches`)
) AS b ON {join_on} AND a.rn = b.rn
{_HEAVY_QUERY_SETTINGS}
"""


_RENTAL_MATCH_STATEMENTS = (
    # Tier 0: same lease period and contract amount (99% of pairs agree on the end date).
    _rental_rank_pairing_sql(
        tier=0,
        dx_keys=("loc", "lease_start", "lease_end", "contract_amount_aed"),
        dld_keys=("loc", "s", "e", "contract_amt"),
        dx_filter="loc != '' AND contract_amount_aed > 0",
        dld_filter="loc != '' AND contract_amt > 0",
    ),
    # Tier 1: same lease period and annual amount (DXBI annualises some contracts).
    _rental_rank_pairing_sql(
        tier=1,
        dx_keys=("loc", "lease_start", "lease_end", "annual_rent_aed"),
        dld_keys=("loc", "s", "e", "annual_amt"),
        dx_filter="loc != '' AND annual_rent_aed > 0",
        dld_filter="loc != '' AND annual_amt > 0",
    ),
    # Tier 2: same lease period and floor area with a different amount — the same Ejari
    # contract reported with a different rent (91% of the first build's DXBI-only rows).
    _rental_rank_pairing_sql(
        tier=2,
        dx_keys=("loc", "lease_start", "lease_end", "sqm"),
        dld_keys=("loc", "s", "e", "sqm"),
        dx_filter="loc != '' AND sqm > 0",
        dld_filter="loc != '' AND sqm > 0",
    ),
    # Tier 3: same start and contract amount where the end dates disagree.
    _rental_rank_pairing_sql(
        tier=3,
        dx_keys=("loc", "lease_start", "contract_amount_aed"),
        dld_keys=("loc", "s", "contract_amt"),
        dx_filter="loc != '' AND contract_amount_aed > 0",
        dld_filter="loc != '' AND contract_amt > 0",
    ),
    # Every DXBI rental left unpaired gets its ledger row. A DLD row with the same start and
    # amount, or the same period and floor area (±1 m²), means DLD already holds the contract.
    f"""
INSERT INTO `market_rental_matches`
    (dxbi_contract_key, dld_rent_key, match_tier, end_day_gap, size_gap, has_dld_candidate, built_at)
WITH {_RENTAL_MATCH_INPUTS}
SELECT dx.contract_key, 0, 255, -1, -1.0,
       toUInt8(
           (dx.contract_amount_aed > 0
            AND (dx.lease_start, dx.contract_amount_aed) IN (SELECT s, contract_amt FROM dld))
           OR (dx.annual_rent_aed > 0
               AND (dx.lease_start, dx.annual_rent_aed) IN (SELECT s, annual_amt FROM dld))
           OR (dx.sqm > 0 AND (
               (dx.lease_start, dx.lease_end, dx.sqm - 1) IN (SELECT s, e, sqm FROM dld)
               OR (dx.lease_start, dx.lease_end, dx.sqm) IN (SELECT s, e, sqm FROM dld)
               OR (dx.lease_start, dx.lease_end, dx.sqm + 1) IN (SELECT s, e, sqm FROM dld)))
       ),
       now64(3)
FROM dx
WHERE dx.contract_key NOT IN (SELECT dxbi_contract_key FROM `market_rental_matches`)
{_HEAVY_QUERY_SETTINGS}
""",
)

_RENTAL_EVENTS_DLD_SQL = f"""
INSERT INTO `market_rental_events` ({", ".join(RENTAL_COLUMNS)})
SELECT
    d.row_key, d.run_id, d.scraped_at,
    if(d.contract_number != '', d.contract_number, d.row_key), d.contract_number, d.line_number,
    d.registration_date, d.start_date, d.end_date, d.property_id, d.land_property_id,
    d.ejari_property_type_id, d.ejari_property_sub_type_id,
    d.prop_type_en, d.prop_type_ar, d.prop_sub_type_en, d.prop_sub_type_ar,
    d.property_usage_id, d.usage_en, d.usage_ar,
    d.rooms, d.rooms, d.parking, d.actual_area, d.annual_amount, d.contract_amount,
    d.total_properties, d.version_number, if(d.version_en = 'Renew', 'Renewed', d.version_en),
    d.version_ar, d.parcel_id, d.area_id, d.area_en, d.area_ar, d.project_en, d.project_ar,
    d.master_project_en, d.master_project_ar, d.is_free_hold, d.is_free_hold_en, d.is_free_hold_ar,
    d.nearest_metro_en, d.nearest_metro_ar, d.nearest_mall_en, d.nearest_mall_ar,
    d.nearest_landmark_en, d.nearest_landmark_ar, d.project_number,
    d.tenant_type_id, d.tenant_type_en, d.tenant_type_ar,
    d.contract_reg_type_id, d.contract_reg_type_en, d.contract_reg_type_ar,
    d.ejari_bus_property_type_id, d.ejari_bus_property_type_en, d.ejari_bus_property_type_ar,
    d.annual_amount / nullIf(d.actual_area, 0),
    x.unit_number, x.bedrooms, m.dxbi_contract_key, x.building_name,
    d.source_system,
    if(m.dxbi_contract_key != '', 'dxbi', 'dld'),
    if(m.dxbi_contract_key != '', 'matched', 'dld_only'),
    1,
    now64(3)
FROM ({DLD_RENTS_BASE}) AS d
LEFT JOIN (SELECT dxbi_contract_key, dld_rent_key FROM market_rental_matches
           WHERE dld_rent_key != 0) AS m
    ON m.dld_rent_key = d.dld_rent_key
LEFT JOIN (SELECT * FROM dxbi_rental_events FINAL) AS x ON x.contract_key = m.dxbi_contract_key
{_HEAVY_QUERY_SETTINGS}
"""

_RENTAL_EVENTS_DXBI_SQL = f"""
INSERT INTO `market_rental_events` ({", ".join(RENTAL_COLUMNS)})
{
    _learned_name_maps(
        staging="market_rental_events",
        dxbi_source="SELECT * FROM dxbi_rental_events FINAL",
        dxbi_key="contract_key",
        staging_key="dxbi_contract_key",
    )
},{_RENTAL_AREA_CTES}
SELECT
    concat('dxbi:', x.contract_key), '', '', concat('dxbi:', x.contract_key),
    x.source_contract_id, 0,
    toDateTime(x.lease_start), toDateTime(x.lease_start), toDateTime(x.lease_end),
    0, 0, 0, 0,
    multiIf(x.property_type = 'Apartment', 'Flat', x.property_type IN ('Villa', 'Townhouse'), 'Villa',
            x.property_type),
    '', '', '', 0,
    multiIf(x.property_type IN ('Apartment', 'Villa', 'Townhouse'), 'Residential',
            x.property_type = 'Commercial', 'Commercial', ''),
    '', '', '', '',
    x.size_sqft / {SQFT_PER_SQM}, toInt64(x.annual_rent_aed), toInt64(x.contract_amount_aed),
    1, 0, x.contract_state, '', '', 0,
    -- Same area resolution as pairing, then the rental-learned map, else DXBI's own name.
    multiIf({_RENTAL_DLD_AREA} != '', {
    _RENTAL_DLD_AREA
}, am.dld_name != '', am.dld_name, x.area_name),
    '',
    if(pm.dld_name != '', pm.dld_name, x.project_name), '', '', '',
    0, '', '', '', '', '', '', '', '', '',
    0, '', '', 0, '', '', 0, '', '',
    x.annual_rent_aed / nullIf(x.size_sqft / {SQFT_PER_SQM}, 0),
    x.unit_number, x.bedrooms, x.contract_key, x.building_name,
    'dxbi', 'dxbi',
    if(m.has_dld_candidate = 1, 'dxbi_probable_duplicate', 'dxbi_only'),
    toUInt8(m.has_dld_candidate = 0),
    now64(3)
FROM market_rental_matches AS m
INNER JOIN (SELECT * FROM dxbi_rental_events FINAL) AS x ON x.contract_key = m.dxbi_contract_key
LEFT JOIN area_name_map AS am ON am.dxbi_name = x.area_name
LEFT JOIN project_name_map AS pm ON pm.dxbi_name = x.project_name
{_rental_area_joins("x")}
WHERE m.dld_rent_key = 0
"""
