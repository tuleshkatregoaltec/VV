"""DXBI-only Analytics records, read from Holocron's listed tables.

``dxbi_sales_listed`` / ``dxbi_leases_listed`` hold every record the Transactions pages list,
once each (the same identity rules), with DXBI's own values and the profile's DLD-sourced area,
master project and project (holocron.market.dxbi_profile). They are rebuilt after each profile
build, so a request reads one table instead of re-deriving the Transactions normalisation
(11-15 s per summary when it did, 2026-10-14).

Values follow the Transactions pages: DXBI's own first, the profile's sourced fill where DXBI
left one empty. A scope is the record's project; a building no source places in a project is
its own scope (``own_building``); a DXBI "building" that is a place's name (``place_name``) is
no project. A record loaded since the last profile build has no profile yet: its scope is
DXBI's project, else its building, until the next build. The master project is DLD's; where DLD
defines none, DXBI's community. Transaction observations are never a registered property-stock
denominator.
"""

from app.transaction.service import BEDROOMS_SQL as _BEDROOMS
from app.transaction.service import LOCATION_SPELLING_SQL as _LOCATION_SPELLING
from app.transaction.service import LOCATION_SQL as _LOCATION
from app.transaction.service import USAGE_SQL as _USAGE

# DXBI's bedrooms label ('1 Bed', '2 Beds', 'Studio') as the Analytics room label ('1 B/R'). An
# office or shop has no bedrooms: its type (Office, Shop, Warehouse; a lease's from its matched
# DLD contract) is its configuration, so the bedroom-keyed tables group commercial records by type.
_ROOMS = (
    f"if({_USAGE} = 'Commercial', "
    # A lease neither DXBI nor its DLD contract types more finely than "Commercial".
    "if(property_type = 'Commercial', 'Commercial (type not recorded)', property_type), "
    "if(match(bedroom_label, '^[0-9]+ Beds?$'), "
    "concat(extract(bedroom_label, '^([0-9]+)'), ' B/R'), bedroom_label))"
)
_BEDROOM_LABEL = (
    f"if(bedrooms != '', {_BEDROOMS}, {_BEDROOMS.replace('bedrooms', 'profile_bedrooms')})"
)
# The scope, its kind and its master come from Holocron's hierarchy (analytics_projects,
# holocron.market.analytics_hierarchy): one spelling per project, one master per project, and a
# building id per DXBI building. A record with no master in it takes its DXBI community.
_NAME_KEY = "lowerUTF8(replaceRegexpAll({e}, '[^A-Za-z0-9]', ''))"
_MASTER = f"if(master_name != '', master_name, {_LOCATION})"
_MASTER_KEY = f"if(master_key != '', master_key, {_NAME_KEY.format(e=_LOCATION)})"
# DLD's area; without a profile, DXBI's community.
_AREA = f"if(profile_area != '', profile_area, {_LOCATION})"

SALES_SOURCE = f"""(
    WITH {_LOCATION_SPELLING}
    SELECT sale_key AS transaction_id, transaction_date AS instance_date,
           'Sales' AS trans_group_en, sale_amount_aed AS actual_worth,
           multiIf(price_per_sqft_aed > 0, round(price_per_sqft_aed),
                   size_sqft > 0, round(sale_amount_aed / size_sqft), NULL) * 10.7639
               AS meter_sale_price,
           multiIf(size_sqft > 0, size_sqft, profile_size > 0, profile_size, NULL) / 10.7639
               AS size_sqm,
           size_sqm AS actual_area,
           property_type, property_type AS property_sub_type_en,
           {_USAGE} AS property_usage_en, {_BEDROOM_LABEL} AS bedroom_label, {_ROOMS} AS rooms_en,
           multiIf(market_status = 'Offplan' OR (market_status = '' AND profile_status = 'Off-Plan'),
                   'Off-Plan Properties',
                   market_status = 'Ready' OR (market_status = '' AND profile_status = 'Ready'),
                   'Existing Properties', '') AS reg_type_en,
           scope_name AS scope, scope_kind, scope_key, building_name, building_id,
           if(building_display != '', building_display, building_name) AS building_label,
           scope AS project_name_en, {_MASTER} AS master_project_en, {_MASTER_KEY} AS master_key_en,
           {_LOCATION} AS location_name, {_AREA} AS area_name_en
    FROM dxbi_sales_listed
)"""

RENTALS_SOURCE = f"""(
    WITH {_LOCATION_SPELLING}
    SELECT contract_key AS contract_id, lease_start AS contract_start_date,
           lease_end AS contract_end_date,
           annual_rent_aed AS annual_amount, contract_amount_aed AS contract_amount,
           multiIf(size_sqft > 0, size_sqft, profile_size > 0, profile_size, NULL) / 10.7639
               AS actual_area,
           actual_area AS size_sqm,
           property_type, property_type AS property_type_en,
           {_USAGE} AS property_usage_en, {_BEDROOM_LABEL} AS bedroom_label, {_ROOMS} AS rooms_en,
           scope_name AS scope, scope_kind, scope_key, building_name, building_id,
           if(building_display != '', building_display, building_name) AS building_label,
           scope AS project_name_en, {_MASTER} AS master_project_en, {_MASTER_KEY} AS master_key_en,
           {_LOCATION} AS location_name, {_AREA} AS area_name_en
    FROM dxbi_leases_listed
)"""
