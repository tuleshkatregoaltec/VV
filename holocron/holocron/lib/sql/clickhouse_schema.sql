-- ClickHouse schema for active Holocron sources
-- This file contains bronze tables for active Holocron sources.

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

CREATE TABLE IF NOT EXISTS dxbi_heatmap_rental_buildings_bronze (
    rental_key    String,
    run_id        String,
    scraped_at    String DEFAULT '',
    location_id   String DEFAULT '',
    property_type LowCardinality(String) DEFAULT '',
    bedrooms      LowCardinality(String) DEFAULT '',
    query_json    String DEFAULT '',
    raw_json      String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (location_id, property_type, bedrooms, rental_key);

CREATE TABLE IF NOT EXISTS dxbi_heatmap_buildings_bronze (
    response_key String,
    run_id       String,
    scraped_at   String DEFAULT '',
    location_id  String DEFAULT '',
    endpoint     LowCardinality(String) DEFAULT '',
    status       UInt16 DEFAULT 0,
    request_url  String DEFAULT '',
    content_type String DEFAULT '',
    seed_json    String DEFAULT '',
    payload_json String DEFAULT '',
    text         String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (location_id, endpoint, response_key);

CREATE TABLE IF NOT EXISTS dxbi_heatmap_building_statuses_bronze (
    response_key String,
    run_id       String,
    scraped_at   String DEFAULT '',
    location_id  String DEFAULT '',
    endpoint     LowCardinality(String) DEFAULT '',
    status       UInt16 DEFAULT 0,
    request_url  String DEFAULT '',
    content_type String DEFAULT '',
    seed_json    String DEFAULT '',
    payload_json String DEFAULT '',
    text         String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (location_id, endpoint, response_key);

CREATE TABLE IF NOT EXISTS dxbi_heatmap_chessboards_bronze (
    response_key String,
    run_id       String,
    scraped_at   String DEFAULT '',
    location_id  String DEFAULT '',
    endpoint     LowCardinality(String) DEFAULT '',
    status       UInt16 DEFAULT 0,
    request_url  String DEFAULT '',
    content_type String DEFAULT '',
    seed_json    String DEFAULT '',
    payload_json String DEFAULT '',
    text         String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (location_id, endpoint, response_key);

CREATE TABLE IF NOT EXISTS dxbi_fam_map_buildings_bronze (
    response_key String,
    run_id       String,
    scraped_at   String DEFAULT '',
    location_id  String DEFAULT '',
    endpoint     LowCardinality(String) DEFAULT '',
    status       UInt16 DEFAULT 0,
    request_url  String DEFAULT '',
    content_type String DEFAULT '',
    seed_json    String DEFAULT '',
    payload_json String DEFAULT '',
    text         String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (location_id, endpoint, response_key);

CREATE TABLE IF NOT EXISTS dxbi_heatmap_errors_bronze (
    error_key         String,
    run_id            String,
    scraped_at        String DEFAULT '',
    location_id       String DEFAULT '',
    endpoint          LowCardinality(String) DEFAULT '',
    status            UInt16 DEFAULT 0,
    request_url       String DEFAULT '',
    request_body_json String DEFAULT '',
    content_type      String DEFAULT '',
    payload_json      String DEFAULT '',
    text              String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (endpoint, location_id, error_key);

CREATE TABLE IF NOT EXISTS dld_od_transactions_bronze (
    row_key              String,
    run_id               String,
    scraped_at           String DEFAULT '',
    mode                 LowCardinality(String) DEFAULT '',
    date_window_start    Nullable(Date),
    date_window_end      Nullable(Date),
    page_index           UInt32 DEFAULT 0,
    row_index            UInt64 DEFAULT 0,
    transaction_number   String DEFAULT '',
    instance_date        DateTime DEFAULT toDateTime(0),
    group_id             UInt32 DEFAULT 0,
    group_en             LowCardinality(String) DEFAULT '',
    group_ar             String DEFAULT '',
    procedure_id         UInt32 DEFAULT 0,
    procedure_en         LowCardinality(String) DEFAULT '',
    procedure_ar         String DEFAULT '',
    procedure_area       Float64 DEFAULT 0,
    actual_area          Float64 DEFAULT 0,
    trans_value          Int64 DEFAULT 0,
    total_buyer          UInt32 DEFAULT 0,
    total_seller         UInt32 DEFAULT 0,
    property_id          UInt32 DEFAULT 0,
    property_type_id     UInt32 DEFAULT 0,
    prop_type_en         LowCardinality(String) DEFAULT '',
    prop_type_ar         String DEFAULT '',
    property_sub_type_id UInt32 DEFAULT 0,
    prop_sb_type_en      LowCardinality(String) DEFAULT '',
    prop_sb_type_ar      String DEFAULT '',
    usage_id             UInt32 DEFAULT 0,
    usage_en             LowCardinality(String) DEFAULT '',
    usage_ar             String DEFAULT '',
    rooms_en             LowCardinality(String) DEFAULT '',
    rooms_ar             String DEFAULT '',
    parking              String DEFAULT '',
    building_age         UInt32 DEFAULT 0,
    parcel_id            String DEFAULT '',
    area_id              UInt32 DEFAULT 0,
    area_en              LowCardinality(String) DEFAULT '',
    area_ar              String DEFAULT '',
    project_en           String DEFAULT '',
    project_ar           String DEFAULT '',
    master_project_en    String DEFAULT '',
    master_project_ar    String DEFAULT '',
    is_free_hold         UInt8 DEFAULT 0,
    is_free_hold_en      LowCardinality(String) DEFAULT '',
    is_free_hold_ar      String DEFAULT '',
    is_offplan           UInt8 DEFAULT 0,
    is_offplan_en        LowCardinality(String) DEFAULT '',
    is_offplan_ar        String DEFAULT '',
    nearest_metro_en     String DEFAULT '',
    nearest_metro_ar     String DEFAULT '',
    nearest_mall_en      String DEFAULT '',
    nearest_mall_ar      String DEFAULT '',
    nearest_landmark_en  String DEFAULT '',
    nearest_landmark_ar  String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (instance_date, transaction_number);

CREATE TABLE IF NOT EXISTS dld_od_rents_bronze (
    row_key                    String,
    run_id                     String,
    scraped_at                 String DEFAULT '',
    mode                       LowCardinality(String) DEFAULT '',
    date_window_start          Nullable(Date),
    date_window_end            Nullable(Date),
    page_index                 UInt32 DEFAULT 0,
    row_index                  UInt64 DEFAULT 0,
    contract_number            String DEFAULT '',
    registration_date          DateTime DEFAULT toDateTime(0),
    start_date                 DateTime DEFAULT toDateTime(0),
    end_date                   DateTime DEFAULT toDateTime(0),
    property_id                UInt32 DEFAULT 0,
    land_property_id           UInt32 DEFAULT 0,
    ejari_property_type_id     UInt32 DEFAULT 0,
    ejari_property_sub_type_id UInt32 DEFAULT 0,
    prop_type_en               LowCardinality(String) DEFAULT '',
    prop_type_ar               String DEFAULT '',
    prop_sub_type_en           LowCardinality(String) DEFAULT '',
    prop_sub_type_ar           String DEFAULT '',
    property_usage_id          UInt32 DEFAULT 0,
    usage_en                   LowCardinality(String) DEFAULT '',
    usage_ar                   String DEFAULT '',
    rooms                      String DEFAULT '',
    parking                    String DEFAULT '',
    actual_area                Float64 DEFAULT 0,
    annual_amount              Int64 DEFAULT 0,
    contract_amount            Int64 DEFAULT 0,
    total_properties           UInt32 DEFAULT 0,
    version_number             UInt32 DEFAULT 0,
    version_en                 LowCardinality(String) DEFAULT '',
    version_ar                 String DEFAULT '',
    parcel_id                  String DEFAULT '',
    area_id                    UInt32 DEFAULT 0,
    area_en                    LowCardinality(String) DEFAULT '',
    area_ar                    String DEFAULT '',
    project_en                 String DEFAULT '',
    project_ar                 String DEFAULT '',
    master_project_en          String DEFAULT '',
    master_project_ar          String DEFAULT '',
    is_free_hold               UInt8 DEFAULT 0,
    is_free_hold_en            LowCardinality(String) DEFAULT '',
    is_free_hold_ar            String DEFAULT '',
    nearest_metro_en           String DEFAULT '',
    nearest_metro_ar           String DEFAULT '',
    nearest_mall_en            String DEFAULT '',
    nearest_mall_ar            String DEFAULT '',
    nearest_landmark_en        String DEFAULT '',
    nearest_landmark_ar        String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (registration_date, contract_number);

CREATE TABLE IF NOT EXISTS dld_od_projects_bronze (
    row_key               String,
    run_id                String,
    scraped_at            String DEFAULT '',
    mode                  LowCardinality(String) DEFAULT '',
    date_window_start     Nullable(Date),
    date_window_end       Nullable(Date),
    page_index            UInt32 DEFAULT 0,
    row_index             UInt64 DEFAULT 0,
    project_number        UInt32 DEFAULT 0,
    project_en            String DEFAULT '',
    project_ar            String DEFAULT '',
    adoption_date         DateTime DEFAULT toDateTime(0),
    start_date            Nullable(DateTime),
    end_date              Nullable(DateTime),
    completion_date       Nullable(DateTime),
    inspection_date       Nullable(DateTime),
    project_status        LowCardinality(String) DEFAULT '',
    prj_type_en           LowCardinality(String) DEFAULT '',
    prj_type_ar           String DEFAULT '',
    percent_completed     Float64 DEFAULT 0,
    project_value         Int64 DEFAULT 0,
    escrow_account_number String DEFAULT '',
    cnt_total             UInt32 DEFAULT 0,
    cnt_unit              UInt32 DEFAULT 0,
    cnt_building          UInt32 DEFAULT 0,
    cnt_villa             UInt32 DEFAULT 0,
    cnt_land              UInt32 DEFAULT 0,
    developer_number      UInt32 DEFAULT 0,
    developer_en          String DEFAULT '',
    developer_ar          String DEFAULT '',
    area_en               LowCardinality(String) DEFAULT '',
    area_ar               String DEFAULT '',
    zone_en               LowCardinality(String) DEFAULT '',
    zone_ar               String DEFAULT '',
    master_project_en     String DEFAULT '',
    master_project_ar     String DEFAULT '',
    description_en        String DEFAULT '',
    description_ar        String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (project_number);

CREATE TABLE IF NOT EXISTS dld_od_valuations_bronze (
    row_key              String,
    run_id               String,
    scraped_at           String DEFAULT '',
    mode                 LowCardinality(String) DEFAULT '',
    date_window_start    Nullable(Date),
    date_window_end      Nullable(Date),
    page_index           UInt32 DEFAULT 0,
    row_index            UInt64 DEFAULT 0,
    procedure_number     UInt32 DEFAULT 0,
    procedure_year       UInt32 DEFAULT 0,
    instance_date        DateTime DEFAULT toDateTime(0),
    property_id          UInt32 DEFAULT 0,
    property_type_id     UInt32 DEFAULT 0,
    property_type_en     LowCardinality(String) DEFAULT '',
    property_type_ar     String DEFAULT '',
    property_sub_type_id UInt32 DEFAULT 0,
    prop_sub_type_en     LowCardinality(String) DEFAULT '',
    prop_sub_type_ar     String DEFAULT '',
    actual_area          Float64 DEFAULT 0,
    procedure_area       Float64 DEFAULT 0,
    actual_worth         Int64 DEFAULT 0,
    property_total_value Int64 DEFAULT 0,
    row_status_code      LowCardinality(String) DEFAULT '',
    area_id              UInt32 DEFAULT 0,
    area_en              LowCardinality(String) DEFAULT '',
    area_ar              String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (instance_date, procedure_year, procedure_number);

CREATE TABLE IF NOT EXISTS dld_od_lands_bronze (
    row_key                 String,
    run_id                  String,
    scraped_at              String DEFAULT '',
    mode                    LowCardinality(String) DEFAULT '',
    date_window_start       Nullable(Date),
    date_window_end         Nullable(Date),
    page_index              UInt32 DEFAULT 0,
    row_index               UInt64 DEFAULT 0,
    land_number             String DEFAULT '',
    land_sub_number         String DEFAULT '',
    parcel_id               String DEFAULT '',
    municipality_number     String DEFAULT '',
    dm_zip_code             String DEFAULT '',
    land_type_id            UInt32 DEFAULT 0,
    land_type_en            LowCardinality(String) DEFAULT '',
    land_type_ar            String DEFAULT '',
    actual_area             Float64 DEFAULT 0,
    is_free_hold            UInt8 DEFAULT 0,
    is_free_hold_en         LowCardinality(String) DEFAULT '',
    is_free_hold_ar         String DEFAULT '',
    is_offplan_en           LowCardinality(String) DEFAULT '',
    is_offplan_ar           String DEFAULT '',
    is_registered           UInt8 DEFAULT 0,
    prop_sub_type_en        LowCardinality(String) DEFAULT '',
    prop_sub_type_ar        String DEFAULT '',
    area_id                 UInt32 DEFAULT 0,
    area_en                 LowCardinality(String) DEFAULT '',
    area_ar                 String DEFAULT '',
    zone_id                 UInt32 DEFAULT 0,
    zone_en                 LowCardinality(String) DEFAULT '',
    zone_ar                 String DEFAULT '',
    master_project_id       UInt32 DEFAULT 0,
    master_project_en       String DEFAULT '',
    master_project_ar       String DEFAULT '',
    project_number          String DEFAULT '',
    project_en              String DEFAULT '',
    project_ar              String DEFAULT '',
    pre_registration_number String DEFAULT '',
    separated_from          String DEFAULT '',
    separated_reference     String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (land_number);

CREATE TABLE IF NOT EXISTS dld_od_buildings_bronze (
    row_key                 String,
    run_id                  String,
    scraped_at              String DEFAULT '',
    mode                    LowCardinality(String) DEFAULT '',
    date_window_start       Nullable(Date),
    date_window_end         Nullable(Date),
    page_index              UInt32 DEFAULT 0,
    row_index               UInt64 DEFAULT 0,
    building_number         String DEFAULT '',
    parent_property_id      UInt32 DEFAULT 0,
    parcel_id               String DEFAULT '',
    creation_date           DateTime DEFAULT toDateTime(0),
    land_number             String DEFAULT '',
    land_sub_number         UInt32 DEFAULT 0,
    land_type_id            UInt32 DEFAULT 0,
    land_type_en            LowCardinality(String) DEFAULT '',
    land_type_ar            String DEFAULT '',
    prop_sub_type_id        UInt32 DEFAULT 0,
    prop_sub_type_en        LowCardinality(String) DEFAULT '',
    prop_sub_type_ar        String DEFAULT '',
    actual_area             Float64 DEFAULT 0,
    built_up_area           Float64 DEFAULT 0,
    common_area             Float64 DEFAULT 0,
    actual_common_area      Float64 DEFAULT 0,
    floors                  UInt32 DEFAULT 0,
    bld_levels              UInt32 DEFAULT 0,
    flats                   UInt32 DEFAULT 0,
    rooms                   UInt32 DEFAULT 0,
    rooms_en                LowCardinality(String) DEFAULT '',
    rooms_ar                String DEFAULT '',
    offices                 UInt32 DEFAULT 0,
    shops                   UInt32 DEFAULT 0,
    car_parks               UInt32 DEFAULT 0,
    elevators               UInt32 DEFAULT 0,
    swimming_pools          UInt32 DEFAULT 0,
    is_free_hold            UInt8 DEFAULT 0,
    is_free_hold_en         LowCardinality(String) DEFAULT '',
    is_free_hold_ar         String DEFAULT '',
    is_lease_hold           UInt8 DEFAULT 0,
    is_lease_hold_en        LowCardinality(String) DEFAULT '',
    is_lease_hold_ar        String DEFAULT '',
    is_offplan_en           LowCardinality(String) DEFAULT '',
    is_offplan_ar           String DEFAULT '',
    is_registered           UInt8 DEFAULT 0,
    pre_registration_number String DEFAULT '',
    area_id                 UInt32 DEFAULT 0,
    area_en                 LowCardinality(String) DEFAULT '',
    area_ar                 String DEFAULT '',
    zone_id                 UInt32 DEFAULT 0,
    zone_en                 LowCardinality(String) DEFAULT '',
    zone_ar                 String DEFAULT '',
    master_project_id       UInt32 DEFAULT 0,
    master_project_en       String DEFAULT '',
    master_project_ar       String DEFAULT '',
    project_number          String DEFAULT '',
    project_en              String DEFAULT '',
    project_ar              String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (building_number);

CREATE TABLE IF NOT EXISTS dld_od_units_bronze (
    row_key                 String,
    run_id                  String,
    scraped_at              String DEFAULT '',
    mode                    LowCardinality(String) DEFAULT '',
    category                LowCardinality(String) DEFAULT '',
    endpoint                LowCardinality(String) DEFAULT '',
    date_window_start       Nullable(Date),
    date_window_end         Nullable(Date),
    page_index              UInt32 DEFAULT 0,
    row_index               UInt64 DEFAULT 0,
    raw_json                String DEFAULT '',
    source_system           LowCardinality(String) DEFAULT 'dld_open_data',
    source_file             String DEFAULT '',
    source_row_index        UInt64 DEFAULT 0,
    property_id             UInt64 DEFAULT 0,
    area_id                 UInt32 DEFAULT 0,
    zone_id                 UInt32 DEFAULT 0,
    area_en                 LowCardinality(String) DEFAULT '',
    area_ar                 String DEFAULT '',
    land_number             String DEFAULT '',
    land_sub_number         String DEFAULT '',
    building_number         String DEFAULT '',
    unit_number             String DEFAULT '',
    unit_balcony_area       Float64 DEFAULT 0,
    unit_parking_number     String DEFAULT '',
    parking_allocation_type String DEFAULT '',
    parking_allocation_type_en LowCardinality(String) DEFAULT '',
    parking_allocation_type_ar String DEFAULT '',
    common_area             Float64 DEFAULT 0,
    actual_common_area      Float64 DEFAULT 0,
    floor                   String DEFAULT '',
    rooms                   String DEFAULT '',
    rooms_en                LowCardinality(String) DEFAULT '',
    rooms_ar                String DEFAULT '',
    actual_area             Float64 DEFAULT 0,
    property_type_id        UInt32 DEFAULT 0,
    property_type_en        LowCardinality(String) DEFAULT '',
    property_type_ar        String DEFAULT '',
    property_sub_type_id    UInt32 DEFAULT 0,
    prop_sub_type_en        LowCardinality(String) DEFAULT '',
    prop_sub_type_ar        String DEFAULT '',
    parent_property_id      UInt64 DEFAULT 0,
    grandparent_property_id UInt64 DEFAULT 0,
    creation_date           DateTime DEFAULT toDateTime(0),
    municipality_zip_code   String DEFAULT '',
    municipality_number     String DEFAULT '',
    parcel_id               String DEFAULT '',
    is_free_hold            UInt8 DEFAULT 0,
    is_lease_hold           UInt8 DEFAULT 0,
    is_registered           UInt8 DEFAULT 0,
    pre_registration_number String DEFAULT '',
    master_project_id       UInt64 DEFAULT 0,
    master_project_en       String DEFAULT '',
    master_project_ar       String DEFAULT '',
    project_id              UInt64 DEFAULT 0,
    project_en              String DEFAULT '',
    project_ar              String DEFAULT '',
    land_type_id            UInt32 DEFAULT 0,
    land_type_en            LowCardinality(String) DEFAULT '',
    land_type_ar            String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (run_id, row_key);

CREATE TABLE IF NOT EXISTS dld_od_brokers_bronze (
    row_key               String,
    run_id                String,
    scraped_at            String DEFAULT '',
    mode                  LowCardinality(String) DEFAULT '',
    date_window_start     Nullable(Date),
    date_window_end       Nullable(Date),
    page_index            UInt32 DEFAULT 0,
    row_index             UInt64 DEFAULT 0,
    broker_number         UInt32 DEFAULT 0,
    broker_id             UInt32 DEFAULT 0,
    broker_en             String DEFAULT '',
    broker_ar             String DEFAULT '',
    gender_type_id        UInt32 DEFAULT 0,
    gender_en             LowCardinality(String) DEFAULT '',
    gender_ar             String DEFAULT '',
    license_start_date    DateTime DEFAULT toDateTime(0),
    license_end_date      DateTime DEFAULT toDateTime(0),
    real_estate_id        UInt32 DEFAULT 0,
    real_estate_number    UInt32 DEFAULT 0,
    real_estate_en        String DEFAULT '',
    real_estate_ar        String DEFAULT '',
    real_estate_broker_id UInt32 DEFAULT 0,
    phone                 String DEFAULT '',
    fax                   String DEFAULT '',
    webpage               String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (broker_number);

CREATE TABLE IF NOT EXISTS dld_od_developers_bronze (
    row_key                String,
    run_id                 String,
    scraped_at             String DEFAULT '',
    mode                   LowCardinality(String) DEFAULT '',
    date_window_start      Nullable(Date),
    date_window_end        Nullable(Date),
    page_index             UInt32 DEFAULT 0,
    row_index              UInt64 DEFAULT 0,
    developer_number       UInt32 DEFAULT 0,
    developer_id           UInt32 DEFAULT 0,
    developer_en           String DEFAULT '',
    developer_ar           String DEFAULT '',
    registration_date      DateTime DEFAULT toDateTime(0),
    license_number         String DEFAULT '',
    license_issue_date     DateTime DEFAULT toDateTime(0),
    license_expiry_date    DateTime DEFAULT toDateTime(0),
    license_source_id      UInt32 DEFAULT 0,
    license_source_en      String DEFAULT '',
    license_source_ar      String DEFAULT '',
    license_type_id        UInt32 DEFAULT 0,
    license_type_en        String DEFAULT '',
    license_type_ar        String DEFAULT '',
    legal_status           String DEFAULT '',
    legal_status_en        String DEFAULT '',
    legal_status_ar        String DEFAULT '',
    chamber_of_commerce_no String DEFAULT '',
    participant_id         UInt32 DEFAULT 0,
    phone                  String DEFAULT '',
    fax                    String DEFAULT '',
    webpage                String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (developer_number);

ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS source_system LowCardinality(String) DEFAULT 'dld_open_data';
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS source_file String DEFAULT '';
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS source_row_index UInt64 DEFAULT 0;
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS raw_json String DEFAULT '';
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS raw_manifest_s3_key String DEFAULT '';
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS project_number String DEFAULT '';
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS building_name_en String DEFAULT '';
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS building_name_ar String DEFAULT '';
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS reg_type_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS reg_type_en LowCardinality(String) DEFAULT '';
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS reg_type_ar String DEFAULT '';
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS meter_sale_price Float64 DEFAULT 0;
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS rent_value Float64 DEFAULT 0;
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS meter_rent_price Float64 DEFAULT 0;
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS no_of_parties_role_1 UInt32 DEFAULT 0;
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS no_of_parties_role_2 UInt32 DEFAULT 0;
ALTER TABLE dld_od_transactions_bronze ADD COLUMN IF NOT EXISTS no_of_parties_role_3 UInt32 DEFAULT 0;

ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS source_system LowCardinality(String) DEFAULT 'dld_open_data';
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS source_file String DEFAULT '';
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS source_row_index UInt64 DEFAULT 0;
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS raw_json String DEFAULT '';
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS raw_manifest_s3_key String DEFAULT '';
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS line_number UInt32 DEFAULT 0;
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS project_number String DEFAULT '';
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS tenant_type_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS tenant_type_en LowCardinality(String) DEFAULT '';
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS tenant_type_ar String DEFAULT '';
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS contract_reg_type_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS contract_reg_type_en LowCardinality(String) DEFAULT '';
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS contract_reg_type_ar String DEFAULT '';
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS ejari_bus_property_type_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS ejari_bus_property_type_en LowCardinality(String) DEFAULT '';
ALTER TABLE dld_od_rents_bronze ADD COLUMN IF NOT EXISTS ejari_bus_property_type_ar String DEFAULT '';

ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS source_system LowCardinality(String) DEFAULT 'dld_open_data';
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS source_file String DEFAULT '';
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS source_row_index UInt64 DEFAULT 0;
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS raw_json String DEFAULT '';
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS raw_manifest_s3_key String DEFAULT '';
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS project_id UInt64 DEFAULT 0;
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS developer_id UInt64 DEFAULT 0;
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS developer_name String DEFAULT '';
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS master_developer_id UInt64 DEFAULT 0;
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS master_developer_number UInt64 DEFAULT 0;
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS master_developer_name String DEFAULT '';
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS project_type_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS project_classification_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS project_classification_ar String DEFAULT '';
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS escrow_agent_id UInt64 DEFAULT 0;
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS escrow_agent_name String DEFAULT '';
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS cancellation_date Nullable(DateTime);
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS property_id UInt64 DEFAULT 0;
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS area_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS zoning_authority_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS zoning_authority_en String DEFAULT '';
ALTER TABLE dld_od_projects_bronze ADD COLUMN IF NOT EXISTS zoning_authority_ar String DEFAULT '';

ALTER TABLE dld_od_valuations_bronze ADD COLUMN IF NOT EXISTS source_system LowCardinality(String) DEFAULT 'dld_open_data';
ALTER TABLE dld_od_valuations_bronze ADD COLUMN IF NOT EXISTS source_file String DEFAULT '';
ALTER TABLE dld_od_valuations_bronze ADD COLUMN IF NOT EXISTS source_row_index UInt64 DEFAULT 0;
ALTER TABLE dld_od_valuations_bronze ADD COLUMN IF NOT EXISTS raw_json String DEFAULT '';
ALTER TABLE dld_od_valuations_bronze ADD COLUMN IF NOT EXISTS raw_manifest_s3_key String DEFAULT '';

ALTER TABLE dld_od_lands_bronze ADD COLUMN IF NOT EXISTS source_system LowCardinality(String) DEFAULT 'dld_open_data';
ALTER TABLE dld_od_lands_bronze ADD COLUMN IF NOT EXISTS source_file String DEFAULT '';
ALTER TABLE dld_od_lands_bronze ADD COLUMN IF NOT EXISTS source_row_index UInt64 DEFAULT 0;
ALTER TABLE dld_od_lands_bronze ADD COLUMN IF NOT EXISTS raw_json String DEFAULT '';
ALTER TABLE dld_od_lands_bronze ADD COLUMN IF NOT EXISTS raw_manifest_s3_key String DEFAULT '';
ALTER TABLE dld_od_lands_bronze ADD COLUMN IF NOT EXISTS property_id UInt64 DEFAULT 0;
ALTER TABLE dld_od_lands_bronze ADD COLUMN IF NOT EXISTS property_type_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_lands_bronze ADD COLUMN IF NOT EXISTS property_type_en LowCardinality(String) DEFAULT '';
ALTER TABLE dld_od_lands_bronze ADD COLUMN IF NOT EXISTS property_type_ar String DEFAULT '';
ALTER TABLE dld_od_lands_bronze ADD COLUMN IF NOT EXISTS property_sub_type_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_lands_bronze ADD COLUMN IF NOT EXISTS project_id UInt64 DEFAULT 0;

ALTER TABLE dld_od_buildings_bronze ADD COLUMN IF NOT EXISTS source_system LowCardinality(String) DEFAULT 'dld_open_data';
ALTER TABLE dld_od_buildings_bronze ADD COLUMN IF NOT EXISTS source_file String DEFAULT '';
ALTER TABLE dld_od_buildings_bronze ADD COLUMN IF NOT EXISTS source_row_index UInt64 DEFAULT 0;
ALTER TABLE dld_od_buildings_bronze ADD COLUMN IF NOT EXISTS raw_json String DEFAULT '';
ALTER TABLE dld_od_buildings_bronze ADD COLUMN IF NOT EXISTS raw_manifest_s3_key String DEFAULT '';
ALTER TABLE dld_od_buildings_bronze ADD COLUMN IF NOT EXISTS property_id UInt64 DEFAULT 0;
ALTER TABLE dld_od_buildings_bronze ADD COLUMN IF NOT EXISTS property_type_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_buildings_bronze ADD COLUMN IF NOT EXISTS property_type_en LowCardinality(String) DEFAULT '';
ALTER TABLE dld_od_buildings_bronze ADD COLUMN IF NOT EXISTS property_type_ar String DEFAULT '';
ALTER TABLE dld_od_buildings_bronze ADD COLUMN IF NOT EXISTS project_id UInt64 DEFAULT 0;

ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS source_system LowCardinality(String) DEFAULT 'dld_open_data';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS source_file String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS source_row_index UInt64 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS raw_manifest_s3_key String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS property_id UInt64 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS area_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS zone_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS area_en LowCardinality(String) DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS area_ar String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS land_number String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS land_sub_number String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS building_number String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS unit_number String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS unit_balcony_area Float64 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS unit_parking_number String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS parking_allocation_type String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS parking_allocation_type_en LowCardinality(String) DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS parking_allocation_type_ar String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS common_area Float64 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS actual_common_area Float64 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS floor String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS rooms String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS rooms_en LowCardinality(String) DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS rooms_ar String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS actual_area Float64 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS property_type_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS property_type_en LowCardinality(String) DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS property_type_ar String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS property_sub_type_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS prop_sub_type_en LowCardinality(String) DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS prop_sub_type_ar String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS parent_property_id UInt64 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS grandparent_property_id UInt64 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS creation_date DateTime DEFAULT toDateTime(0);
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS municipality_zip_code String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS municipality_number String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS parcel_id String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS is_free_hold UInt8 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS is_lease_hold UInt8 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS is_registered UInt8 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS pre_registration_number String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS master_project_id UInt64 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS master_project_en String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS master_project_ar String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS project_id UInt64 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS project_en String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS project_ar String DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS land_type_id UInt32 DEFAULT 0;
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS land_type_en LowCardinality(String) DEFAULT '';
ALTER TABLE dld_od_units_bronze ADD COLUMN IF NOT EXISTS land_type_ar String DEFAULT '';

ALTER TABLE dld_od_brokers_bronze ADD COLUMN IF NOT EXISTS source_system LowCardinality(String) DEFAULT 'dld_open_data';
ALTER TABLE dld_od_brokers_bronze ADD COLUMN IF NOT EXISTS source_file String DEFAULT '';
ALTER TABLE dld_od_brokers_bronze ADD COLUMN IF NOT EXISTS source_row_index UInt64 DEFAULT 0;
ALTER TABLE dld_od_brokers_bronze ADD COLUMN IF NOT EXISTS raw_json String DEFAULT '';
ALTER TABLE dld_od_brokers_bronze ADD COLUMN IF NOT EXISTS raw_manifest_s3_key String DEFAULT '';

ALTER TABLE dld_od_developers_bronze ADD COLUMN IF NOT EXISTS source_system LowCardinality(String) DEFAULT 'dld_open_data';
ALTER TABLE dld_od_developers_bronze ADD COLUMN IF NOT EXISTS source_file String DEFAULT '';
ALTER TABLE dld_od_developers_bronze ADD COLUMN IF NOT EXISTS source_row_index UInt64 DEFAULT 0;
ALTER TABLE dld_od_developers_bronze ADD COLUMN IF NOT EXISTS raw_json String DEFAULT '';
ALTER TABLE dld_od_developers_bronze ADD COLUMN IF NOT EXISTS raw_manifest_s3_key String DEFAULT '';
ALTER TABLE dld_od_developers_bronze ADD COLUMN IF NOT EXISTS developer_name_en String DEFAULT '';
ALTER TABLE dld_od_developers_bronze ADD COLUMN IF NOT EXISTS developer_name_ar String DEFAULT '';

CREATE TABLE IF NOT EXISTS pf_locations_bronze (
    location_id        String,
    parent_location_id Nullable(String),
    scraped_at         String DEFAULT '',
    locale             LowCardinality(String) DEFAULT '',
    path               String DEFAULT '',
    path_ids_json      String DEFAULT '',
    path_name          String DEFAULT '',
    name               String DEFAULT '',
    level              Int32 DEFAULT 0,
    location_type      LowCardinality(String) DEFAULT '',
    url_slug           String DEFAULT '',
    url_city_slug      String DEFAULT '',
    lat                Nullable(Float64),
    lng                Nullable(Float64),
    children_count     UInt32 DEFAULT 0,
    top_location_id    String DEFAULT '',
    published          UInt8 DEFAULT 0,
    is_dubai           UInt8 DEFAULT 0,
    raw_json           String DEFAULT '',
    run_id             String
) ENGINE = MergeTree()
ORDER BY location_id;

CREATE TABLE IF NOT EXISTS pf_listings_bronze (
    property_key                String,
    run_id                      String,
    scraped_at                  String DEFAULT '',
    query_signature             String DEFAULT '',
    category_id                 UInt16 DEFAULT 0,
    location_id                 String DEFAULT '',
    property_type_id            Nullable(Int64),
    bedroom                     Nullable(Int64),
    min_price                   Nullable(Int64),
    max_price                   Nullable(Int64),
    page                        UInt32 DEFAULT 0,
    wrapper_index               UInt32 DEFAULT 0,
    listing_id                  String DEFAULT '',
    property_id                 String DEFAULT '',
    reference                   String DEFAULT '',
    details_path                String DEFAULT '',
    share_url                   String DEFAULT '',
    title                       String DEFAULT '',
    property_type_json          String DEFAULT '',
    price_json                  String DEFAULT '',
    size_json                   String DEFAULT '',
    bedrooms                    String DEFAULT '',
    bathrooms                   String DEFAULT '',
    listing_location_ids_json   String DEFAULT '',
    listing_location_names_json String DEFAULT '',
    city_location_id            String DEFAULT '',
    community_location_id       String DEFAULT '',
    subcommunity_location_id    String DEFAULT '',
    building_location_id        String DEFAULT '',
    leaf_location_id            String DEFAULT '',
    lat                         Nullable(Float64),
    lng                         Nullable(Float64),
    is_available                UInt8 DEFAULT 0,
    is_verified                 UInt8 DEFAULT 0,
    is_featured                 UInt8 DEFAULT 0,
    is_premium                  UInt8 DEFAULT 0,
    delta_reason                LowCardinality(String) DEFAULT '',
    selected_for_detail         UInt8 DEFAULT 0,
    property_fingerprint        String DEFAULT '',
    agent_json                  String DEFAULT '',
    broker_json                 String DEFAULT '',
    client_json                 String DEFAULT '',
    images_json                 String DEFAULT '',
    raw_property_json           String DEFAULT '',
    raw_wrapper_json            String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (run_id, property_key);

CREATE TABLE IF NOT EXISTS pf_listing_details_bronze (
    detail_key           String,
    run_id               String,
    scraped_at           String DEFAULT '',
    listing_id           String DEFAULT '',
    property_id          String DEFAULT '',
    property_key         String DEFAULT '',
    details_path         String DEFAULT '',
    category_id          UInt16 DEFAULT 0,
    location_id          String DEFAULT '',
    status               LowCardinality(String) DEFAULT '',
    error                String DEFAULT '',
    detail_property_json String DEFAULT '',
    raw_json             String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (run_id, detail_key);

CREATE TABLE IF NOT EXISTS reelly_projects_bronze (
    project_key    String,
    run_id         String,
    scraped_at     String DEFAULT '',
    project_id     String DEFAULT '',
    delta_reason   LowCardinality(String) DEFAULT '',
    list_item_json String DEFAULT '',
    raw_json       String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (run_id, project_key);

CREATE TABLE IF NOT EXISTS reelly_documents_bronze (
    document_key    String,
    run_id          String,
    scraped_at      String DEFAULT '',
    project_id      String DEFAULT '',
    source_endpoint LowCardinality(String) DEFAULT '',
    field_path      String DEFAULT '',
    name            String DEFAULT '',
    url             String DEFAULT '',
    normalized_url  String DEFAULT '',
    status          LowCardinality(String) DEFAULT '',
    error           String DEFAULT '',
    downloaded_path String DEFAULT '',
    final_url       String DEFAULT '',
    content_type    String DEFAULT '',
    sha256          String DEFAULT '',
    size_bytes      UInt64 DEFAULT 0,
    raw_json        String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (run_id, document_key);

CREATE TABLE IF NOT EXISTS reelly_matrix_availability_bronze (
    availability_key String,
    run_id           String,
    scraped_at       String DEFAULT '',
    project_id       String DEFAULT '',
    endpoint         String DEFAULT '',
    candidate        String DEFAULT '',
    status           LowCardinality(String) DEFAULT '',
    error            String DEFAULT '',
    raw_json         String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (run_id, availability_key);

CREATE TABLE IF NOT EXISTS bronze_load_ledger (
    source          LowCardinality(String),
    dataset_version String,
    manifest_key    String,
    run_id          String,
    table_name      String,
    row_count       UInt64,
    loaded_at       DateTime64(3, 'UTC'),
    status          LowCardinality(String),
    error           String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (source, dataset_version, manifest_key, table_name, loaded_at);

-- Silver layer: cleaned, normalised, analytics-ready tables derived from bronze.
-- Field naming conventions:
--   - Free-text entity names use initcap(trim()) applied at build time.
--   - Arabic variants are preserved alongside English.
--   - Bronze ingestion envelope (run_id, mode, page_index, etc.) is dropped.
--   - Numeric-only ID fields (group_id, procedure_id, usage_id) are dropped;
--     area_id and property_id are kept as stable cross-source identifiers.
--   - Redundant string flags (is_free_hold_en/ar, is_offplan_en/ar) are dropped.

CREATE TABLE IF NOT EXISTS silver_transactions (
    row_key                  String,
    transaction_number       String               DEFAULT '',
    transaction_date         Date                 DEFAULT toDate(0),
    trans_group              LowCardinality(String) DEFAULT '',
    trans_group_ar           String               DEFAULT '',
    procedure_name           LowCardinality(String) DEFAULT '',
    procedure_name_ar        String               DEFAULT '',
    procedure_area           Float64              DEFAULT 0,
    property_type            LowCardinality(String) DEFAULT '',
    property_type_ar         String               DEFAULT '',
    property_sub_type        LowCardinality(String) DEFAULT '',
    property_sub_type_ar     String               DEFAULT '',
    property_usage           LowCardinality(String) DEFAULT '',
    property_usage_ar        String               DEFAULT '',
    reg_type                 LowCardinality(String) DEFAULT '',
    reg_type_ar              String               DEFAULT '',
    rooms_en                 LowCardinality(String) DEFAULT '',
    rooms_ar                 String               DEFAULT '',
    parking                  String               DEFAULT '',
    building_age             UInt32               DEFAULT 0,
    parcel_id                String               DEFAULT '',
    area_id                  UInt32               DEFAULT 0,
    area_name_en             LowCardinality(String) DEFAULT '',
    area_name_ar             String               DEFAULT '',
    project_name_en          String               DEFAULT '',
    project_name_ar          String               DEFAULT '',
    master_project_en        String               DEFAULT '',
    master_project_ar        String               DEFAULT '',
    building_name_en         String               DEFAULT '',
    building_name_ar         String               DEFAULT '',
    project_number           String               DEFAULT '',
    property_id              UInt32               DEFAULT 0,
    actual_area_sqm          Float64              DEFAULT 0,
    sale_price_aed           Int64                DEFAULT 0,
    price_per_sqm_aed        Float64              DEFAULT 0,
    is_free_hold             UInt8                DEFAULT 0,
    is_off_plan              UInt8                DEFAULT 0,
    total_buyers             UInt32               DEFAULT 0,
    total_sellers            UInt32               DEFAULT 0,
    nearest_metro_en         String               DEFAULT '',
    nearest_metro_ar         String               DEFAULT '',
    nearest_mall_en          String               DEFAULT '',
    nearest_mall_ar          String               DEFAULT '',
    nearest_landmark_en      String               DEFAULT '',
    nearest_landmark_ar      String               DEFAULT '',
    no_of_parties_role_1     UInt32               DEFAULT 0,
    no_of_parties_role_2     UInt32               DEFAULT 0,
    no_of_parties_role_3     UInt32               DEFAULT 0
) ENGINE = ReplacingMergeTree()
ORDER BY (transaction_date, transaction_number);

CREATE TABLE IF NOT EXISTS silver_rent_contracts (
    row_key                      String,
    contract_id                  String               DEFAULT '',
    contract_number              String               DEFAULT '',
    line_number                  UInt32               DEFAULT 0,
    registration_date            Date                 DEFAULT toDate(0),
    contract_start_date          Date                 DEFAULT toDate(0),
    contract_end_date            Date                 DEFAULT toDate(0),
    property_type                LowCardinality(String) DEFAULT '',
    property_type_ar             String               DEFAULT '',
    property_sub_type            LowCardinality(String) DEFAULT '',
    property_sub_type_ar         String               DEFAULT '',
    property_usage               LowCardinality(String) DEFAULT '',
    property_usage_ar            String               DEFAULT '',
    rooms                        LowCardinality(String) DEFAULT '',
    parking                      String               DEFAULT '',
    actual_area_sqm              Float64              DEFAULT 0,
    annual_amount_aed            Int64                DEFAULT 0,
    contract_amount_aed          Int64                DEFAULT 0,
    rent_per_sqm_aed             Float64              DEFAULT 0,
    total_properties             UInt32               DEFAULT 0,
    version_number               UInt32               DEFAULT 0,
    contract_version             LowCardinality(String) DEFAULT '',
    contract_version_ar          String               DEFAULT '',
    parcel_id                    String               DEFAULT '',
    area_id                      UInt32               DEFAULT 0,
    area_name_en                 LowCardinality(String) DEFAULT '',
    area_name_ar                 String               DEFAULT '',
    project_name_en              String               DEFAULT '',
    project_name_ar              String               DEFAULT '',
    master_project_en            String               DEFAULT '',
    master_project_ar            String               DEFAULT '',
    project_number               String               DEFAULT '',
    property_id                  UInt32               DEFAULT 0,
    land_property_id             UInt32               DEFAULT 0,
    is_free_hold                 UInt8                DEFAULT 0,
    tenant_type                  LowCardinality(String) DEFAULT '',
    tenant_type_ar               String               DEFAULT '',
    contract_reg_type            LowCardinality(String) DEFAULT '',
    contract_reg_type_ar         String               DEFAULT '',
    ejari_property_type_id       UInt32               DEFAULT 0,
    ejari_property_sub_type_id   UInt32               DEFAULT 0,
    ejari_business_property_type LowCardinality(String) DEFAULT '',
    ejari_business_property_type_ar String            DEFAULT '',
    nearest_metro_en             String               DEFAULT '',
    nearest_metro_ar             String               DEFAULT '',
    nearest_mall_en              String               DEFAULT '',
    nearest_mall_ar              String               DEFAULT '',
    nearest_landmark_en          String               DEFAULT '',
    nearest_landmark_ar          String               DEFAULT ''
) ENGINE = ReplacingMergeTree()
ORDER BY (registration_date, contract_id);
