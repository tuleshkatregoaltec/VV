"""Canonical rental identity/ranking and scoring SQL; free of runtime imports."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

COVERAGE_CTE = """
WITH coverage AS (
    SELECT max(source_shard_date) AS data_complete_through
    FROM dxbi_rental_events FINAL
),
"""

RANKED_CTES = """latest_unit AS (
    SELECT
        c.event_key,
        c.unit_candidate_key AS unit_candidate_key,
        c.unit_cohort_key,
        c.location_name,
        if(
            c.property_type IN ('Villa', 'Townhouse'),
            '',
            coalesce(nullIf(g.display_building_name, ''), c.building_name)
        ) AS building_name,
        coalesce(nullIf(g.display_project_name, ''), c.project_name) AS project_name,
        coalesce(nullIf(g.display_area_name, ''), c.area_name) AS area_name,
        c.building_name AS registry_building_name,
        c.project_name AS registry_project_name,
        c.area_name AS registry_area_name,
        g.canonical_location_id,
        coalesce(nullIf(g.match_status, ''), 'unmapped') AS geography_match_status,
        coalesce(nullIf(g.coordinate_precision, ''), 'missing') AS coordinate_precision,
        g.latitude,
        g.longitude,
        c.property_type,
        c.bedrooms,
        c.size_sqft,
        c.contract_amount_aed,
        c.contract_term_days,
        c.contract_term_months,
        c.annual_rent_aed,
        c.rent_normalization_version,
        c.address_normalization_version,
        c.purchase_price_aed,
        c.lease_start,
        c.lease_end,
        c.contract_state,
        c.observed_contracts,
        c.last_scraped_at,
        c.loaded_at,
        coalesce(nullIf(c.unit_number, ''), m.unit_number) AS unit_number,
        m.identity_sale_date,
        m.identity_sale_price,
        m.last_purchase_date,
        m.matched_sale_price,
        m.latest_property_type,
        m.latest_price_per_sqft_aed,
        m.latest_capital_gain_pct,
        m.latest_ltv_pct,
        m.latest_seller_type,
        m.latest_seller_transaction_count,
        m.latest_market_status,
        m.latest_detail_url,
        m.matching_units,
        m.match_status AS unit_match_status
    FROM dxbi_rental_unit_candidates AS c FINAL
    LEFT JOIN geo_crm_rental_hierarchy AS g
        ON g.registry_area_name = c.area_name
        AND g.registry_project_name = c.project_name
        AND g.registry_building_name = c.building_name
        AND g.source_grain = multiIf(
            c.property_type IN ('Villa', 'Townhouse'), 'landed_phase',
            c.building_name != '', 'building',
            c.project_name != '', 'project',
            'area'
        )
    LEFT JOIN dxbi_rental_sale_matches AS m FINAL
        ON m.unit_candidate_key = c.unit_candidate_key
),
identified_unit AS (
    SELECT
        *,
        if(
            unit_match_status = 'unique' AND ifNull(unit_number, '') != '',
            concat(
                'unit:',
                replaceRegexpAll(
                    lowerUTF8(coalesce(nullIf(building_name, ''), nullIf(project_name, ''), location_name)),
                    '[^a-z0-9]+',
                    ''
                ),
                ':',
                replaceRegexpAll(lowerUTF8(area_name), '[^a-z0-9]+', ''),
                ':',
                upperUTF8(unit_number)
            ),
            concat('candidate:', unit_candidate_key)
        ) AS property_identity_key
    FROM latest_unit
),
ranked_unit AS (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY property_identity_key
            ORDER BY lease_start DESC, lease_end DESC, last_scraped_at DESC, event_key DESC
        ) AS identity_rank
    FROM identified_unit
),
"""

LEAD_SCORING_CTES = """lead_evidence AS (
    SELECT
        r.*,
        c.data_complete_through,
        multiIf(
            property_type IN ('Apartment', 'Villa'), 'residential',
            property_type = 'Commercial', 'commercial',
            'other'
        ) AS asset_class,
        multiIf(
            property_type = 'Commercial'
                AND latest_property_type IN (
                    'Office',
                    'Shop',
                    'Warehouse',
                    'Show Rooms',
                    'Workshop',
                    'Clinic',
                    'Gymnasium',
                    'Hotel'
                ),
            latest_property_type,
            property_type != '',
            property_type,
            'Other'
        ) AS property_subtype,
        dateDiff('day', {as_of:Date}, lease_end) AS days_to_expiry,
        multiIf(
            unit_match_status != 'unique', 'unit_unresolved',
            last_purchase_date >= lease_start
                AND last_purchase_date < lease_end,
                'sale_during_lease',
            'stable_rental_history'
        ) AS ownership_timing,
        multiIf(
            lease_end >= {as_of:Date}, 'upcoming',
            unit_match_status != 'unique', 'unit_unresolved',
            last_purchase_date >= lease_start
                AND last_purchase_date < lease_end,
                'ownership_review',
            'unlet_signal'
        ) AS lease_evidence_state,
        multiIf(
            lease_end < {as_of:Date}, 'expired',
            lease_end <= addDays({as_of:Date}, 30), 'expiring_30',
            lease_end <= addDays({as_of:Date}, 60), 'expiring_60',
            'expiring_90'
        ) AS lead_status,
        if(
            unit_match_status = 'unique',
            'high',
            if(purchase_price_aed > 0, 'medium', 'low')
        )
            AS match_confidence
    FROM ranked_unit AS r
    CROSS JOIN coverage AS c
    WHERE
        identity_rank = 1
        AND
        lease_end >= addDays({as_of:Date}, -{expired_days:Int32})
        AND lease_end <= addDays({as_of:Date}, 90)
        AND NOT (
            unit_match_status = 'unique'
            AND last_purchase_date >= lease_end
        )
),
leads AS (
    SELECT
        *,
        greatest(
            0,
            least(
                100,
                multiIf(
                    lead_status = 'expired' AND lease_evidence_state = 'unlet_signal', 88,
                    lead_status = 'expiring_30', 84,
                    lead_status = 'expiring_60', 72,
                    60
                )
                + if(unit_match_status = 'unique', 6, 0)
                + if(contract_state = 'Renewed', 2, 0)
                - if(ownership_timing = 'sale_during_lease', 25, 0)
            )
        ) AS raw_score,
        if(raw_score >= 90, 'urgent', if(raw_score >= 75, 'high', 'medium')) AS priority
    FROM lead_evidence
)
"""

PUBLICATION_POLICY = "crm-rental-ranked-base/v2-exact-display-area"
BASE_TABLE = "crm_rental_ranked_base"
BASE_ORDER_BY = "(area_name, project_name, building_name, lease_end, property_identity_key)"
LIVE_LEAD_CTE = COVERAGE_CTE + RANKED_CTES + LEAD_SCORING_CTES
CANDIDATE_SOURCE = "FROM dxbi_rental_unit_candidates AS c FINAL"
assert LIVE_LEAD_CTE.count(CANDIDATE_SOURCE) == 1
# The lead query for chosen areas only. Leases are narrowed to those areas before the joins and
# the per-unit ranking, so one area costs a fraction of all of Dubai. The registry area may be
# renamed by the geography crosswalk, so registry names that display as a chosen area are kept
# too; the exact display-area filter still runs on the result.
AREA_LEAD_CTE = LIVE_LEAD_CTE.replace(
    CANDIDATE_SOURCE,
    """FROM (
        SELECT *, event_key
        FROM dxbi_rental_unit_candidates FINAL
        WHERE
            has({areas:Array(String)}, area_name)
            OR area_name IN (
                SELECT registry_area_name
                FROM geo_crm_rental_hierarchy
                WHERE has({areas:Array(String)}, display_area_name)
            )
    ) AS c""",
)


RANKED_BASE_SELECT = (
    "WITH "
    + RANKED_CTES.rstrip().removesuffix(",")
    + (" SELECT * FROM ranked_unit WHERE identity_rank = 1")
)


# Validate the complete pre-ranking relation: normalized identity areas can collide while
# their exact display labels differ. Checking only identity_rank=1 would hide that conflict.
_IDENTIFIED_CTES, _ = RANKED_CTES.split("ranked_unit AS (", 1)
AREA_IDENTITY_VALIDATION_SQL = (
    "WITH "
    + _IDENTIFIED_CTES.rstrip().removesuffix(",")
    + """
SELECT count() AS unsafe_identities
FROM (
    SELECT property_identity_key
    FROM identified_unit
    GROUP BY property_identity_key
    HAVING min(area_name) != max(area_name)
)
"""
)


def base_lead_cte(*, areas: bool = False) -> str:
    # Publication proves every pre-ranking identity belongs to one exact display area.
    prune = " PREWHERE area_name IN {areas:Array(String)}" if areas else ""
    return (
        COVERAGE_CTE + f"ranked_unit AS (SELECT * FROM {BASE_TABLE}{prune}),\n" + LEAD_SCORING_CTES
    )


TRANSFORM_REVISION = hashlib.sha256(
    (
        PUBLICATION_POLICY
        + AREA_IDENTITY_VALIDATION_SQL
        + LIVE_LEAD_CTE
        + AREA_LEAD_CTE
        + base_lead_cte(areas=True)
        + BASE_ORDER_BY
    ).encode()
).hexdigest()
PHYSICAL_DEPENDENCIES = (
    "dxbi_rental_events",
    "dxbi_rental_unit_candidates",
    "dxbi_rental_sale_matches",
    "geo_source_signatures",
    "geo_entity_links",
    "geo_location_nodes",
    "geo_location_closure",
)
VIEW_DEPENDENCIES = ("geo_mapped_source_facts", "geo_crm_rental_hierarchy")
DEPENDENCIES = (*PHYSICAL_DEPENDENCIES, *VIEW_DEPENDENCIES)
_NAMES = ", ".join("'" + name + "'" for name in DEPENDENCIES)
# Metadata only. Background merges may conservatively invalidate a published base.
DEPENDENCY_STATE_SQL = f"""
SELECT t.name AS name, t.engine AS engine, toString(t.uuid) AS uuid,
    t.create_table_query AS ddl, ifNull(p.parts, '[]') AS parts,
    ifNull(m.pending, 0) AS pending
FROM system.tables AS t
LEFT JOIN (
    SELECT table, toJSONString(arraySort(groupArray(tuple(
        name, rows, bytes_on_disk, toString(hash_of_all_files)
    )))) AS parts
    FROM system.parts
    WHERE database = currentDatabase() AND active AND table IN ({_NAMES})
    GROUP BY table
) AS p ON p.table = t.name
LEFT JOIN (
    SELECT table, countIf(NOT is_done) AS pending
    FROM system.mutations
    WHERE database = currentDatabase() AND table IN ({_NAMES})
    GROUP BY table
) AS m ON m.table = t.name
WHERE t.database = currentDatabase() AND t.name IN ({_NAMES})
ORDER BY name
"""


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def dependency_revision(rows: Sequence[Mapping[str, Any]]) -> str:
    by_name = {row["name"]: dict(row) for row in rows}
    if set(by_name) != set(DEPENDENCIES) or len(rows) != len(DEPENDENCIES):
        raise ValueError("Rental base requires all seven physical sources and both views")
    for name, row in by_name.items():
        if row["pending"]:
            raise ValueError(f"Source mutation still running: {name}")
        expected = (
            row["engine"] == "View"
            if name in VIEW_DEPENDENCIES
            else (row["engine"].endswith("MergeTree"))
        )
        if not expected:
            raise ValueError(f"Unexpected rental dependency engine: {name}")
    return _digest([TRANSFORM_REVISION, sorted(by_name.items())])


def schema_revision(rows: Sequence[Mapping[str, Any]]) -> str:
    return _digest([dict(row) for row in rows])


def schema_sql(table: str) -> str:
    if not table.replace("_", "").isalnum():
        raise ValueError("Invalid rental table identifier")
    return (
        "SELECT name, type, position, default_kind, default_expression FROM system.columns "
        f"WHERE database=currentDatabase() AND table='{table}' ORDER BY position"
    )
