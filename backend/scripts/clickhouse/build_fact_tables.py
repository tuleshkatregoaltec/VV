from __future__ import annotations

import argparse
import os
import sys
import time

from clickhouse_driver import Client

CLICKHOUSE_HOST = os.environ.get("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.environ.get("CLICKHOUSE_NATIVE_PORT", "9001"))
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "vitevue")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "vitevue_dev")
CLICKHOUSE_DB = os.environ.get("CLICKHOUSE_DB", "vitevue")

PROJECT_FACT_SQL = """
CREATE TABLE ch_project_fact
ENGINE = MergeTree
ORDER BY project_id AS
WITH
    sales AS (
        SELECT
            project_number,
            count() AS sales_transaction_count_12m,
            round(sum(toFloat64(actual_worth)), 2) AS total_sales_volume_12m,
            round(median(toFloat64(actual_worth)), 2) AS median_sale_price,
            round(avg(toFloat64(meter_sale_price)), 2) AS avg_sale_price_sqm_12m
        FROM ch_transactions
        WHERE trans_group_en = 'Sales'
          AND project_number != ''
          AND instance_date >= today() - 365
          AND actual_worth IS NOT NULL
          AND actual_worth > 0
        GROUP BY project_number
    ),
    rents AS (
        SELECT
            project_number,
            count() AS rental_contract_count_12m,
            round(median(toFloat64(annual_amount)), 2) AS median_annual_rent,
            round(avg(toFloat64(annual_amount) / greatest(toFloat64(actual_area), 1)), 2)
                AS avg_rent_price_sqm_12m
        FROM ch_rent_contracts
        WHERE project_number != ''
          AND contract_start_date >= today() - 365
          AND annual_amount IS NOT NULL
          AND annual_amount > 0
        GROUP BY project_number
    )
SELECT
    p.project_id,
    p.project_number,
    p.project_name_en,
    p.area_name_en,
    p.area_id,
    p.developer_name,
    p.master_project_en,
    p.project_status AS completion_status,
    multiIf(
        lowerUTF8(p.project_status) LIKE '%complete%', 'completed',
        lowerUTF8(p.project_status) LIKE '%cancel%', 'cancelled',
        p.project_end_date IS NOT NULL AND p.project_end_date <= addMonths(today(), 12),
            'delivering_next_12_months',
        p.project_end_date IS NULL, 'unscheduled',
        'future'
    ) AS pipeline_status,
    p.no_of_units,
    p.percent_completed,
    round(
        multiIf(
            lowerUTF8(p.project_status) LIKE '%complete%', 1,
            lowerUTF8(p.project_status) LIKE '%cancel%', 0,
            p.percent_completed > 0, least(greatest(toFloat64(p.percent_completed) / 100, 0.1), 0.95),
            0.4
        ),
        2
    ) AS estimated_delivery_confidence,
    ifNull(s.sales_transaction_count_12m, 0) AS sales_transaction_count_12m,
    ifNull(r.rental_contract_count_12m, 0) AS rental_contract_count_12m,
    ifNull(s.total_sales_volume_12m, 0) AS total_sales_volume_12m,
    s.median_sale_price AS median_sale_price,
    r.median_annual_rent AS median_annual_rent,
    if(
        s.median_sale_price IS NULL OR s.median_sale_price = 0 OR r.median_annual_rent IS NULL,
        CAST(NULL, 'Nullable(Float64)'),
        round(toFloat64(r.median_annual_rent) / toFloat64(s.median_sale_price) * 100, 2)
    ) AS gross_yield_pct,
    s.avg_sale_price_sqm_12m AS avg_sale_price_sqm_12m,
    r.avg_rent_price_sqm_12m AS avg_rent_price_sqm_12m
FROM ch_projects p
LEFT JOIN sales s ON p.project_number = s.project_number
LEFT JOIN rents r ON p.project_number = r.project_number
WHERE p.project_id != 0
"""

AREA_FACT_SQL = """
CREATE TABLE ch_area_fact
ENGINE = MergeTree
ORDER BY area_name_en AS
SELECT
    area_name_en,
    any(area_id) AS area_id,
    countIf(pipeline_status NOT IN ('completed', 'cancelled')) AS active_projects,
    countIf(pipeline_status = 'completed') AS completed_projects,
    countIf(lowerUTF8(completion_status) LIKE '%delay%' OR lowerUTF8(completion_status) LIKE '%overdue%')
        AS overdue_projects,
    sumIf(no_of_units, pipeline_status NOT IN ('completed', 'cancelled')) AS pipeline_units,
    sumIf(no_of_units, pipeline_status = 'delivering_next_12_months')
        AS units_delivering_next_12_months,
    uniqExactIf(developer_name, developer_name != '' AND pipeline_status NOT IN ('completed', 'cancelled'))
        AS active_developers,
    round(avgIf(percent_completed, percent_completed > 0), 2) AS avg_completion_pct,
    round(avg(estimated_delivery_confidence), 2) AS avg_delivery_confidence,
    sum(sales_transaction_count_12m) AS sales_transaction_count_12m,
    sum(rental_contract_count_12m) AS rental_contract_count_12m,
    round(sum(total_sales_volume_12m), 2) AS total_sales_volume_12m,
    round(medianIf(median_sale_price, median_sale_price IS NOT NULL), 2) AS median_sale_price,
    round(medianIf(median_annual_rent, median_annual_rent IS NOT NULL), 2) AS median_annual_rent,
    round(avgIf(avg_sale_price_sqm_12m, avg_sale_price_sqm_12m IS NOT NULL), 2)
        AS avg_sale_price_sqm_12m,
    round(avgIf(avg_rent_price_sqm_12m, avg_rent_price_sqm_12m IS NOT NULL), 2)
        AS avg_rent_price_sqm_12m,
    round(avgIf(gross_yield_pct, gross_yield_pct IS NOT NULL), 2) AS gross_yield_pct,
    arrayFilter(x -> x != '', topK(8)(developer_name)) AS top_developers,
    arrayFilter(x -> x != '', topK(8)(master_project_en)) AS top_master_projects
FROM ch_project_fact
WHERE area_name_en != ''
GROUP BY area_name_en
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local ClickHouse serving fact tables.")
    parser.add_argument("--clickhouse-host", default=CLICKHOUSE_HOST)
    parser.add_argument("--clickhouse-port", type=int, default=CLICKHOUSE_PORT)
    parser.add_argument("--clickhouse-user", default=CLICKHOUSE_USER)
    parser.add_argument("--clickhouse-password", default=CLICKHOUSE_PASSWORD)
    parser.add_argument("--clickhouse-db", default=CLICKHOUSE_DB)
    return parser.parse_args()


def get_client(args: argparse.Namespace) -> Client:
    return Client(
        host=args.clickhouse_host,
        port=args.clickhouse_port,
        user=args.clickhouse_user,
        password=args.clickhouse_password,
        database=args.clickhouse_db,
    )


def build_fact_tables(client: Client) -> None:
    start = time.time()
    print("Rebuilding ch_project_fact...")
    client.execute("DROP TABLE IF EXISTS ch_project_fact")
    client.execute(PROJECT_FACT_SQL)

    print("Rebuilding ch_area_fact...")
    client.execute("DROP TABLE IF EXISTS ch_area_fact")
    client.execute(AREA_FACT_SQL)

    project_count = client.execute("SELECT count() FROM ch_project_fact")[0][0]
    area_count = client.execute("SELECT count() FROM ch_area_fact")[0][0]
    print(
        f"Built ch_project_fact ({project_count:,} rows) and "
        f"ch_area_fact ({area_count:,} rows) in {time.time() - start:.2f}s"
    )


def main() -> int:
    build_fact_tables(get_client(parse_args()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
