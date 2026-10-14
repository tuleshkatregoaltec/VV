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

from app.transaction.queries import _BEDROOMS, _LOCATION, _LOCATION_SPELLING, _USAGE

# DXBI's bedrooms label ('1 Bed', '2 Beds', 'Studio') as the Analytics room label ('1 B/R').
_ROOMS = (
    "if(match(bedroom_label, '^[0-9]+ Beds?$'), "
    "concat(extract(bedroom_label, '^([0-9]+)'), ' B/R'), bedroom_label)"
)
_BEDROOM_LABEL = (
    f"if(bedrooms != '', {_BEDROOMS}, {_BEDROOMS.replace('bedrooms', 'profile_bedrooms')})"
)
_SCOPE = """multiIf(
    profile_project_source = '', if(project_name != '', project_name, building_name),
    profile_project_source = 'place_name', '', profile_project)"""
_SCOPE_KIND = """multiIf(
    scope = '', '',
    profile_project_source = 'own_building'
        OR (profile_project_source = '' AND project_name = ''), 'Building',
    'Project')"""
_MASTER = f"if(profile_master != '', profile_master, {_LOCATION})"
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
           {_SCOPE} AS scope, {_SCOPE_KIND} AS scope_kind, building_name,
           scope AS project_name_en, {_MASTER} AS master_project_en,
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
           {_SCOPE} AS scope, {_SCOPE_KIND} AS scope_kind, building_name,
           scope AS project_name_en, {_MASTER} AS master_project_en,
           {_LOCATION} AS location_name, {_AREA} AS area_name_en
    FROM dxbi_leases_listed
)"""
