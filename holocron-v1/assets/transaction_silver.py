"""Deterministic transaction-location silver assets for phase 1 entity resolution."""

from __future__ import annotations

from dagster import AssetIn, MaterializeResult, asset

from holocron.resources.clickhouse import ClickHouseResource
from holocron.transforms.transaction_location import (
    PF_HIERARCHY_COLUMNS,
    SILVER_COLUMNS,
    bay_silver_rows,
    dxbi_silver_rows,
    pf_silver_rows,
    sort_date_key,
)


@asset(
    name="bay_transaction_location_silver",
    group_name="bayut",
    tags={
        "provider": "bayut",
        "dataset": "bay_transactions",
        "asset_type": "silver",
        "table": "bay_transaction_location_silver",
    },
    ins={
        "bay_sale_transactions_bronze": AssetIn(key="bay_sale_transactions"),
        "bay_rental_transactions_bronze": AssetIn(key="bay_rental_transactions"),
    },
    description=(
        "Build deterministic Bayut transaction location silver rows with normalized names, "
        "hierarchy output, and stable source keys."
    ),
)
def bay_transaction_location_silver(
    context,
    bay_sale_transactions_bronze,
    bay_rental_transactions_bronze,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    del context, bay_sale_transactions_bronze, bay_rental_transactions_bronze

    sale_columns, sale_result_rows = clickhouse.query_rows(
        """
        SELECT
            release_id, scraped_at, transaction_hash_id, transaction_date, latitude, longitude,
            bayut_latitude, bayut_longitude, bayut_leaf_location_id, bayut_leaf_location_name_en,
            bayut_location_l3_name_en, bayut_location_l4_name_en, bayut_location_l5_name_en,
            bayut_location_l6_name_en, unit_number
        FROM bay_sale_transactions
        """
    )
    rental_columns, rental_result_rows = clickhouse.query_rows(
        """
        SELECT
            release_id, scraped_at, transaction_hash_id, transaction_date, latitude, longitude,
            bayut_latitude, bayut_longitude, bayut_leaf_location_id, bayut_leaf_location_name_en,
            bayut_location_l3_name_en, bayut_location_l4_name_en, bayut_location_l5_name_en,
            bayut_location_l6_name_en, '' AS unit_number
        FROM bay_rental_transactions
        """
    )

    sale_rows = [dict(zip(sale_columns, row, strict=False)) for row in sale_result_rows]
    rental_rows = [dict(zip(rental_columns, row, strict=False)) for row in rental_result_rows]
    silver_rows = [
        *bay_silver_rows(sale_rows, source_table="bay_sale_transactions", transaction_kind="sale"),
        *bay_silver_rows(
            rental_rows,
            source_table="bay_rental_transactions",
            transaction_kind="rent",
        ),
    ]
    silver_rows.sort(key=lambda item: (sort_date_key(item[7]), item[4]))
    row_count = clickhouse.replace_table_rows(
        table="bay_transaction_location_silver",
        rows=silver_rows,
        column_names=SILVER_COLUMNS,
        staging_suffix="bay_transaction_location_silver",
    )
    return MaterializeResult(
        metadata={
            "row_count": row_count,
            "sale_bronze_row_count": len(sale_rows),
            "rental_bronze_row_count": len(rental_rows),
        }
    )


@asset(
    name="dxbi_transaction_location_silver",
    group_name="dxbinteract",
    tags={
        "provider": "dxbinteract",
        "dataset": "dxbi_transactions",
        "asset_type": "silver",
        "table": "dxbi_transaction_location_silver",
    },
    ins={
        "dxbi_sale_transactions_bronze": AssetIn(key="dxbi_sale_transactions"),
        "dxbi_rental_transactions_bronze": AssetIn(key="dxbi_rental_transactions"),
    },
    description=(
        "Build deterministic DXBI transaction location silver rows by parsing location_path and "
        "standardizing hierarchy hints."
    ),
)
def dxbi_transaction_location_silver(
    context,
    dxbi_sale_transactions_bronze,
    dxbi_rental_transactions_bronze,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    del context, dxbi_sale_transactions_bronze, dxbi_rental_transactions_bronze

    sale_columns, sale_result_rows = clickhouse.query_rows(
        """
        SELECT
            run_id, scraped_at, transaction_key, scope_slug, location_path, transaction_date
        FROM dxbi_sale_transactions
        """
    )
    rental_columns, rental_result_rows = clickhouse.query_rows(
        """
        SELECT
            run_id, scraped_at, transaction_key, scope_slug, location_path, lease_start_date
        FROM dxbi_rental_transactions
        """
    )

    sale_rows = [dict(zip(sale_columns, row, strict=False)) for row in sale_result_rows]
    rental_rows = [dict(zip(rental_columns, row, strict=False)) for row in rental_result_rows]
    silver_rows = [
        *dxbi_silver_rows(
            sale_rows,
            source_table="dxbi_sale_transactions",
            transaction_kind="sale",
        ),
        *dxbi_silver_rows(
            rental_rows,
            source_table="dxbi_rental_transactions",
            transaction_kind="rent",
        ),
    ]
    silver_rows.sort(key=lambda item: (sort_date_key(item[7]), item[4]))
    row_count = clickhouse.replace_table_rows(
        table="dxbi_transaction_location_silver",
        rows=silver_rows,
        column_names=SILVER_COLUMNS,
        staging_suffix="dxbi_transaction_location_silver",
    )
    return MaterializeResult(
        metadata={
            "row_count": row_count,
            "sale_bronze_row_count": len(sale_rows),
            "rental_bronze_row_count": len(rental_rows),
        }
    )


@asset(
    name="pf_transaction_location_silver",
    group_name="propertyfinder",
    tags={
        "provider": "propertyfinder",
        "dataset": "pf_transactions",
        "asset_type": "silver",
        "table": "pf_transaction_location_silver",
    },
    ins={
        "pf_sale_transactions_bronze": AssetIn(key="pf_sale_transactions"),
        "pf_rental_transactions_bronze": AssetIn(key="pf_rental_transactions"),
        "pf_location_hierarchy_silver": AssetIn(key="pf_location_hierarchy"),
    },
    description=(
        "Build deterministic Property Finder transaction location silver rows by joining "
        "transactions to the cleaned PF location hierarchy."
    ),
)
def pf_transaction_location_silver(
    context,
    pf_sale_transactions_bronze,
    pf_rental_transactions_bronze,
    pf_location_hierarchy_silver,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    del (
        context,
        pf_sale_transactions_bronze,
        pf_rental_transactions_bronze,
        pf_location_hierarchy_silver,
    )

    hierarchy_columns, hierarchy_result_rows = clickhouse.query_rows(
        f"SELECT {', '.join(PF_HIERARCHY_COLUMNS)} FROM pf_location_hierarchy"
    )
    hierarchy_rows = [
        dict(zip(hierarchy_columns, row, strict=False)) for row in hierarchy_result_rows
    ]
    hierarchy_by_id = {str(row["pf_location_id"]): row for row in hierarchy_rows}

    sale_columns, sale_result_rows = clickhouse.query_rows(
        """
        SELECT
            release_id, scraped_at, pf_transaction_id, transaction_date, property_number,
            high_level_location_name, location_name, propertyfinder_location_id,
            captured_from_pf_location_id
        FROM pf_sale_transactions
        """
    )
    rental_columns, rental_result_rows = clickhouse.query_rows(
        """
        SELECT
            release_id, scraped_at, pf_transaction_id, transaction_date, property_number,
            high_level_location_name, location_name, propertyfinder_location_id,
            captured_from_pf_location_id
        FROM pf_rental_transactions
        """
    )

    sale_rows = [dict(zip(sale_columns, row, strict=False)) for row in sale_result_rows]
    rental_rows = [dict(zip(rental_columns, row, strict=False)) for row in rental_result_rows]
    silver_rows = [
        *pf_silver_rows(
            sale_rows,
            hierarchy_by_id,
            source_table="pf_sale_transactions",
            transaction_kind="sale",
        ),
        *pf_silver_rows(
            rental_rows,
            hierarchy_by_id,
            source_table="pf_rental_transactions",
            transaction_kind="rent",
        ),
    ]
    silver_rows.sort(key=lambda item: (sort_date_key(item[7]), item[4]))
    row_count = clickhouse.replace_table_rows(
        table="pf_transaction_location_silver",
        rows=silver_rows,
        column_names=SILVER_COLUMNS,
        staging_suffix="pf_transaction_location_silver",
    )
    return MaterializeResult(
        metadata={
            "row_count": row_count,
            "sale_bronze_row_count": len(sale_rows),
            "rental_bronze_row_count": len(rental_rows),
            "hierarchy_row_count": len(hierarchy_rows),
        }
    )
