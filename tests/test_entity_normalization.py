import unittest
from datetime import date

from holocron.assets.transaction_silver import (
    _bay_hierarchy_names,
    _pf_area_name,
    _pf_building_and_project,
    _sort_date_key,
)
from holocron.lib.entity_normalization import (
    normalize_identifier,
    normalize_text,
    split_location_path,
    token_bag,
)


class EntityNormalizationTest(unittest.TestCase):
    def test_normalize_text_expands_common_real_estate_tokens(self) -> None:
        self.assertEqual(normalize_text("JVC Twr. IV, L.L.C"), "jumeirah village circle tower 4")

    def test_normalize_identifier_collapses_spaces(self) -> None:
        self.assertEqual(normalize_identifier("Unit 12-B"), "unit12b")

    def test_token_bag_preserves_order_after_normalization(self) -> None:
        self.assertEqual(token_bag("Mulberry 1A"), ["mulberry", "1a"])

    def test_split_location_path_splits_common_delimiters(self) -> None:
        self.assertEqual(
            split_location_path("Binghatti Starlight, Al Jaddaf"),
            ["Binghatti Starlight", "Al Jaddaf"],
        )

    def test_bay_hierarchy_names_dedupes_repeated_levels(self) -> None:
        row = {
            "bayut_location_l3_name_en": "Dubai Marina",
            "bayut_location_l4_name_en": "Marina Promenade",
            "bayut_location_l5_name_en": "Marina Promenade",
            "bayut_location_l6_name_en": "",
            "bayut_leaf_location_name_en": "Aurora",
        }
        self.assertEqual(
            _bay_hierarchy_names(row),
            ["Dubai Marina", "Marina Promenade", "Aurora"],
        )

    def test_pf_tower_rows_map_to_building_and_project(self) -> None:
        self.assertEqual(
            _pf_building_and_project("tower", "Mulberry 1", "Mulberry"),
            ("building", "Mulberry 1", "Mulberry"),
        )

    def test_pf_area_name_skips_dubai_city_label(self) -> None:
        self.assertEqual(
            _pf_area_name("tower", ["Dubai", "Dubai Hills Estate"], "Mulberry 1"),
            "Dubai Hills Estate",
        )

    def test_sort_date_key_handles_missing_and_valid_dates(self) -> None:
        values = [date(2026, 2, 14), None]
        sorted_values = sorted(values, key=_sort_date_key)
        self.assertEqual(sorted_values, [None, date(2026, 2, 14)])


if __name__ == "__main__":
    unittest.main()
