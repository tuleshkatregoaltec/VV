import unittest

from holocron.sources.pf_transactions.extract import (
    LocationNode,
    _path_override_from_transaction_url,
    _resolved_transaction_path,
    _root_node_ids,
)


class PfTransactionsExtractTest(unittest.TestCase):
    def test_path_override_is_parsed_from_transaction_url(self) -> None:
        self.assertEqual(
            _path_override_from_transaction_url(
                "/en/transactions/buy/dubai/dubai-marina", purpose="buy"
            ),
            "dubai/dubai-marina",
        )
        self.assertEqual(
            _path_override_from_transaction_url(
                "/en/transactions/rent/dubai/downtown-dubai", purpose="rent"
            ),
            "dubai/downtown-dubai",
        )
        self.assertEqual(
            _path_override_from_transaction_url(
                "/en/transactions/buy/dubai/dubai-marina", purpose="rent"
            ),
            "",
        )

    def test_resolved_transaction_path_prefers_override(self) -> None:
        node = LocationNode(
            purpose="buy",
            pf_location_id="3155",
            parent_pf_location_id="722",
            city_pf_location_id="1",
            path_ids="1.50.722.3155",
            path_depth=4,
            level_type="TOWER",
            location_name="Marina Quays East",
            slug="dubai-marina-marina-quays-marina-quays-east",
            city_slug="dubai",
        )
        self.assertEqual(
            _resolved_transaction_path(node),
            "dubai/dubai-marina-marina-quays-marina-quays-east",
        )
        self.assertEqual(
            _resolved_transaction_path(
                node, path_overrides={"3155": "dubai/dubai-marina-marina-quays-east"}
            ),
            "dubai/dubai-marina-marina-quays-east",
        )

    def test_root_nodes_prefer_city_then_community_depths(self) -> None:
        city = LocationNode(
            purpose="buy",
            pf_location_id="1",
            parent_pf_location_id="",
            city_pf_location_id="1",
            path_ids="1",
            path_depth=1,
            level_type="CITY",
            location_name="Dubai",
            slug="dubai",
            city_slug="dubai",
        )
        community = LocationNode(
            purpose="buy",
            pf_location_id="50",
            parent_pf_location_id="1",
            city_pf_location_id="1",
            path_ids="1.50",
            path_depth=2,
            level_type="COMMUNITY",
            location_name="Dubai Marina",
            slug="dubai-marina",
            city_slug="dubai",
        )
        leaf = LocationNode(
            purpose="buy",
            pf_location_id="3155",
            parent_pf_location_id="722",
            city_pf_location_id="1",
            path_ids="1.50.722.3155",
            path_depth=4,
            level_type="TOWER",
            location_name="Marina Quays East",
            slug="dubai-marina-marina-quays-marina-quays-east",
            city_slug="dubai",
        )
        self.assertEqual(_root_node_ids({"1": city, "50": community, "3155": leaf}), ["1"])
        self.assertEqual(_root_node_ids({"50": community, "3155": leaf}), ["50"])


if __name__ == "__main__":
    unittest.main()
