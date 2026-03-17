import unittest

from holocron.sources import SOURCES


class DatasetRegistryTest(unittest.TestCase):
    def test_dataset_registry_has_expected_modes(self) -> None:
        modes = {source.name: source.mode for source in SOURCES}
        self.assertEqual(modes["dld"], "full_snapshot")
        self.assertEqual(modes["gis"], "full_snapshot")
        self.assertEqual(modes["dxbi"], "reference_replace")

    def test_all_registered_tables_have_filenames(self) -> None:
        for source in SOURCES:
            self.assertTrue(source.tables)
            for table in source.tables:
                self.assertTrue(table.csv_name)
                self.assertTrue(table.table_name)


if __name__ == "__main__":
    unittest.main()
