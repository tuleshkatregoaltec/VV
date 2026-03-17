-- ClickHouse schema for Vitevue ETL
-- Source of truth: old/insert/schemas.sql
-- Run once against the target ClickHouse database.

-- ---------------------------------------------------------------------------
-- Bayut bronze tables (append-only browser-backed extraction)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS bayut_sale_transactions (
    release_id String,
    scraped_at DateTime,
    window_start_date Date,
    window_end_date Date,
    purpose LowCardinality(String) DEFAULT 'for-sale',
    page UInt32 DEFAULT 0,
    transaction_hash_id String,
    transaction_date String DEFAULT '',
    transaction_amount String DEFAULT '',
    transaction_per_sqm_amount String DEFAULT '',
    builtup_area_sqm String DEFAULT '',
    plot_area_sqm String DEFAULT '',
    balcony_area_sqm String DEFAULT '',
    beds String DEFAULT '',
    floor String DEFAULT '',
    latitude String DEFAULT '',
    longitude String DEFAULT '',
    bayut_latitude String DEFAULT '',
    bayut_longitude String DEFAULT '',
    bayut_property_type_id String DEFAULT '',
    bayut_leaf_location_id String DEFAULT '',
    bayut_leaf_location_name_en String DEFAULT '',
    bayut_leaf_location_name_ar String DEFAULT '',
    bayut_location_l3_name_en String DEFAULT '',
    bayut_location_l3_name_ar String DEFAULT '',
    bayut_location_l4_name_en String DEFAULT '',
    bayut_location_l4_name_ar String DEFAULT '',
    bayut_location_l5_name_en String DEFAULT '',
    bayut_location_l5_name_ar String DEFAULT '',
    bayut_location_l6_name_en String DEFAULT '',
    bayut_location_l6_name_ar String DEFAULT '',
    occupancy_status_name String DEFAULT '',
    claimed_transaction_status String DEFAULT '',
    property_completion_status_sk String DEFAULT '',
    sale_market_name String DEFAULT '',
    seller_type String DEFAULT '',
    transaction_payment_method String DEFAULT '',
    unit_number String DEFAULT '',
    has_kpi_value UInt8 DEFAULT 0,
    previous_sale_transaction_date String DEFAULT ''
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(window_end_date)
ORDER BY (window_end_date, transaction_hash_id, scraped_at);


CREATE TABLE IF NOT EXISTS bayut_rental_transactions (
    release_id String,
    scraped_at DateTime,
    window_start_date Date,
    window_end_date Date,
    purpose LowCardinality(String) DEFAULT 'for-rent',
    page UInt32 DEFAULT 0,
    transaction_hash_id String,
    transaction_date String DEFAULT '',
    contract_start_date String DEFAULT '',
    contract_end_date String DEFAULT '',
    transaction_amount String DEFAULT '',
    contract_monthly_amount String DEFAULT '',
    transaction_per_sqm_amount String DEFAULT '',
    builtup_area_sqm String DEFAULT '',
    plot_area_sqm String DEFAULT '',
    balcony_area_sqm String DEFAULT '',
    beds String DEFAULT '',
    floor String DEFAULT '',
    latitude String DEFAULT '',
    longitude String DEFAULT '',
    bayut_latitude String DEFAULT '',
    bayut_longitude String DEFAULT '',
    bayut_property_type_id String DEFAULT '',
    bayut_leaf_location_id String DEFAULT '',
    bayut_leaf_location_name_en String DEFAULT '',
    bayut_leaf_location_name_ar String DEFAULT '',
    bayut_location_l3_name_en String DEFAULT '',
    bayut_location_l3_name_ar String DEFAULT '',
    bayut_location_l4_name_en String DEFAULT '',
    bayut_location_l4_name_ar String DEFAULT '',
    bayut_location_l5_name_en String DEFAULT '',
    bayut_location_l5_name_ar String DEFAULT '',
    bayut_location_l6_name_en String DEFAULT '',
    bayut_location_l6_name_ar String DEFAULT '',
    occupancy_status_name String DEFAULT '',
    claimed_transaction_status String DEFAULT '',
    property_completion_status_sk String DEFAULT '',
    rent_contract_duration_months String DEFAULT '',
    rent_contract_renewal_status_name String DEFAULT '',
    has_kpi_value UInt8 DEFAULT 0,
    previous_sale_transaction_date String DEFAULT ''
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(window_end_date)
ORDER BY (window_end_date, transaction_hash_id, scraped_at);

-- ---------------------------------------------------------------------------
-- DLD bronze tables (full-refresh via S3 → EXCHANGE TABLES)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dld_transactions (
    transaction_id String,
    procedure_id String DEFAULT '',
    trans_group_id Int32 DEFAULT 0,
    trans_group_ar String DEFAULT '',
    trans_group_en String DEFAULT '',
    procedure_name_ar String DEFAULT '',
    procedure_name_en String DEFAULT '',
    instance_date Date,
    property_typeB_id Int32 DEFAULT 0,
    property_type_ar String DEFAULT '',
    property_type_en LowCardinality(String) DEFAULT '',
    property_sub_type_id Int32 DEFAULT 0,
    property_sub_type_ar String DEFAULT '',
    property_sub_type_en LowCardinality(String) DEFAULT '',
    property_usage_ar String DEFAULT '',
    property_usage_en LowCardinality(String) DEFAULT '',
    reg_type_id Int32 DEFAULT 0,
    reg_type_ar String DEFAULT '',
    reg_type_en LowCardinality(String) DEFAULT '',
    area_id Int32 DEFAULT 0,
    area_name_ar LowCardinality(String) DEFAULT '',
    area_name_en LowCardinality(String) DEFAULT '',
    building_name_ar String DEFAULT '',
    building_name_en String DEFAULT '',
    project_number String DEFAULT '',
    project_name_ar String DEFAULT '',
    project_name_en String DEFAULT '',
    master_project_en LowCardinality(String) DEFAULT '',
    master_project_ar String DEFAULT '',
    nearest_landmark_ar String DEFAULT '',
    nearest_landmark_en String DEFAULT '',
    nearest_metro_ar String DEFAULT '',
    nearest_metro_en String DEFAULT '',
    nearest_mall_ar String DEFAULT '',
    nearest_mall_en String DEFAULT '',
    rooms_ar String DEFAULT '',
    rooms_en LowCardinality(String) DEFAULT '',
    has_parking UInt8 DEFAULT 0,
    procedure_area Decimal64(2) DEFAULT 0,
    actual_worth Nullable(Decimal64(2)),
    meter_sale_price Nullable(Decimal64(2)),
    rent_value Nullable(Decimal64(2)),
    meter_rent_price Nullable(Decimal64(2)),
    no_of_parties_role_1 UInt16 DEFAULT 0,
    no_of_parties_role_2 UInt16 DEFAULT 0,
    no_of_parties_role_3 UInt16 DEFAULT 0
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(instance_date)
ORDER BY (property_usage_en, instance_date, transaction_id);


CREATE TABLE IF NOT EXISTS dld_rent_contracts (
    contract_id String,
    contract_reg_type_id Int32 DEFAULT 0,
    contract_reg_type_ar String DEFAULT '',
    contract_reg_type_en LowCardinality(String) DEFAULT '',
    contract_start_date Date,
    contract_end_date Nullable(Date),
    contract_amount Nullable(Decimal64(2)),
    annual_amount Nullable(Decimal64(2)),
    no_of_prop UInt16 DEFAULT 0,
    line_number UInt16,
    is_free_hold UInt8 DEFAULT 0,
    ejari_bus_property_type_id Int32 DEFAULT 0,
    ejari_bus_property_type_ar String DEFAULT '',
    ejari_bus_property_type_en String DEFAULT '',
    ejari_property_type_id Int32 DEFAULT 0,
    ejari_property_type_en LowCardinality(String) DEFAULT '',
    ejari_property_type_ar String DEFAULT '',
    ejari_property_sub_type_id Int32 DEFAULT 0,
    ejari_property_sub_type_en LowCardinality(String) DEFAULT '',
    ejari_property_sub_type_ar String DEFAULT '',
    property_usage_en LowCardinality(String) DEFAULT '',
    property_usage_ar String DEFAULT '',
    project_number String DEFAULT '',
    project_name_ar String DEFAULT '',
    project_name_en String DEFAULT '',
    master_project_ar String DEFAULT '',
    master_project_en LowCardinality(String) DEFAULT '',
    area_id Int32 DEFAULT 0,
    area_name_ar LowCardinality(String) DEFAULT '',
    area_name_en LowCardinality(String) DEFAULT '',
    actual_area Decimal64(2) DEFAULT 0,
    nearest_landmark_ar String DEFAULT '',
    nearest_landmark_en String DEFAULT '',
    nearest_metro_ar String DEFAULT '',
    nearest_metro_en String DEFAULT '',
    nearest_mall_ar String DEFAULT '',
    nearest_mall_en String DEFAULT '',
    tenant_type_id Int32 DEFAULT 0,
    tenant_type_ar String DEFAULT '',
    tenant_type_en LowCardinality(String) DEFAULT ''
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(contract_start_date)
ORDER BY (property_usage_en, contract_start_date, contract_id, line_number);


CREATE TABLE IF NOT EXISTS dld_projects (
    project_id Int32,
    project_number String DEFAULT '',
    project_name_ar String DEFAULT '',
    project_name_en LowCardinality(String) DEFAULT '',
    developer_id Int32 DEFAULT 0,
    developer_number String DEFAULT '',
    developer_name String DEFAULT '',
    master_developer_id Int32 DEFAULT 0,
    master_developer_number String DEFAULT '',
    master_developer_name String DEFAULT '',
    project_start_date Nullable(Date),
    project_end_date Nullable(Date),
    project_type_id Int32 DEFAULT 0,
    project_type_ar String DEFAULT '',
    project_classification_id Int32 DEFAULT 0,
    project_classification_ar String DEFAULT '',
    escrow_agent_id Int32 DEFAULT 0,
    escrow_agent_name String DEFAULT '',
    project_status String DEFAULT '',
    project_status_ar String DEFAULT '',
    percent_completed Float32 DEFAULT 0,
    completion_date Nullable(Date),
    cancellation_date Nullable(Date),
    project_description_ar String DEFAULT '',
    project_description_en String DEFAULT '',
    property_id Nullable(Int32),
    area_id Int32 DEFAULT 0,
    area_name_ar LowCardinality(String) DEFAULT '',
    area_name_en LowCardinality(String) DEFAULT '',
    master_project_ar String DEFAULT '',
    master_project_en LowCardinality(String) DEFAULT '',
    zoning_authority_id Int32 DEFAULT 0,
    zoning_authority_ar String DEFAULT '',
    zoning_authority_en String DEFAULT '',
    no_of_lands UInt32 DEFAULT 0,
    no_of_buildings UInt16 DEFAULT 0,
    no_of_villas UInt16 DEFAULT 0,
    no_of_units UInt32 DEFAULT 0
) ENGINE = MergeTree()
ORDER BY project_id;


CREATE TABLE IF NOT EXISTS dld_buildings (
    property_id Int32,
    area_id Int32 DEFAULT 0,
    zone_id Int32 DEFAULT 0,
    area_name_ar LowCardinality(String) DEFAULT '',
    area_name_en LowCardinality(String) DEFAULT '',
    land_number String DEFAULT '',
    land_sub_number String DEFAULT '',
    building_number String DEFAULT '',
    common_area Decimal64(2) DEFAULT 0,
    actual_common_area Decimal64(2) DEFAULT 0,
    floors UInt16 DEFAULT 0,
    rooms String DEFAULT '',
    rooms_ar String DEFAULT '',
    rooms_en String DEFAULT '',
    car_parks UInt16 DEFAULT 0,
    built_up_area Decimal64(2) DEFAULT 0,
    bld_levels UInt16 DEFAULT 0,
    shops UInt16 DEFAULT 0,
    flats UInt16 DEFAULT 0,
    offices UInt16 DEFAULT 0,
    swimming_pools UInt16 DEFAULT 0,
    elevators UInt16 DEFAULT 0,
    actual_area Decimal64(2) DEFAULT 0,
    property_type_id Int32 DEFAULT 0,
    property_type_ar String DEFAULT '',
    property_type_en LowCardinality(String) DEFAULT '',
    property_sub_type_id Int32 DEFAULT 0,
    property_sub_type_ar String DEFAULT '',
    property_sub_type_en LowCardinality(String) DEFAULT '',
    parent_property_id Nullable(Int32),
    creation_date Nullable(Date),
    parcel_id String DEFAULT '',
    is_free_hold UInt8 DEFAULT 0,
    is_lease_hold UInt8 DEFAULT 0,
    is_registered UInt8 DEFAULT 0,
    pre_registration_number String DEFAULT '',
    master_project_id Int32 DEFAULT 0,
    master_project_en LowCardinality(String) DEFAULT '',
    master_project_ar String DEFAULT '',
    project_id Int32 DEFAULT 0,
    project_name_ar String DEFAULT '',
    project_name_en LowCardinality(String) DEFAULT '',
    land_type_id Int32 DEFAULT 0,
    land_type_ar String DEFAULT '',
    land_type_en String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY property_id;


CREATE TABLE IF NOT EXISTS dld_units (
    property_id Int32,
    area_id Int32 DEFAULT 0,
    zone_id Int32 DEFAULT 0,
    area_name_ar LowCardinality(String) DEFAULT '',
    area_name_en LowCardinality(String) DEFAULT '',
    land_number String DEFAULT '',
    land_sub_number String DEFAULT '',
    building_number String DEFAULT '',
    unit_number String DEFAULT '',
    unit_balcony_area Decimal64(2) DEFAULT 0,
    unit_parking_number String DEFAULT '',
    parking_allocation_type String DEFAULT '',
    parking_allocation_type_ar String DEFAULT '',
    parking_allocation_type_en String DEFAULT '',
    common_area Decimal64(2) DEFAULT 0,
    actual_common_area Decimal64(2) DEFAULT 0,
    floor String DEFAULT '',
    rooms String DEFAULT '',
    rooms_ar String DEFAULT '',
    rooms_en LowCardinality(String) DEFAULT '',
    actual_area Decimal64(2) DEFAULT 0,
    property_type_id Int32 DEFAULT 0,
    property_type_ar String DEFAULT '',
    property_type_en LowCardinality(String) DEFAULT '',
    property_sub_type_id Int32 DEFAULT 0,
    property_sub_type_ar String DEFAULT '',
    property_sub_type_en LowCardinality(String) DEFAULT '',
    parent_property_id Nullable(Int32),
    grandparent_property_id Nullable(Int32),
    creation_date Nullable(Date),
    munc_zip_code String DEFAULT '',
    munc_number String DEFAULT '',
    parcel_id String DEFAULT '',
    is_free_hold UInt8 DEFAULT 0,
    is_lease_hold UInt8 DEFAULT 0,
    is_registered UInt8 DEFAULT 0,
    pre_registration_number String DEFAULT '',
    master_project_id Int32 DEFAULT 0,
    master_project_en LowCardinality(String) DEFAULT '',
    master_project_ar String DEFAULT '',
    project_id Int32 DEFAULT 0,
    project_name_ar String DEFAULT '',
    project_name_en LowCardinality(String) DEFAULT '',
    land_type_id Int32 DEFAULT 0,
    land_type_ar String DEFAULT '',
    land_type_en String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY property_id;


CREATE TABLE IF NOT EXISTS dld_land_registry (
    property_id Int32,
    area_id Int32 DEFAULT 0,
    zone_id Int32 DEFAULT 0,
    area_name_ar LowCardinality(String) DEFAULT '',
    area_name_en LowCardinality(String) DEFAULT '',
    land_number String DEFAULT '',
    land_sub_number String DEFAULT '',
    actual_area Decimal64(2) DEFAULT 0,
    property_type_id Int32 DEFAULT 0,
    property_type_ar String DEFAULT '',
    property_type_en LowCardinality(String) DEFAULT '',
    property_sub_type_id Int32 DEFAULT 0,
    property_sub_type_ar String DEFAULT '',
    property_sub_type_en LowCardinality(String) DEFAULT '',
    munc_zip_code String DEFAULT '',
    munc_number String DEFAULT '',
    parcel_id String DEFAULT '',
    is_free_hold UInt8 DEFAULT 0,
    is_registered UInt8 DEFAULT 0,
    pre_registration_number String DEFAULT '',
    separated_from Int32 DEFAULT 0,
    separated_reference String DEFAULT '',
    project_id Int32 DEFAULT 0,
    project_name_ar String DEFAULT '',
    project_name_en String DEFAULT '',
    master_project_id Int32 DEFAULT 0,
    master_project_en LowCardinality(String) DEFAULT '',
    master_project_ar String DEFAULT '',
    land_type_id Int32 DEFAULT 0,
    land_type_ar String DEFAULT '',
    land_type_en String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY property_id;


CREATE TABLE IF NOT EXISTS dld_developers (
    developer_id Int32,
    participant_id String DEFAULT '',
    developer_number String DEFAULT '',
    developer_name_ar LowCardinality(String) DEFAULT '',
    developer_name_en LowCardinality(String) DEFAULT '',
    registration_date Nullable(Date),
    license_source_id Int32 DEFAULT 0,
    license_source_ar String DEFAULT '',
    license_source_en String DEFAULT '',
    license_type_id Int32 DEFAULT 0,
    license_type_ar String DEFAULT '',
    license_type_en String DEFAULT '',
    license_number String DEFAULT '',
    license_issue_date Nullable(Date),
    license_expiry_date Nullable(Date),
    chamber_of_commerce_no String DEFAULT '',
    legal_status String DEFAULT '',
    legal_status_ar String DEFAULT '',
    legal_status_en String DEFAULT '',
    webpage String DEFAULT '',
    phone String DEFAULT '',
    fax String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY developer_id;


-- ---------------------------------------------------------------------------
-- DXB Interact bronze tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dxbi_locations (
    run_id String,
    location_id Int32,
    location_name LowCardinality(String) DEFAULT '',
    location_slug String DEFAULT '',
    location_flag LowCardinality(String) DEFAULT '',
    is_featured UInt8 DEFAULT 0,
    seq Nullable(Int32),
    scraped_at DateTime
) ENGINE = MergeTree()
ORDER BY (location_id, location_slug);


CREATE TABLE IF NOT EXISTS dxbi_developers (
    run_id String,
    developer_id Int32,
    developer_name String DEFAULT '',
    is_hot UInt8 DEFAULT 0,
    scraped_at DateTime
) ENGINE = MergeTree()
ORDER BY developer_id;


CREATE TABLE IF NOT EXISTS dxbi_popular_searches (
    run_id String,
    source_page String DEFAULT '',
    scope_slug String DEFAULT '',
    item_rank UInt16 DEFAULT 0,
    location_name String DEFAULT '',
    location_slug String DEFAULT '',
    transaction_count UInt32 DEFAULT 0,
    metric_label LowCardinality(String) DEFAULT '',
    scraped_at DateTime
) ENGINE = MergeTree()
ORDER BY (scope_slug, item_rank, location_slug);


CREATE TABLE IF NOT EXISTS dxbi_popular_sales_areas (
    run_id String,
    source_page String DEFAULT '',
    scope_slug String DEFAULT '',
    item_rank UInt16 DEFAULT 0,
    location_name String DEFAULT '',
    location_slug String DEFAULT '',
    transaction_count UInt32 DEFAULT 0,
    metric_label LowCardinality(String) DEFAULT '',
    scraped_at DateTime
) ENGINE = MergeTree()
ORDER BY (scope_slug, item_rank, location_slug);


CREATE TABLE IF NOT EXISTS dxbi_sales_transactions (
    run_id String,
    source_page String DEFAULT '',
    scope_slug String DEFAULT '',
    listing_rank UInt32 DEFAULT 0,
    location_path String DEFAULT '',
    status_text String DEFAULT '',
    price_aed Nullable(Decimal64(2)),
    capital_gain_text String DEFAULT '',
    price_per_sqft_aed Nullable(Decimal64(2)),
    transaction_size_sqft Nullable(Decimal64(2)),
    bua_sqft Nullable(Decimal64(2)),
    bedrooms_label LowCardinality(String) DEFAULT '',
    transaction_date Nullable(Date),
    seller_type LowCardinality(String) DEFAULT '',
    unit_is_locked UInt8 DEFAULT 0,
    scraped_at DateTime,
    filters_json String DEFAULT ''
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(scraped_at)
ORDER BY (scope_slug, ifNull(transaction_date, toDate('1970-01-01')), listing_rank, location_path);


CREATE TABLE IF NOT EXISTS dxbi_rental_transactions (
    run_id String,
    source_page String DEFAULT '',
    scope_slug String DEFAULT '',
    listing_rank UInt32 DEFAULT 0,
    location_path String DEFAULT '',
    status_text String DEFAULT '',
    bedrooms_label LowCardinality(String) DEFAULT '',
    size_sqft Nullable(Decimal64(2)),
    annual_rent_aed Nullable(Decimal64(2)),
    rental_yield_pct Nullable(Decimal64(4)),
    lease_start_date Nullable(Date),
    lease_end_date Nullable(Date),
    duration_text LowCardinality(String) DEFAULT '',
    purchase_price_aed Nullable(Decimal64(2)),
    unit_is_locked UInt8 DEFAULT 0,
    scraped_at DateTime,
    filters_json String DEFAULT ''
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(scraped_at)
ORDER BY (scope_slug, ifNull(lease_start_date, toDate('1970-01-01')), listing_rank, location_path);


-- ---------------------------------------------------------------------------
-- Silver tables (enriched / geocoded)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS geo_buildings (
    address_key       String,
    building_name_en  String DEFAULT '',
    project_name_en   String DEFAULT '',
    master_project_en String DEFAULT '',
    area_name_en      String DEFAULT '',
    lat               Float64,
    lng               Float64
) ENGINE = MergeTree()
ORDER BY address_key;


CREATE TABLE IF NOT EXISTS gis_land_plots (
    plot_number           String,
    old_numbers           String DEFAULT '',
    project_name          String DEFAULT '',
    community_name        LowCardinality(String) DEFAULT '',
    master_developer      String DEFAULT '',
    plot_area_sqm         Float64 DEFAULT 0,
    plot_area_sqft        Float64 DEFAULT 0,
    max_gfa_sqm           Float64 DEFAULT 0,
    max_gfa_sqft          Float64 DEFAULT 0,
    max_height            String DEFAULT '',
    max_coverage          String DEFAULT '',
    site_plan_issue_date  Nullable(Date),
    site_plan_expiry_date Nullable(Date),
    side1_building        String DEFAULT '',
    side1_podium          String DEFAULT '',
    side2_building        String DEFAULT '',
    side2_podium          String DEFAULT '',
    side3_building        String DEFAULT '',
    side3_podium          String DEFAULT '',
    side4_building        String DEFAULT '',
    side4_podium          String DEFAULT '',
    land_use              String DEFAULT '',   -- JSON: [{"type": "...", "use": "..."}]
    general_notes         String DEFAULT '',
    coordinates           String DEFAULT '',   -- JSON: [[east, north], ...] UTM (WGS84 Zone 40N)
    landuse_symbols       String DEFAULT '',
    gfa_type              LowCardinality(String) DEFAULT '',
    is_verified           UInt8 DEFAULT 0,
    verify_comments       String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY plot_number;


CREATE TABLE IF NOT EXISTS gis_project_areas (
    object_id    Int32,
    project_name String,
    rings        String DEFAULT ''   -- JSON: array of rings, each ring [[lng, lat], ...] WGS84
) ENGINE = MergeTree()
ORDER BY object_id;


CREATE TABLE IF NOT EXISTS gis_subproject_areas (
    object_id            Int32,
    project_id           String DEFAULT '',
    project_name         String DEFAULT '',
    entity_name          String DEFAULT '',
    developer_name       String DEFAULT '',
    master_project_name  String DEFAULT '',
    original_plot_number String DEFAULT '',
    project_logo         String DEFAULT '',
    rings                String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY object_id;


CREATE TABLE IF NOT EXISTS gis_plot_building_limits (
    object_id   Int32,
    plot_number String,
    rings       String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);


CREATE TABLE IF NOT EXISTS gis_plot_podium_limits (
    object_id   Int32,
    plot_number String,
    max_height  String DEFAULT '',
    rings       String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);


CREATE TABLE IF NOT EXISTS gis_plot_features (
    object_id           Int32,
    plot_number         String,
    feature_type_code   Int32 DEFAULT 0,
    feature_type_label  LowCardinality(String) DEFAULT '',
    feature_area_sqm    Float64 DEFAULT 0,
    feature_perimeter_m Float64 DEFAULT 0,
    rings               String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);


CREATE TABLE IF NOT EXISTS gis_frozen_plots (
    object_id         Int32,
    plot_number       String,
    old_plot_numbers  String DEFAULT '',
    is_frozen         UInt8 DEFAULT 0,
    plot_area_sqm     Float64 DEFAULT 0,
    plot_perimeter_m  Float64 DEFAULT 0,
    gfa_type          LowCardinality(String) DEFAULT '',
    gfa_sqm_t         String DEFAULT '',
    gfa_sqft_t        String DEFAULT '',
    rings             String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);


CREATE TABLE IF NOT EXISTS gis_landuse_symbols (
    object_id         Int32,
    landuse           String DEFAULT '',
    landuse_character String DEFAULT '',
    landuse_id        String DEFAULT '',
    lat               Float64 DEFAULT 0,
    lng               Float64 DEFAULT 0
) ENGINE = MergeTree()
ORDER BY object_id;


CREATE TABLE IF NOT EXISTS gis_plot_built_to_lines (
    object_id   Int32,
    plot_number String,
    paths       String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);


CREATE TABLE IF NOT EXISTS gis_plot_arcades (
    object_id   Int32,
    plot_number String,
    rings       String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);


CREATE TABLE IF NOT EXISTS gis_plot_retail (
    object_id   Int32,
    plot_number String,
    rings       String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);


