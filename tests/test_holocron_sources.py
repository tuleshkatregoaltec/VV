import unittest

from holocron.sources import SOURCES, SOURCES_BY_NAME


class HolocronSourcesTest(unittest.TestCase):
    def test_sources_are_registered_by_name(self) -> None:
        self.assertEqual({source.name for source in SOURCES}, set(SOURCES_BY_NAME))

    def test_tables_have_declared_csv_names_and_table_names(self) -> None:
        for source in SOURCES:
            self.assertTrue(source.tables)
            for table in source.tables:
                self.assertTrue(table.csv_name)
                self.assertTrue(table.table_name)


if __name__ == "__main__":
    unittest.main()
