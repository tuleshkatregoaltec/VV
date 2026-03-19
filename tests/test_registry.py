import unittest

from holocron.sources import SOURCES


class DatasetRegistryTest(unittest.TestCase):
    def test_dataset_registry_has_expected_modes(self) -> None:
        modes = {source.name: source.mode for source in SOURCES}
        self.assertEqual(modes["dld_bulk_data"], "full_snapshot")
        self.assertEqual(modes["dda_planning_layers"], "full_snapshot")
        self.assertEqual(modes["dxbi_lookups"], "reference_replace")
        self.assertEqual(modes["dxbi_transactions"], "reference_replace")
        self.assertEqual(modes["pf_locations"], "reference_replace")
        self.assertEqual(modes["pf_transactions"], "reference_replace")

    def test_dataset_registry_has_expected_providers(self) -> None:
        providers = {source.name: source.provider_name for source in SOURCES}
        self.assertEqual(providers["bay_transactions"], "bayut")
        self.assertEqual(providers["dld_bulk_data"], "dld")
        self.assertEqual(providers["dxbi_lookups"], "dxbinteract")
        self.assertEqual(providers["dxbi_transactions"], "dxbinteract")
        self.assertEqual(providers["geo_buildings"], "geo_api")
        self.assertEqual(providers["dda_planning_layers"], "dda")
        self.assertEqual(providers["pf_locations"], "propertyfinder")
        self.assertEqual(providers["pf_transactions"], "propertyfinder")

    def test_all_registered_tables_have_filenames(self) -> None:
        for source in SOURCES:
            self.assertTrue(source.tables)
            for table in source.tables:
                self.assertTrue(table.csv_name)
                self.assertTrue(table.table_name)


if __name__ == "__main__":
    unittest.main()
