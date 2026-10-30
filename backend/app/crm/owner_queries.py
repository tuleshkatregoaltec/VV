from __future__ import annotations

import asyncio
import hashlib
import json
from decimal import ROUND_FLOOR

from clickhouse_connect.driver.external import ExternalData

from app.clickhouse.client import query
from app.crm.import_normalization import positive_decimal
from app.crm.registry_locations import RegistryLocationIndex, normalize_registry_locations
from app.market.reference import normalize_unit_text_sql, unit_lookup_key, unit_lookup_key_sql

_UNIT_LOOKUP_KEY = unit_lookup_key_sql("unit_number")
_UNIT_TEXT = normalize_unit_text_sql("unit_number")
_SHORT_UNIT_LOOKUP_KEY = unit_lookup_key_sql(
    "if(startsWith(numeric_unit, 'TAG-'), arrayElement(splitByChar('-', numeric_unit), -1), numeric_unit)"
)


def _lookup_scope(parameters):
    if "scopes" not in parameters:
        return "", None
    scopes = parameters["scopes"]
    if not scopes:
        return " AND 0", None
    external = ExternalData(
        file_name="owner_lookup",
        data="\n".join(
            json.dumps({"location": name, "unit": unit}) for name, unit in scopes
        ).encode(),
        fmt="JSONEachRow",
        structure="location String, unit String",
    )
    unit = _UNIT_LOOKUP_KEY
    suffix = "toString(toUInt64OrZero(extract(unit_number, '([0-9]+)$')))"
    terms = []
    for field in ("building_name", "project_name", "area_name"):
        name = f"replaceRegexpAll(lowerUTF8({field}), '[^a-z0-9]', '')"
        terms.append(f"({name}, {unit}) IN (SELECT location, unit FROM owner_lookup)")
        terms.append(
            f"(lowerUTF8(property_type) IN ('villa','villas','townhouse','townhouses') AND ({name}, {suffix}) IN (SELECT location, unit FROM owner_lookup))"
        )
    return " AND (" + " OR ".join(terms) + ")", external


async def fetch_canonical_building_keys(parameters):
    if not parameters["name_keys"] or not parameters["community_keys"]:
        return []
    # Large imports exceed ClickHouse's HTTP form-field limit with bound arrays.
    # Stream both independent key sets without constructing their cross product.
    external = ExternalData(
        file_name="owner_building_keys",
        data="\n".join(
            json.dumps({"value": value, "kind": kind})
            for kind, field in ((1, "name_keys"), (2, "community_keys"))
            for value in sorted(set(parameters[field]))
        ).encode(),
        fmt="JSONEachRow",
        structure="value String, kind UInt8",
    )
    return await query(
        """SELECT DISTINCT name_key, community_key, project_key, building_id
           FROM analytics_building_keys
           WHERE name_key IN (SELECT value FROM owner_building_keys WHERE kind = 1)
             AND community_key IN (SELECT value FROM owner_building_keys WHERE kind = 2)""",
        external_data=external,
    )


async def fetch_place_hierarchy():
    """Every DXBI building key with its community and project (the Analytics hierarchy)."""
    return await query(
        """SELECT DISTINCT name_key, community_key, project_key, building_id
           FROM analytics_building_keys"""
    )


async def fetch_import_locations():
    return await query(
        """SELECT DISTINCT arrayJoin([area_name, project_name]) AS name,
                           area_name, project_name
           FROM dxbi_sales_unit_events WHERE area_name != '' OR project_name != ''"""
    )


async def fetch_import_context_sales(parameters):
    return await query(
        rf"""SELECT transaction_date, sale_amount_aed, unit_number,
                   {_UNIT_LOOKUP_KEY} AS unit_key,
                   building_name, building_key, project_name, area_name, area_key,
                   property_type, market_status, sale_key
            FROM dxbi_sales_unit_events FINAL
            WHERE (area_name IN {{locations:Array(String)}}
                   OR project_name IN {{locations:Array(String)}})
              AND transaction_date BETWEEN {{start_date:Date}} AND {{end_date:Date}}
            SETTINGS max_threads=2, max_memory_usage=2000000000""",
        parameters,
    )


async def fetch_cadastral_lands(parameters: dict) -> list[dict]:
    return await query(
        """SELECT DISTINCT area_id, area_en, master_project_en, project_en,
                  land_number, land_sub_number
           FROM dld_od_lands_bronze
           WHERE land_number IN {land_numbers:Array(String)}""",
        parameters,
    )


async def fetch_transaction_signatures(parameters):
    # The warehouse currently stores UInt64 consideration. Integer buckets are
    # only a coarse query superset, not a conversion of source/event prices.
    # Include fractional endpoints; the shared Decimal engine tests exact deltas.
    buckets = set()
    for value in parameters["prices"]:
        amount = positive_decimal(value)
        if amount is not None:
            lower = int((amount - 2).to_integral_value(rounding=ROUND_FLOOR))
            upper = int((amount + 2).to_integral_value(rounding=ROUND_FLOOR))
            buckets.update(range(max(0, lower), upper + 1))
    if not buckets:
        return []
    scope, external = _lookup_scope(parameters)
    rows = await query(
        f"""
            SELECT transaction_date, sale_amount_aed, 0 AS contract_amount_aed,
                   0 AS annual_rent_aed, {_UNIT_LOOKUP_KEY} AS unit_key,
                   unit_number, building_name, building_key, project_name,
                   area_name, area_key, property_type, size_sqft,
                   sale_key, sale_key AS event_key, detail_url, 'sale' AS event_family, '' AS location_name
            FROM dxbi_sales_unit_events FINAL
            WHERE floor(sale_amount_aed) IN {{amount_buckets:Array(Int64)}}
            {scope}
            UNION ALL
            SELECT lease_start AS transaction_date, 0 AS sale_amount_aed,
                   contract_amount_aed, annual_rent_aed, {_UNIT_LOOKUP_KEY} AS unit_key,
                   unit_number, building_name, '' AS building_key, project_name,
                   area_name, '' AS area_key, property_type, size_sqft,
                   '' AS sale_key, event_key, '' AS detail_url, 'rental' AS event_family, location_name
            FROM dxbi_rental_events FINAL
            WHERE (floor(contract_amount_aed) IN {{amount_buckets:Array(Int64)}}
               OR floor(annual_rent_aed) IN {{amount_buckets:Array(Int64)}})
            {scope}
            SETTINGS max_execution_time=25, max_result_rows=500000, result_overflow_mode='throw', max_threads=2, max_memory_usage=2000000000
        """,
        {"amount_buckets": sorted(buckets)},
        **({"external_data": external} if external is not None else {}),
    )

    if rows:
        places = await query(
            "SELECT location_id, path_key, building_key, area_key, match_rank, "
            "building_label, project_label, area_label FROM dxbi_places"
        )
        catalog = RegistryLocationIndex(places)
        return [normalize_registry_locations(row, catalog) for row in rows]
    return rows


async def fetch_near_transaction_signatures(parameters):
    """Legacy entry point, with the same complete amount universe as recovery."""
    return await fetch_transaction_signatures(parameters)


async def fetch_unit_sales(parameters):
    scope, external = _lookup_scope(parameters)
    rows = await query(
        f"""
            SELECT
                {_UNIT_LOOKUP_KEY} AS unit_key,
                unit_number,
                building_name,
                building_key,
                project_name,
                area_name,
                area_key,
                property_type,
                bedrooms,
                size_sqft,
                transaction_date,
                sale_amount_aed,
                market_status,
                sale_key,
                detail_url
            FROM dxbi_sales_unit_events FINAL
            WHERE unit_key
                IN {{unit_keys:Array(String)}}
            {scope}
            ORDER BY unit_key, transaction_date
            SETTINGS max_execution_time=25, max_result_rows=500000, result_overflow_mode='throw', max_threads=2, max_memory_usage=2000000000
            """,
        {"unit_keys": parameters["unit_keys"]},
        **({"external_data": external} if external is not None else {}),
    )
    if rows and "scopes" in parameters:
        catalog = RegistryLocationIndex(await fetch_registry_places())
        return [normalize_registry_locations(row, catalog) for row in rows]
    return rows


async def fetch_rental_source_columns():
    return await query(
        "SELECT count() AS has_unit FROM system.columns WHERE database=currentDatabase() "
        "AND table='dxbi_rental_unit_candidates' AND name='unit_number'"
    )


async def fetch_rental_evidence(parameters, has_source_unit: bool):
    source_unit = "c.unit_number" if has_source_unit else "''"
    return await query(
        rf"""
            WITH
                if({source_unit} != '', {source_unit}, m.unit_number) AS observed_unit,
                replaceRegexpAll(upperUTF8(replaceAll(observed_unit, '–', '-')), '\\s+', '') AS compact_unit,
                if(match(compact_unit, '^\\d+\\.0$'), substring(compact_unit, 1, length(compact_unit)-2), compact_unit) AS numeric_unit,
                if(startsWith(numeric_unit, 'TAG-'), arrayElement(splitByChar('-', numeric_unit), -1), numeric_unit) AS normalized_unit
            SELECT
                c.event_key AS event_key,
                c.unit_candidate_key AS unit_candidate_key,
                c.building_name AS building_name,
                c.project_name AS project_name,
                c.area_name AS area_name,
                c.property_type AS property_type,
                c.lease_end AS lease_end,
                c.annual_rent_aed AS annual_rent_aed,
                observed_unit AS unit_number,
                normalized_unit AS unit_key,
                if({source_unit} != '', 'source_unit', 'sale_inference') AS rental_match_method
            FROM dxbi_rental_unit_candidates AS c FINAL
            LEFT JOIN dxbi_rental_sale_matches AS m FINAL USING (unit_candidate_key)
            WHERE
                ({source_unit} != '' OR m.match_status = 'unique')
                AND normalized_unit IN {{units:Array(String)}}
                AND c.lease_end >= {{window_start:Date}}
                AND c.lease_end <= {{window_end:Date}}
            ORDER BY ({source_unit} != '') DESC, c.lease_end DESC, c.unit_candidate_key, c.event_key
            SETTINGS max_threads=2, max_memory_usage=2000000000
            """,
        parameters,
    )


async def fetch_owner_property_signatures(parameters):
    return await query(
        f"""
        SELECT
            transaction_date,
            sale_amount_aed,
            {_UNIT_LOOKUP_KEY} AS unit_key,
            unit_number,
            building_name,
            building_key,
            project_name,
            area_name,
            area_key,
            property_type,
            market_status,
            bedrooms,
            size_sqft,
            built_up_area_sqft,
            price_per_sqft_aed,
            sale_key
        FROM dxbi_sales_unit_events FINAL
        WHERE transaction_date IN {{dates:Array(Date)}}
          AND sale_amount_aed IN {{prices:Array(UInt64)}}
        """,
        parameters,
    )


async def fetch_registry_sales_evidence(parameters):
    return await query(
        """
                SELECT
                    building_name,
                    unit_number,
                    transaction_date,
                    sale_amount_aed,
                    ltv_pct,
                    seller_type,
                    detail_url
                FROM dxbi_sales_unit_events FINAL
                WHERE
                    lowerUTF8(building_name) IN {buildings:Array(String)}
                    AND lowerUTF8(unit_number) IN {units:Array(String)}
                ORDER BY transaction_date DESC
                LIMIT 500
                """,
        parameters,
    )


async def fetch_registry_lease_evidence(parameters):
    return await query(
        """
                SELECT
                    c.unit_candidate_key,
                    c.lease_start,
                    c.lease_end,
                    c.annual_rent_aed,
                    c.contract_state,
                    c.observed_contracts
                FROM dxbi_rental_unit_candidates AS c FINAL
                WHERE c.unit_candidate_key IN {candidate_keys:Array(String)}
                LIMIT 200
                """,
        parameters,
    )


async def fetch_sales_by_keys(parameters):
    return await query(
        f"""
            SELECT
                {_UNIT_LOOKUP_KEY} AS unit_key,
                unit_number,
                building_name,
                building_key,
                project_name,
                area_name,
                area_key,
                sale_key
            FROM dxbi_sales_unit_events FINAL
            WHERE sale_key IN {{sale_keys:Array(String)}}
            """,
        parameters,
    )


async def fetch_unit_sales_by_short_key(parameters):
    # short_unit_key applies the import-side unit normalization (TAG-AL2-237 -> 237, 101.0 -> 101)
    # to registry units, so both sides are compared in the same form.
    return await query(
        rf"""
            WITH
                replaceRegexpAll(upperUTF8({_UNIT_TEXT}), '\\s+', '') AS compact_unit,
                if(match(compact_unit, '^\\d+\\.0$'), substring(compact_unit, 1, length(compact_unit)-2), compact_unit) AS numeric_unit,
                {_SHORT_UNIT_LOOKUP_KEY} AS short_unit_key
            SELECT
                {_UNIT_LOOKUP_KEY} AS unit_key,
                short_unit_key,
                unit_number,
                property_type,
                building_name,
                building_key,
                project_name,
                area_name,
                area_key,
                transaction_date,
                sale_amount_aed,
                sale_key,
                detail_url
            FROM dxbi_sales_unit_events FINAL
            WHERE short_unit_key IN {{unit_keys:Array(String)}}
            ORDER BY unit_key, transaction_date
            """,
        parameters,
    )


async def fetch_assessment_building_aliases(parameters):
    return await query(
        """SELECT name_key, building_id, community_key, project_key FROM analytics_building_keys
           WHERE building_id IN (
               SELECT building_id FROM analytics_building_keys
               WHERE name_key IN {names:Array(String)}
           )
           SETTINGS max_execution_time=20, max_threads=2, max_memory_usage=1000000000""",
        parameters,
    )


async def fetch_assessment_source_fingerprint() -> str:
    """Identify the physical DXBI/alias inputs, not a canonical market release.

    Background merges may conservatively invalidate this marker. The mutable
    inputs do not provide an atomic, validated publication contract.
    """
    tables = ["analytics_building_keys", "dxbi_sales_unit_events"]
    async with asyncio.timeout(3):
        rows = await query(
            """SELECT t.name AS name, toString(t.uuid) AS uuid,
                      t.engine AS engine, p.parts AS parts,
                      ifNull(m.pending, 0) AS pending
               FROM system.tables AS t
               LEFT JOIN (
                   SELECT table AS name,
                          arraySort(groupArray((name, toString(hash_of_all_files)))) AS parts
                   FROM system.parts
                   WHERE database = currentDatabase() AND active AND table IN {tables:Array(String)}
                   GROUP BY table
               ) AS p ON p.name = t.name
               LEFT JOIN (
                   SELECT table AS name, count() AS pending
                   FROM system.mutations
                   WHERE database = currentDatabase() AND NOT is_done
                     AND table IN {tables:Array(String)}
                   GROUP BY table
               ) AS m ON m.name = t.name
               WHERE t.database = currentDatabase() AND t.name IN {tables:Array(String)}
               ORDER BY t.name
               SETTINGS max_execution_time=2, max_threads=1""",
            {"tables": tables},
        )
    if [row["name"] for row in rows] != tables or any(
        "MergeTree" not in str(row["engine"]) or row["pending"] for row in rows
    ):
        raise RuntimeError("Ownership evidence sources are missing or mutating")
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


async def fetch_assessment_sales(parameters):
    properties = parameters["properties"]
    if not properties:
        return []
    # Typed multipart data avoids URL/form limits without interpolating values
    # into SQL. Only normalized public property lookup keys leave PostgreSQL.
    external = ExternalData(
        file_name="owner_properties",
        data="\n".join(
            json.dumps({"location": name, "unit": unit}) for name, unit in properties
        ).encode(),
        fmt="JSONEachRow",
        structure="location String, unit String",
    )
    scope = "(SELECT location, unit FROM owner_properties)"
    rows = await query(
        f"""SELECT {_UNIT_LOOKUP_KEY} AS unit_key, unit_number, building_name,
                   building_key, project_name, area_name, area_key, property_type,
                   bedrooms, size_sqft, transaction_date, sale_amount_aed,
                   market_status, sale_key, detail_url
            FROM dxbi_sales_unit_events FINAL
            WHERE (replaceRegexpAll(lowerUTF8(building_name), '[^a-z0-9]', ''), unit_key)
                      IN {scope}
               OR (replaceRegexpAll(lowerUTF8(project_name), '[^a-z0-9]', ''), unit_key)
                      IN {scope}
            ORDER BY unit_key, transaction_date
            LIMIT 500001
            SETTINGS max_execution_time=25, max_threads=2, max_memory_usage=2000000000""",
        external_data=external,
    )
    if len(rows) > 500000:
        raise RuntimeError("Ownership registry evidence exceeds the bounded query size")
    if rows:
        catalog = RegistryLocationIndex(await fetch_registry_places())
        return [normalize_registry_locations(row, catalog) for row in rows]
    return rows


async def fetch_property_identity_candidates(parameters):
    """Complete full-ID/villa-suffix query superset; shared matcher proves scope."""
    scope, external = _lookup_scope(parameters)
    parameters = {"units": sorted({unit_lookup_key(value) for value in parameters["identifiers"]})}
    rows = await query(
        f"""SELECT unit_number, building_name, project_name, area_name, property_type,
                   size_sqft, sale_key AS event_key, sale_amount_aed,
                   transaction_date, 'sale' AS event_family, '' AS location_name
            FROM dxbi_sales_unit_events FINAL
            WHERE ({_UNIT_LOOKUP_KEY} IN {{units:Array(String)}}
               OR (lowerUTF8(property_type) IN ('villa','villas','townhouse','townhouses')
                   AND toString(toUInt64OrZero(extract(unit_number, '([0-9]+)$'))) IN {{units:Array(String)}}))
            {scope}
            UNION ALL
            SELECT unit_number, building_name, project_name, area_name, property_type,
                   size_sqft, event_key, 0 AS sale_amount_aed, lease_start AS transaction_date,
                   'rental' AS event_family, location_name
            FROM dxbi_rental_events FINAL
            WHERE ({_UNIT_LOOKUP_KEY} IN {{units:Array(String)}}
               OR (lowerUTF8(property_type) IN ('villa','villas','townhouse','townhouses')
                   AND toString(toUInt64OrZero(extract(unit_number, '([0-9]+)$'))) IN {{units:Array(String)}}))
            {scope}
            SETTINGS max_execution_time=25, max_result_rows=500000, result_overflow_mode='throw', max_threads=2, max_memory_usage=2000000000""",
        parameters,
        **({"external_data": external} if external is not None else {}),
    )
    if rows:
        places = await query(
            "SELECT location_id, path_key, building_key, area_key, match_rank, building_label, project_label, area_label FROM dxbi_places"
        )
        catalog = RegistryLocationIndex(places)
        return [normalize_registry_locations(row, catalog) for row in rows]
    return rows


async def fetch_registry_places():
    return await query(
        "SELECT location_id, path_key, building_key, area_key, match_rank, building_label, project_label, area_label FROM dxbi_places"
    )


_MATCHER_EVENT_COLUMNS = (
    """unit_number, building_name, project_name, area_name, size_sqft, property_type"""
)
_FINANCING_PROCEDURES = "(?i)mortgage|lease finance|lease to own|modify"


async def fetch_matcher_places():
    """Every distinct place label set in DXBI sales and rentals, with the rental ``location_name``
    the place catalog also reads. A few thousand rows stand for millions of events."""
    return await query(
        """SELECT 'sale' AS family, area_name, project_name, building_name, '' AS location_name
           FROM dxbi_sales_unit_events
           GROUP BY area_name, project_name, building_name
           UNION ALL
           SELECT 'rental' AS family, area_name, project_name, building_name, location_name
           FROM dxbi_rental_events
           GROUP BY area_name, project_name, building_name, location_name"""
    )


async def fetch_matcher_events(places: list[dict]):
    """DXBI sales and rentals in the given places, as the matcher's event dicts.

    ``places`` are rows of ``fetch_matcher_places``; an event belongs to a row when its three
    labels (and, for a rental, its location name) equal the row's."""
    if not places:
        return []
    external = ExternalData(
        file_name="matcher_places",
        data="\n".join(
            json.dumps(
                {
                    "family": row["family"],
                    "area": row["area_name"],
                    "project": row["project_name"],
                    "building": row["building_name"],
                    "location": row["location_name"],
                }
            )
            for row in places
        ).encode(),
        fmt="JSONEachRow",
        structure="family String, area String, project String, building String, location String",
    )
    return await query(
        f"""SELECT 'sale' AS family, sale_key AS event_key, toString(transaction_date) AS event_date,
                   toFloat64(sale_amount_aed) AS amount, '' AS location_name,
                   {_MATCHER_EVENT_COLUMNS}
            FROM dxbi_sales_unit_events FINAL
            WHERE (area_name, project_name, building_name) IN
                  (SELECT area, project, building FROM matcher_places WHERE family = 'sale')
            UNION ALL
            SELECT 'rental' AS family, event_key, toString(lease_start) AS event_date,
                   toFloat64(contract_amount_aed) AS amount, location_name,
                   {_MATCHER_EVENT_COLUMNS}
            FROM dxbi_rental_events FINAL
            WHERE contract_amount_aed > 0
              AND (area_name, project_name, building_name, location_name) IN
                  (SELECT area, project, building, location FROM matcher_places
                   WHERE family = 'rental')""",
        external_data=external,
    )


async def fetch_matcher_registry(amounts: list[int]):
    """Transactions (``market_sale_events``) sales at exactly these whole-dirham amounts, as the
    matcher's registry rows. Financing procedures (mortgage, lease finance...) are never sales."""
    external = ExternalData(
        file_name="matcher_amounts",
        data="\n".join(json.dumps({"amount": value}) for value in amounts).encode(),
        fmt="JSONEachRow",
        structure="amount Int64",
    )
    return await query(
        f"""SELECT instance_date, procedure_name_en, actual_worth, procedure_area,
                   property_type_en, area_name_en, master_project_en, project_name_en,
                   building_name_en, unit_number, community_name, match_status, dxbi_sale_key,
                   transaction_id
            FROM market_sale_events
            WHERE actual_worth IN (SELECT amount FROM matcher_amounts)
              AND NOT match(procedure_name_en, '{_FINANCING_PROCEDURES}')""",
        external_data=external,
    )
