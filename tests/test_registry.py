import unittest

from etl.core.dataset_registry import DATASET_SPECS


class DatasetRegistryTest(unittest.TestCase):
    def test_dataset_registry_has_expected_modes(self) -> None:
        self.assertEqual(DATASET_SPECS["dld"].mode, "full_snapshot")
        self.assertEqual(DATASET_SPECS["gis"].mode, "full_snapshot")
        self.assertEqual(DATASET_SPECS["dxbi"].mode, "reference_replace")

    def test_all_registered_tables_have_filenames(self) -> None:
        for dataset_spec in DATASET_SPECS.values():
            self.assertTrue(dataset_spec.tables)
            for table in dataset_spec.tables:
                self.assertTrue(table.filename)
                self.assertTrue(table.table_name)


if __name__ == "__main__":
    unittest.main()
