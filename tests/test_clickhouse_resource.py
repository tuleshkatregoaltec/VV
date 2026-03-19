import unittest

from holocron.resources.clickhouse import ClickHouseResource


class ClickHouseResourceTest(unittest.TestCase):
    def test_deduped_select_sql_uses_key_filter_for_single_key(self) -> None:
        sql = ClickHouseResource._deduped_select_sql(
            table="bay_sale_transactions",
            staging="bay_sale_transactions_staging_run",
            key_columns=("transaction_hash_id",),
            table_columns=["transaction_hash_id", "transaction_amount", "scraped_at"],
        )
        self.assertIn("FROM bay_sale_transactions_staging_run", sql)
        self.assertIn("GROUP BY transaction_hash_id", sql)
        self.assertIn("any(transaction_amount) AS transaction_amount", sql)
        self.assertIn("incoming.transaction_hash_id", sql)
        self.assertIn("SELECT transaction_hash_id FROM bay_sale_transactions", sql)

    def test_deduped_select_sql_uses_tuple_filter_for_composite_key(self) -> None:
        sql = ClickHouseResource._deduped_select_sql(
            table="example_table",
            staging="example_table_staging_run",
            key_columns=("key_a", "key_b"),
            table_columns=["key_a", "key_b", "value"],
        )
        self.assertIn("GROUP BY key_a, key_b", sql)
        self.assertIn("tuple(incoming.key_a, incoming.key_b)", sql)
        self.assertIn("SELECT tuple(key_a, key_b) FROM example_table", sql)

    def test_deduped_select_sql_rejects_missing_key_columns(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing dedupe columns"):
            ClickHouseResource._deduped_select_sql(
                table="example_table",
                staging="example_table_staging_run",
                key_columns=("missing_key",),
                table_columns=["other_key", "value"],
            )


if __name__ == "__main__":
    unittest.main()
