-- ClickHouse schema for active Holocron sources
-- This file currently includes DDA bronze tables.

CREATE TABLE IF NOT EXISTS dda_land_plots (
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
    land_use              String DEFAULT '',
    general_notes         String DEFAULT '',
    coordinates           String DEFAULT '',
    landuse_symbols       String DEFAULT '',
    gfa_type              LowCardinality(String) DEFAULT '',
    is_verified           UInt8 DEFAULT 0,
    verify_comments       String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY plot_number;

CREATE TABLE IF NOT EXISTS dda_project_areas (
    object_id    Int32,
    project_name String DEFAULT '',
    rings        String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY object_id;

CREATE TABLE IF NOT EXISTS dda_subproject_areas (
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

CREATE TABLE IF NOT EXISTS dda_plot_building_limits (
    object_id   Int32,
    plot_number String,
    rings       String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);

CREATE TABLE IF NOT EXISTS dda_plot_podium_limits (
    object_id   Int32,
    plot_number String,
    max_height  String DEFAULT '',
    rings       String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);

CREATE TABLE IF NOT EXISTS dda_plot_features (
    object_id           Int32,
    plot_number         String,
    feature_type_code   Int32 DEFAULT 0,
    feature_type_label  LowCardinality(String) DEFAULT '',
    feature_area_sqm    Float64 DEFAULT 0,
    feature_perimeter_m Float64 DEFAULT 0,
    rings               String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);

CREATE TABLE IF NOT EXISTS dda_frozen_plots (
    object_id        Int32,
    plot_number      String,
    old_plot_numbers String DEFAULT '',
    is_frozen        UInt8 DEFAULT 0,
    plot_area_sqm    Float64 DEFAULT 0,
    plot_perimeter_m Float64 DEFAULT 0,
    gfa_type         LowCardinality(String) DEFAULT '',
    gfa_sqm_t        String DEFAULT '',
    gfa_sqft_t       String DEFAULT '',
    rings            String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);

CREATE TABLE IF NOT EXISTS dda_landuse_symbols (
    object_id         Int32,
    landuse           String DEFAULT '',
    landuse_character String DEFAULT '',
    landuse_id        String DEFAULT '',
    lat               Float64 DEFAULT 0,
    lng               Float64 DEFAULT 0
) ENGINE = MergeTree()
ORDER BY object_id;

CREATE TABLE IF NOT EXISTS dda_plot_built_to_lines (
    object_id   Int32,
    plot_number String,
    paths       String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);

CREATE TABLE IF NOT EXISTS dda_plot_arcades (
    object_id   Int32,
    plot_number String,
    rings       String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);

CREATE TABLE IF NOT EXISTS dda_plot_retail (
    object_id   Int32,
    plot_number String,
    rings       String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (plot_number, object_id);

CREATE TABLE IF NOT EXISTS dxbi_transactions_bronze (
    transaction_key String,
    source_table    LowCardinality(String),
    cells_json      String DEFAULT '',
    cells_count     UInt16 DEFAULT 0,
    run_id          String,
    scraped_at      String DEFAULT '',
    slice_start_date Date,
    slice_end_date   Date,
    source_url      String DEFAULT '',
    page_number     UInt32 DEFAULT 0,
    row_number      UInt32 DEFAULT 0
) ENGINE = MergeTree()
ORDER BY (slice_start_date, source_table, transaction_key);

CREATE TABLE IF NOT EXISTS bay_listings_bronze (
    listing_key          String,
    listing_id           Nullable(Int64),
    purpose              LowCardinality(String),
    category             LowCardinality(String),
    location_id          Int64,
    page                 UInt32 DEFAULT 0,
    scraped_at           String DEFAULT '',
    extract_date         Date,
    title                String DEFAULT '',
    reference_number     String DEFAULT '',
    property_type_main   String DEFAULT '',
    property_type_sub    String DEFAULT '',
    price_aed            Float64 DEFAULT 0,
    area_built_up_sqft   Float64 DEFAULT 0,
    area_plot_sqft       Nullable(Float64),
    bedrooms             Nullable(Int16),
    bathrooms            Nullable(Int16),
    completion_status    String DEFAULT '',
    city_id              Nullable(Int64),
    city_name            String DEFAULT '',
    community_id         Nullable(Int64),
    community_name       String DEFAULT '',
    sub_community_id     Nullable(Int64),
    sub_community_name   String DEFAULT '',
    cluster_id           Nullable(Int64),
    cluster_name         String DEFAULT '',
    lat                  Nullable(Float64),
    lng                  Nullable(Float64),
    agency_id            Nullable(Int64),
    agency_name          String DEFAULT '',
    agent_id             Nullable(Int64),
    agent_name           String DEFAULT '',
    permit_number        String DEFAULT '',
    dld_property_sk      String DEFAULT '',
    project_id           Nullable(Int64),
    project_title        String DEFAULT '',
    created_at           String DEFAULT '',
    updated_at           String DEFAULT '',
    url                  String DEFAULT '',
    raw_json             String DEFAULT '',
    run_id               String
) ENGINE = MergeTree()
ORDER BY (extract_date, purpose, city_name, listing_key);

CREATE TABLE IF NOT EXISTS bay_locations_bronze (
    location_id        Int64,
    name               String DEFAULT '',
    level              LowCardinality(String) DEFAULT '',
    completion_status  String DEFAULT '',
    query              String DEFAULT '',
    page               UInt32 DEFAULT 0,
    scraped_at         String DEFAULT '',
    extract_date       Date,
    country_id         Nullable(Int64),
    country_name       String DEFAULT '',
    city_id            Nullable(Int64),
    city_name          String DEFAULT '',
    community_id       Nullable(Int64),
    community_name     String DEFAULT '',
    sub_community_id   Nullable(Int64),
    sub_community_name String DEFAULT '',
    cluster_id         Nullable(Int64),
    cluster_name       String DEFAULT '',
    lat                Nullable(Float64),
    lng                Nullable(Float64),
    raw_json           String DEFAULT '',
    run_id             String
) ENGINE = MergeTree()
ORDER BY (level, location_id);

CREATE TABLE IF NOT EXISTS bay_transactions_bronze (
    transaction_key       String,
    purpose               LowCardinality(String),
    category              LowCardinality(String),
    locations_ids_json    String DEFAULT '',
    page                  UInt32 DEFAULT 0,
    scraped_at            String DEFAULT '',
    window_start_date     Date,
    window_end_date       Date,
    transaction_date      Date,
    amount_aed            Float64 DEFAULT 0,
    transaction_category  String DEFAULT '',
    property_type         String DEFAULT '',
    beds                  Nullable(Int16),
    builtup_area_sqft     Nullable(Float64),
    plot_area_sqft        Nullable(Float64),
    occupancy_status      String DEFAULT '',
    location_id           Nullable(Int64),
    location_name         String DEFAULT '',
    full_location         String DEFAULT '',
    lat                   Nullable(Float64),
    lng                   Nullable(Float64),
    agent_id              Nullable(Int64),
    status                String DEFAULT '',
    contract_type         String DEFAULT '',
    duration_months       Nullable(Int16),
    monthly_amount_aed    Nullable(Float64),
    raw_json              String DEFAULT '',
    run_id                String
) ENGINE = MergeTree()
ORDER BY (transaction_date, purpose, transaction_key);

CREATE TABLE IF NOT EXISTS dld_transactions_bronze (
    transaction_key          String,
    transaction_kind         LowCardinality(String),
    transaction_date         Date,
    data_mode                LowCardinality(String),
    property_type_id         Nullable(Int64),
    property_type_name_en    String DEFAULT '',
    property_type_name_ar    String DEFAULT '',
    community_id             String DEFAULT '',
    community_name_en        String DEFAULT '',
    community_name_ar        String DEFAULT '',
    project_id               Nullable(Int64),
    project_name_en          String DEFAULT '',
    project_name_ar          String DEFAULT '',
    building_id              Nullable(Int64),
    building_name_en         String DEFAULT '',
    building_name_ar         String DEFAULT '',
    usage_id                 Nullable(Int64),
    usage_name_en            String DEFAULT '',
    usage_name_ar            String DEFAULT '',
    property_status_id       Nullable(Int64),
    property_status_name_en  String DEFAULT '',
    property_status_name_ar  String DEFAULT '',
    property_sub_type_id     Nullable(Int64),
    property_sub_type_name_en String DEFAULT '',
    property_sub_type_name_ar String DEFAULT '',
    sale_type_id             Nullable(Int64),
    sale_type_name_en        String DEFAULT '',
    sale_type_name_ar        String DEFAULT '',
    value_aed                Float64 DEFAULT 0,
    area_sqm                 Float64 DEFAULT 0,
    per_sqm_aed              Float64 DEFAULT 0,
    transaction_count        UInt32 DEFAULT 0,
    raw_json                 String DEFAULT '',
    run_id                   String
) ENGINE = MergeTree()
ORDER BY (transaction_date, transaction_kind, transaction_key);
