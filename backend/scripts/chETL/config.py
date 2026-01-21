"""ClickHouse ETL Configuration."""

from pydantic import BaseModel
from typing import List, Dict
import os


class ClickHouseConfig(BaseModel):
    """ClickHouse connection configuration."""

    host: str = os.getenv("CLICKHOUSE_HOST", "localhost")
    port: int = int(os.getenv("CLICKHOUSE_PORT", "9000"))
    username: str = os.getenv("CLICKHOUSE_USER", "default")
    password: str = os.getenv("CLICKHOUSE_PASSWORD", "")
    database: str = os.getenv("CLICKHOUSE_DB", "default")


class TableConfig(BaseModel):
    """Configuration for a single table's ETL process."""

    name: str
    csv_filename: str
    primary_key_cols: List[str]
    critical_cols: List[str]
    column_mappings: Dict[str, str] = {}


# Table configurations
TABLES = {
    "developers": TableConfig(
        name="ch_developers",
        csv_filename="Developers.csv",
        primary_key_cols=["developer_id"],
        critical_cols=["developer_number", "name_en", "name_ar"],
    ),
    "areas": TableConfig(
        name="ch_areas",
        csv_filename="Areas.csv",
        primary_key_cols=["area_id"],
        critical_cols=["area_name_en", "area_name_ar"],
    ),
    "projects": TableConfig(
        name="ch_projects",
        csv_filename="Projects.csv",
        primary_key_cols=["project_id"],
        critical_cols=[
            "project_number",
            "project_name_en",
            "project_name_ar",
            "master_project_en",
            "master_project_id",
            "developer_id",
            "master_developer_id",
            "area_id",
            "area_name_en",
            "latitude",
            "longitude",
            "property_usage_en",
            "is_free_hold",
            "project_status",
            "project_start_date",
            "completion_date",
            "project_end_date",
            "cancellation_date",
            "percent_completed",
            "total_units",
            "total_buildings",
            "total_villas",
            "escrow_agent_name",
            "zoning_authority_en",
        ],
        column_mappings={
            "no_of_units": "total_units",
            "no_of_buildings": "total_buildings",
            "no_of_villas": "total_villas",
        },
    ),
    "land_registry": TableConfig(
        name="ch_land_registry",
        csv_filename="LandRegistry.csv",
        primary_key_cols=["land_registry_id"],
        critical_cols=[
            "parcel_id",
            "parcel_name_en",
            "parcel_name_ar",
            "master_project_id",
            "master_project_en",
            "area_id",
            "property_type_en",
            "property_usage_en",
            "parcel_area",
            "is_free_hold",
            "separated_from",
        ],
    ),
    "buildings": TableConfig(
        name="ch_buildings",
        csv_filename="Buildings.csv",
        primary_key_cols=["building_id"],
        critical_cols=[
            "building_number",
            "building_name_en",
            "building_name_ar",
            "project_id",
            "project_number",
            "project_name_en",
            "master_project_id",
            "master_project_en",
            "land_registry_id",
            "area_id",
            "property_type_en",
            "property_sub_type_en",
            "property_usage_en",
            "bld_levels",
            "floors",
            "units",
            "flats",
            "offices",
            "car_parks",
            "shops",
            "elevators",
            "swimming_pools",
            "latitude",
            "longitude",
            "is_free_hold",
        ],
    ),
    "units": TableConfig(
        name="ch_units",
        csv_filename="Units.csv",
        primary_key_cols=["unit_id"],
        critical_cols=[
            "unit_number",
            "unit_name_en",
            "building_id",
            "building_name_en",
            "project_id",
            "project_number",
            "project_name_en",
            "master_project_id",
            "master_project_en",
            "area_id",
            "property_type_en",
            "property_sub_type_en",
            "property_usage_en",
            "rooms_en",
            "floor",
            "actual_area",
            "common_area",
            "unit_balcony_area",
            "unit_parking_number",
            "parking_allocation_type_en",
            "is_free_hold",
        ],
    ),
    "transactions": TableConfig(
        name="ch_transactions",
        csv_filename="Transactions.csv",
        primary_key_cols=["transaction_id"],
        critical_cols=[
            "transaction_id",
            "instance_date",
            "property_usage_en",
            "actual_worth",
            "procedure_area",
            "meter_sale_price",
            "property_type_en",
            "property_sub_type_en",
            "rooms_en",
            "reg_type_en",
            "master_project_en",
            "area_name_en",
            "area_id",
            "project_name_en",
            "project_number",
            "building_name_en",
            "property_type_ar",
            "property_sub_type_ar",
            "rooms_ar",
            "reg_type_ar",
            "master_project_ar",
            "area_name_ar",
            "project_name_ar",
            "building_name_ar",
            "has_parking",
            "nearest_landmark_en",
            "nearest_landmark_ar",
            "nearest_metro_en",
            "nearest_metro_ar",
            "nearest_mall_en",
            "nearest_mall_ar",
        ],
    ),
    "rent_contracts": TableConfig(
        name="ch_rent_contracts",
        csv_filename="RentContracts.csv",
        primary_key_cols=["contract_id", "line_number"],
        critical_cols=[
            "contract_id",
            "line_number",
            "property_usage_en",
            "contract_start_date",
            "contract_end_date",
            "ejari_property_type_en",
            "ejari_property_sub_type_en",
            "contract_reg_type_en",
            "tenant_type_en",
            "master_project_en",
            "area_name_en",
            "area_id",
            "project_name_en",
            "project_number",
            "ejari_property_type_ar",
            "ejari_property_sub_type_ar",
            "contract_reg_type_ar",
            "tenant_type_ar",
            "master_project_ar",
            "area_name_ar",
            "project_name_ar",
            "annual_amount",
            "actual_area",
            "rent_per_sqm",
            "nearest_landmark_en",
            "nearest_landmark_ar",
            "nearest_metro_en",
            "nearest_metro_ar",
            "nearest_mall_en",
            "nearest_mall_ar",
        ],
    ),
}

# Table processing order (respects dependencies)
TABLE_ORDER = [
    "developers",
    "areas",
    "projects",
    "land_registry",
    "buildings",
    "units",
    "transactions",
    "rent_contracts",
]

# S3 Configuration
S3_BUCKET = os.getenv("S3_BUCKET", "vitevue-data")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
