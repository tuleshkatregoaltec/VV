import unittest

from holocron.transforms.pf_locations import build_hierarchy_rows, normalize_level


class PfLocationsTransformTest(unittest.TestCase):
    def test_normalize_level_maps_known_levels(self) -> None:
        self.assertEqual(normalize_level("CITY", 1), "city")
        self.assertEqual(normalize_level("COMMUNITY", 2), "community")
        self.assertEqual(normalize_level("SUBCOMMUNITY", 3), "subcommunity")
        self.assertEqual(normalize_level("TOWER", 4), "tower")
        self.assertEqual(normalize_level("DISTRICT", 5), "district")

    def test_build_hierarchy_rows_shapes_parent_and_ancestor_fields(self) -> None:
        rows = [
            {
                "release_id": "run-1",
                "scraped_at": "2026-03-21 00:00:00",
                "pf_location_id": "1",
                "parent_pf_location_id": "",
                "city_pf_location_id": "1",
                "path_ids": "1",
                "path_depth": 1,
                "level_type": "CITY",
                "location_name": "Dubai",
                "alternate_name": "",
                "slug": "dubai",
                "city_slug": "dubai",
                "parent_path_name_en": "",
                "full_path_name_en": "Dubai",
                "breadcrumbs_json": "[]",
                "is_transaction_visible": 1,
                "is_community_visible": 1,
                "is_subcommunity_visible": 1,
                "is_in_cms": 1,
                "seen_in_buy": 1,
                "seen_in_rent": 1,
                "buy_listing_url": "",
                "rent_listing_url": "",
            },
            {
                "release_id": "run-1",
                "scraped_at": "2026-03-21 00:00:00",
                "pf_location_id": "2",
                "parent_pf_location_id": "1",
                "city_pf_location_id": "1",
                "path_ids": "1.2",
                "path_depth": 2,
                "level_type": "COMMUNITY",
                "location_name": "Dubai Marina",
                "alternate_name": "",
                "slug": "dubai-marina",
                "city_slug": "dubai",
                "parent_path_name_en": "Dubai",
                "full_path_name_en": "Dubai, Dubai Marina",
                "breadcrumbs_json": "[]",
                "is_transaction_visible": 1,
                "is_community_visible": 1,
                "is_subcommunity_visible": 0,
                "is_in_cms": 1,
                "seen_in_buy": 1,
                "seen_in_rent": 0,
                "buy_listing_url": "/buy",
                "rent_listing_url": "",
            },
        ]
        silver_rows = build_hierarchy_rows(rows)
        self.assertEqual(len(silver_rows), 2)
        city_row, community_row = silver_rows
        self.assertEqual(city_row[8], "city")
        self.assertEqual(city_row[21], 0)
        self.assertEqual(community_row[8], "community")
        self.assertEqual(community_row[13], "Dubai")
        self.assertEqual(community_row[17], "[\"1\"]")
        self.assertEqual(community_row[18], "[\"Dubai\"]")
        self.assertEqual(community_row[19], "[\"dubai\"]")
        self.assertEqual(community_row[21], 1)


if __name__ == "__main__":
    unittest.main()
