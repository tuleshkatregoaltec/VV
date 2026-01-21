-- ClickHouse Schema Definitions for ViteVue Platform
-- All tables use ReplacingMergeTree for automatic deduplication
-- Hash-based change detection via row_hash column (sipHash64)
-- Soft deletes via is_deleted flag
-- ETL rollback safety via etl_run_id

-- Table 1: Transactions (Sales)
CREATE TABLE IF NOT EXISTS ch_transactions (
    -- Primary Key
    transaction_id String,

    -- Change Detection & Versioning
    row_hash UInt64,
    etl_run_id String,
    etl_inserted_at DateTime DEFAULT now(),
    is_deleted UInt8 DEFAULT 0,

    -- Golden Path Sort Key (property_usage + date)
    property_usage_en LowCardinality(String),
    instance_date Date,

    -- Core Dimensions (LowCardinality for instant dropdowns)
    property_type_en LowCardinality(String),
    property_sub_type_en LowCardinality(String),
    rooms_en LowCardinality(String),
    reg_type_en LowCardinality(String),

    -- Geographic (denormalized for fast filtering)
    master_project_en LowCardinality(String),
    area_name_en LowCardinality(String),
    area_id Nullable(Int32),
    project_name_en String,
    project_number Nullable(String),
    building_name_en Nullable(String),

    -- Arabic columns (future-proofing, not in sort key)
    property_type_ar Nullable(String),
    property_sub_type_ar Nullable(String),
    rooms_ar Nullable(String),
    reg_type_ar Nullable(String),
    master_project_ar Nullable(String),
    area_name_ar Nullable(String),
    project_name_ar Nullable(String),
    building_name_ar Nullable(String),

    -- Property Details
    procedure_area Decimal64(2),
    has_parking UInt8,

    -- Financial Metrics
    actual_worth Decimal64(2),
    meter_sale_price Decimal64(2),

    -- Landmarks
    nearest_landmark_en Nullable(String),
    nearest_landmark_ar Nullable(String),
    nearest_metro_en Nullable(String),
    nearest_metro_ar Nullable(String),
    nearest_mall_en Nullable(String),
    nearest_mall_ar Nullable(String),

    -- Pre-computed Buckets (for analytics UI)
    price_bucket LowCardinality(String),
    area_bucket LowCardinality(String),
    price_sqft_bucket LowCardinality(String)

) ENGINE = ReplacingMergeTree(etl_inserted_at)
PARTITION BY toYYYYMM(instance_date)
ORDER BY (property_usage_en, instance_date, transaction_id)
SETTINGS index_granularity = 8192;


-- Table 2: Rent Contracts
CREATE TABLE IF NOT EXISTS ch_rent_contracts (
    -- Composite Primary Key
    contract_id String,
    line_number UInt16,

    -- Change Detection & Versioning
    row_hash UInt64,
    etl_run_id String,
    etl_inserted_at DateTime DEFAULT now(),
    is_deleted UInt8 DEFAULT 0,

    -- Golden Path Sort Key
    property_usage_en LowCardinality(String),
    contract_start_date Date,

    -- Core Dimensions
    ejari_property_type_en LowCardinality(String),
    ejari_property_sub_type_en LowCardinality(String),
    contract_reg_type_en LowCardinality(String),
    tenant_type_en LowCardinality(String),

    -- Geographic (denormalized)
    master_project_en LowCardinality(String),
    area_name_en LowCardinality(String),
    area_id Nullable(Int32),
    project_name_en Nullable(String),
    project_number Nullable(String),

    -- Arabic columns (future-proofing)
    ejari_property_type_ar Nullable(String),
    ejari_property_sub_type_ar Nullable(String),
    contract_reg_type_ar Nullable(String),
    tenant_type_ar Nullable(String),
    master_project_ar Nullable(String),
    area_name_ar Nullable(String),
    project_name_ar Nullable(String),

    -- Metrics (strictly metric units)
    annual_amount Decimal64(2),
    actual_area Decimal64(2),
    rent_per_sqm Decimal64(2),

    contract_end_date Nullable(Date),

    -- Landmarks
    nearest_landmark_en Nullable(String),
    nearest_landmark_ar Nullable(String),
    nearest_metro_en Nullable(String),
    nearest_metro_ar Nullable(String),
    nearest_mall_en Nullable(String),
    nearest_mall_ar Nullable(String),

    -- Buckets
    rent_bucket LowCardinality(String),
    area_bucket LowCardinality(String),
    rent_sqft_bucket LowCardinality(String)

) ENGINE = ReplacingMergeTree(etl_inserted_at)
PARTITION BY toYYYYMM(contract_start_date)
ORDER BY (property_usage_en, contract_start_date, contract_id, line_number)
SETTINGS index_granularity = 8192;


-- Table 3: Developers
CREATE TABLE IF NOT EXISTS ch_developers (
    developer_id Int32,
    developer_number String,

    -- LowCardinality for instant dropdown queries
    name_en LowCardinality(String),
    name_ar LowCardinality(Nullable(String)),

    row_hash UInt64,
    etl_run_id String,
    etl_inserted_at DateTime DEFAULT now(),
    is_deleted UInt8 DEFAULT 0

) ENGINE = ReplacingMergeTree(etl_inserted_at)
ORDER BY developer_id;


-- Table 4: Projects
CREATE TABLE IF NOT EXISTS ch_projects (
    project_id Int32,
    project_number String,

    project_name_en String,
    project_name_ar Nullable(String),

    master_project_en LowCardinality(Nullable(String)),
    master_project_id Nullable(Int32),

    developer_id Nullable(Int32),
    master_developer_id Nullable(Int32),

    area_id Nullable(Int32),
    area_name_en LowCardinality(Nullable(String)),

    latitude Nullable(Float64),
    longitude Nullable(Float64),

    property_usage_en LowCardinality(Nullable(String)),
    is_free_hold Nullable(UInt8),

    -- Project Status & Timeline
    project_status LowCardinality(Nullable(String)),
    project_start_date Nullable(Date),
    completion_date Nullable(Date),
    project_end_date Nullable(Date),
    cancellation_date Nullable(Date),
    percent_completed Nullable(Float32),

    -- Project Composition
    total_units Nullable(UInt32),
    total_buildings Nullable(UInt16),
    total_villas Nullable(UInt16),

    -- Regulatory
    escrow_agent_name Nullable(String),
    zoning_authority_en Nullable(String),

    row_hash UInt64,
    etl_run_id String,
    etl_inserted_at DateTime DEFAULT now(),
    is_deleted UInt8 DEFAULT 0,

    -- PROJECTION for flexible filtering on non-key columns
    PROJECTION generic_attribute_search (
        SELECT * ORDER BY developer_id, area_id, is_free_hold, project_id
    )

) ENGINE = ReplacingMergeTree(etl_inserted_at)
ORDER BY (project_number, project_id);


-- Table 5: Buildings
CREATE TABLE IF NOT EXISTS ch_buildings (
    building_id Int32,
    building_number Nullable(String),
    building_name_en String,
    building_name_ar Nullable(String),

    project_id Nullable(Int32),
    project_number Nullable(String),
    project_name_en LowCardinality(Nullable(String)),

    master_project_id Nullable(Int32),
    master_project_en LowCardinality(Nullable(String)),

    land_registry_id Nullable(Int32),
    area_id Nullable(Int32),

    property_type_en LowCardinality(Nullable(String)),
    property_sub_type_en LowCardinality(Nullable(String)),
    property_usage_en LowCardinality(Nullable(String)),

    -- Building specs
    bld_levels Nullable(UInt16),
    floors Nullable(UInt16),
    units Nullable(UInt16),
    flats Nullable(UInt16),
    offices Nullable(UInt16),
    car_parks Nullable(UInt16),
    shops Nullable(UInt16),
    elevators Nullable(UInt16),
    swimming_pools Nullable(UInt16),

    latitude Nullable(Float64),
    longitude Nullable(Float64),

    is_free_hold Nullable(UInt8),

    row_hash UInt64,
    etl_run_id String,
    etl_inserted_at DateTime DEFAULT now(),
    is_deleted UInt8 DEFAULT 0,

    PROJECTION generic_attribute_search (
        SELECT * ORDER BY project_number, property_usage_en, building_id
    )

) ENGINE = ReplacingMergeTree(etl_inserted_at)
ORDER BY (project_number, building_id);


-- Table 6: Units
CREATE TABLE IF NOT EXISTS ch_units (
    unit_id Int32,
    unit_number Nullable(String),
    unit_name_en Nullable(String),

    building_id Nullable(Int32),
    building_name_en LowCardinality(Nullable(String)),

    project_id Nullable(Int32),
    project_number Nullable(String),
    project_name_en LowCardinality(Nullable(String)),

    master_project_id Nullable(Int32),
    master_project_en LowCardinality(Nullable(String)),

    area_id Nullable(Int32),

    property_type_en LowCardinality(Nullable(String)),
    property_sub_type_en LowCardinality(Nullable(String)),
    property_usage_en LowCardinality(Nullable(String)),

    -- Unit specs (for comparables engine)
    rooms_en LowCardinality(Nullable(String)),
    floor Nullable(String),
    actual_area Nullable(Decimal64(2)),
    common_area Nullable(Decimal64(2)),
    unit_balcony_area Nullable(Decimal64(2)),

    -- Parking
    unit_parking_number Nullable(String),
    parking_allocation_type_en Nullable(String),

    is_free_hold Nullable(UInt8),

    row_hash UInt64,
    etl_run_id String,
    etl_inserted_at DateTime DEFAULT now(),
    is_deleted UInt8 DEFAULT 0,

    PROJECTION generic_attribute_search (
        SELECT * ORDER BY project_number, building_id, rooms_en, unit_id
    )

) ENGINE = ReplacingMergeTree(etl_inserted_at)
ORDER BY (project_number, building_id, unit_id);


-- Table 7: Land Registry
CREATE TABLE IF NOT EXISTS ch_land_registry (
    land_registry_id Int32,
    parcel_id Nullable(String),
    parcel_name_en Nullable(String),
    parcel_name_ar Nullable(String),

    master_project_id Nullable(Int32),
    master_project_en LowCardinality(Nullable(String)),

    area_id Nullable(Int32),

    property_type_en LowCardinality(Nullable(String)),
    property_usage_en LowCardinality(Nullable(String)),

    parcel_area Nullable(Decimal64(2)),
    is_free_hold Nullable(UInt8),

    separated_from Nullable(Int32),

    row_hash UInt64,
    etl_run_id String,
    etl_inserted_at DateTime DEFAULT now(),
    is_deleted UInt8 DEFAULT 0

) ENGINE = ReplacingMergeTree(etl_inserted_at)
ORDER BY land_registry_id;


-- Table 8: Areas
CREATE TABLE IF NOT EXISTS ch_areas (
    area_id Int32,
    area_name_en LowCardinality(String),
    area_name_ar LowCardinality(Nullable(String)),

    row_hash UInt64,
    etl_run_id String,
    etl_inserted_at DateTime DEFAULT now(),
    is_deleted UInt8 DEFAULT 0

) ENGINE = ReplacingMergeTree(etl_inserted_at)
ORDER BY area_id;
