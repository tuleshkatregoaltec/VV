"""DXBI-only Analytics projections; no canonical-market or DLD enrichment dependency.

Share the Transactions identity and catalogue rules. A scope is a DXBI project, or
its building when no project is supplied; community uses DXBI's displayed location.
Transaction observations are never a registered property-stock denominator.
"""

from app.transaction.service import normalized_rentals_source_sql, normalized_sales_source_sql

_ROOMS = "if(match(bedrooms, '^[0-9]+ Beds?$'), concat(extract(bedrooms, '^([0-9]+)'), ' B/R'), bedrooms)"
_SCOPE = "if(project_name != '', project_name, building_name)"

SALES_SOURCE = f"""(
    SELECT transaction_id, transaction_date AS instance_date,
           'Sales' AS trans_group_en, price_aed AS actual_worth,
           price_per_sqft * 10.7639 AS meter_sale_price,
           size_sqft / 10.7639 AS size_sqm, size_sqft / 10.7639 AS actual_area,
           property_type, property_type AS property_sub_type_en,
           property_usage AS property_usage_en, {_ROOMS} AS rooms_en,
           multiIf(status = 'Off-Plan', 'Off-Plan Properties',
                   status = 'Ready', 'Existing Properties', '') AS reg_type_en,
           if(project_name != '', 'Project', 'Building') AS scope_kind,
           {_SCOPE} AS project_name_en, location_name AS master_project_en,
           location_name, location_name AS area_name_en
    FROM ({normalized_sales_source_sql()})
)"""

RENTALS_SOURCE = f"""(
    SELECT contract_id, lease_start AS contract_start_date, lease_end AS contract_end_date,
           annual_rent_aed AS annual_amount, contract_amount_aed AS contract_amount,
           size_sqft / 10.7639 AS actual_area, size_sqft / 10.7639 AS size_sqm,
           property_type, property_type AS property_type_en,
           property_usage AS property_usage_en, {_ROOMS} AS rooms_en,
           if(project_name != '', 'Project', 'Building') AS scope_kind,
           {_SCOPE} AS project_name_en, location_name AS master_project_en,
           location_name, location_name AS area_name_en
    FROM ({normalized_rentals_source_sql()})
)"""
