from __future__ import annotations

from holocron.platform.clickhouse import ClickHouseClient
from holocron.platform.clickhouse_schema import ensure_schema

_SILVER_TRANSACTIONS_SQL = """
INSERT INTO `silver_transactions_staging`
SELECT
    row_key,
    if(transaction_number != '', transaction_number, row_key) AS transaction_number,
    toDate(instance_date)                                      AS transaction_date,
    group_en                                                   AS trans_group,
    group_ar                                                   AS trans_group_ar,
    procedure_en                                               AS procedure_name,
    procedure_ar                                               AS procedure_name_ar,
    procedure_area,
    prop_type_en                                               AS property_type,
    prop_type_ar                                               AS property_type_ar,
    prop_sb_type_en                                            AS property_sub_type,
    prop_sb_type_ar                                            AS property_sub_type_ar,
    usage_en                                                   AS property_usage,
    usage_ar                                                   AS property_usage_ar,
    reg_type_en                                                AS reg_type,
    reg_type_ar                                                AS reg_type_ar,
    rooms_en,
    rooms_ar,
    parking,
    building_age,
    parcel_id,
    area_id,
    initcap(trim(area_en))                                     AS area_name_en,
    area_ar                                                    AS area_name_ar,
    initcap(trim(project_en))                                  AS project_name_en,
    project_ar                                                 AS project_name_ar,
    initcap(trim(master_project_en))                           AS master_project_en,
    master_project_ar,
    initcap(trim(building_name_en))                            AS building_name_en,
    building_name_ar,
    project_number,
    property_id,
    actual_area                                                AS actual_area_sqm,
    trans_value                                                AS sale_price_aed,
    if(
        meter_sale_price > 0,
        meter_sale_price,
        trans_value / nullIf(procedure_area, 0)
    )                                                          AS price_per_sqm_aed,
    is_free_hold,
    is_offplan                                                 AS is_off_plan,
    total_buyer                                                AS total_buyers,
    total_seller                                               AS total_sellers,
    nearest_metro_en,
    nearest_metro_ar,
    nearest_mall_en,
    nearest_mall_ar,
    nearest_landmark_en,
    nearest_landmark_ar,
    no_of_parties_role_1,
    no_of_parties_role_2,
    no_of_parties_role_3
FROM dld_od_transactions_bronze
WHERE trans_value > 0
"""

_SILVER_RENT_CONTRACTS_SQL = """
INSERT INTO `silver_rent_contracts_staging`
SELECT
    row_key,
    if(contract_number != '', contract_number, row_key) AS contract_id,
    contract_number,
    line_number,
    toDate(registration_date)                           AS registration_date,
    toDate(start_date)                                  AS contract_start_date,
    toDate(end_date)                                    AS contract_end_date,
    prop_type_en                                        AS property_type,
    prop_type_ar                                        AS property_type_ar,
    prop_sub_type_en                                    AS property_sub_type,
    prop_sub_type_ar                                    AS property_sub_type_ar,
    usage_en                                            AS property_usage,
    usage_ar                                            AS property_usage_ar,
    rooms,
    parking,
    actual_area                                         AS actual_area_sqm,
    annual_amount                                       AS annual_amount_aed,
    contract_amount                                     AS contract_amount_aed,
    annual_amount / nullIf(actual_area, 0)              AS rent_per_sqm_aed,
    total_properties,
    version_number,
    version_en                                          AS contract_version,
    version_ar                                          AS contract_version_ar,
    parcel_id,
    area_id,
    initcap(trim(area_en))                              AS area_name_en,
    area_ar                                             AS area_name_ar,
    initcap(trim(project_en))                           AS project_name_en,
    project_ar                                          AS project_name_ar,
    initcap(trim(master_project_en))                    AS master_project_en,
    master_project_ar,
    project_number,
    property_id,
    land_property_id,
    is_free_hold,
    tenant_type_en                                      AS tenant_type,
    tenant_type_ar,
    contract_reg_type_en                                AS contract_reg_type,
    contract_reg_type_ar,
    ejari_property_type_id,
    ejari_property_sub_type_id,
    ejari_bus_property_type_en                          AS ejari_business_property_type,
    ejari_bus_property_type_ar                          AS ejari_business_property_type_ar,
    nearest_metro_en,
    nearest_metro_ar,
    nearest_mall_en,
    nearest_mall_ar,
    nearest_landmark_en,
    nearest_landmark_ar
FROM dld_od_rents_bronze
WHERE annual_amount > 0
"""


def _materialize(
    *,
    clickhouse: ClickHouseClient,
    target_table: str,
    insert_sql: str,
) -> int:
    staging = f"{target_table}_staging"
    clickhouse.command(f"DROP TABLE IF EXISTS `{staging}`")
    clickhouse.command(f"CREATE TABLE `{staging}` AS `{target_table}`")
    try:
        clickhouse.command(insert_sql)
        clickhouse.command(f"EXCHANGE TABLES `{target_table}` AND `{staging}`")
    finally:
        clickhouse.command(f"DROP TABLE IF EXISTS `{staging}`")
    result = clickhouse.query(f"SELECT count() FROM `{target_table}`")
    return int(result.result_rows[0][0])


def materialize_silver_transactions(*, clickhouse: ClickHouseClient) -> int:
    ensure_schema(clickhouse=clickhouse)
    return _materialize(
        clickhouse=clickhouse,
        target_table="silver_transactions",
        insert_sql=_SILVER_TRANSACTIONS_SQL,
    )


def materialize_silver_rent_contracts(*, clickhouse: ClickHouseClient) -> int:
    ensure_schema(clickhouse=clickhouse)
    return _materialize(
        clickhouse=clickhouse,
        target_table="silver_rent_contracts",
        insert_sql=_SILVER_RENT_CONTRACTS_SQL,
    )
