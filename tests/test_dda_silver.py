import unittest

from holocron.assets.dda_silver import (
    _centroid_from_rings,
    _json_array_string,
    _normalized_identifier_list,
    _parse_plot_coordinates,
    _parse_ring_coordinates,
)


class DdaSilverTest(unittest.TestCase):
    def test_parse_plot_coordinates_handles_valid_points(self) -> None:
        self.assertEqual(
            _parse_plot_coordinates("[[500000.0,2800000.0],[500100.0,2800100.0]]"),
            [[500000.0, 2800000.0], [500100.0, 2800100.0]],
        )

    def test_parse_ring_coordinates_handles_nested_rings(self) -> None:
        self.assertEqual(
            _parse_ring_coordinates("[[[55.1,25.1],[55.2,25.2]],[[55.3,25.3],[55.4,25.4]]]"),
            [
                [[55.1, 25.1], [55.2, 25.2]],
                [[55.3, 25.3], [55.4, 25.4]],
            ],
        )

    def test_centroid_from_rings_returns_lat_lng_average(self) -> None:
        self.assertEqual(
            _centroid_from_rings([[[55.1, 25.1], [55.3, 25.3]]]),
            (25.200000000000003, 55.2),
        )

    def test_normalized_identifier_list_splits_normalizes_and_deduplicates(self) -> None:
        self.assertEqual(
            _normalized_identifier_list("123-A, 123 B, , 123-a"),
            ["123a", "123b"],
        )

    def test_json_array_string_falls_back_to_empty_array(self) -> None:
        self.assertEqual(_json_array_string(""), "[]")
        self.assertEqual(_json_array_string("not-json"), "[]")


if __name__ == "__main__":
    unittest.main()
