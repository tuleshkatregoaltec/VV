"""ClickHouse batch insert utilities."""

import logging
from typing import List, Dict, Any
import clickhouse_connect
import pandas as pd

logger = logging.getLogger(__name__)


class ClickHouseLoader:
    """Batch insert rows into ClickHouse."""

    def __init__(self, client: clickhouse_connect.driver.Client):
        self.client = client

    def insert_batch(
        self,
        table_name: str,
        rows: List[Dict[str, Any]],
        batch_size: int = 50000,
    ):
        """
        Insert batch of rows into ClickHouse.

        Args:
            table_name: Target table name
            rows: List of row dicts
            batch_size: Number of rows per batch
        """
        if not rows:
            logger.info(f"No rows to insert into {table_name}")
            return

        total_rows = len(rows)
        logger.info(f"Inserting {total_rows:,} rows into {table_name}...")

        # Process in batches
        for i in range(0, total_rows, batch_size):
            batch = rows[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total_rows + batch_size - 1) // batch_size

            logger.info(
                f"Inserting batch {batch_num}/{total_batches} "
                f"({len(batch):,} rows) into {table_name}"
            )

            # Convert to DataFrame
            df = pd.DataFrame(batch)

            # Insert using clickhouse-connect
            self.client.insert_df(
                table=table_name,
                df=df,
                settings={
                    "async_insert": 1,
                    "wait_for_async_insert": 1,
                },
            )

        logger.info(f"Successfully inserted {total_rows:,} rows into {table_name}")

    def optimize_table(self, table_name: str):
        """
        Force merge optimization on a table.

        This merges ReplacingMergeTree parts and removes duplicates.
        """
        logger.info(f"Optimizing {table_name}...")

        self.client.command(f"OPTIMIZE TABLE {table_name} FINAL")

        logger.info(f"Optimization complete for {table_name}")
