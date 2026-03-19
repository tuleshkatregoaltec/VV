import re
import unittest
from pathlib import Path

from holocron.sources import SOURCES


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "holocron/lib/sql/clickhouse_schema.sql"
CREATE_TABLE_PATTERN = re.compile(r"CREATE TABLE IF NOT EXISTS ([a-zA-Z0-9_]+)")


class SchemaRegistryTest(unittest.TestCase):
    def test_all_registered_tables_exist_in_schema(self) -> None:
        schema_sql = SCHEMA_PATH.read_text()
        declared_tables = set(CREATE_TABLE_PATTERN.findall(schema_sql))
        for source in SOURCES:
            for table in source.tables:
                self.assertIn(table.table_name, declared_tables)

    def test_schema_has_no_duplicate_create_table_statements(self) -> None:
        schema_sql = SCHEMA_PATH.read_text()
        declared_tables = CREATE_TABLE_PATTERN.findall(schema_sql)
        self.assertEqual(len(declared_tables), len(set(declared_tables)))


if __name__ == "__main__":
    unittest.main()
