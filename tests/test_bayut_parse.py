from datetime import date
import unittest

from holocron.sources.bayut.parse import (
    format_bayut_range,
    parse_date,
    rental_row,
    sale_row,
)


class BayutParseTest(unittest.TestCase):
    def test_parse_date_and_range_format(self) -> None:
        start = parse_date("2026-03-01")
        end = parse_date("2026-03-03")
        self.assertEqual(start, date(2026, 3, 1))
        self.assertEqual(format_bayut_range(start, end), "20260301-20260303")

    def test_sale_row_maps_source_payload(self) -> None:
        row = sale_row(
            release_id="run-1",
            scraped_at="2026-03-21 00:00:00",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 3),
            page=2,
            hit={
                "transaction_hash_id": "tx-1",
                "date_transaction_nk": "2026-03-02",
                "transaction_amount": 1250000,
                "bayut_leaf_location_name_en": "Aurora",
                "bayut_location_l3_name_en": "Dubai Marina",
                "unit_number": "1201",
                "has_kpi_value": True,
            },
        )
        self.assertEqual(row.transaction_hash_id, "tx-1")
        self.assertEqual(row.transaction_amount, "1250000")
        self.assertEqual(row.bayut_leaf_location_name_en, "Aurora")
        self.assertEqual(row.bayut_location_l3_name_en, "Dubai Marina")
        self.assertEqual(row.unit_number, "1201")
        self.assertEqual(row.has_kpi_value, 1)
        self.assertEqual(row.window_start_date, "2026-03-01")
        self.assertEqual(row.window_end_date, "2026-03-03")

    def test_rental_row_maps_source_payload(self) -> None:
        row = rental_row(
            release_id="run-1",
            scraped_at="2026-03-21 00:00:00",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 3),
            page=1,
            hit={
                "transaction_hash_id": "rtx-1",
                "date_transaction_nk": "2026-03-02",
                "date_start_nk": "2026-04-01",
                "date_end_nk": "2027-03-31",
                "rent_contract_duration_months": 12,
                "rent_contract_renewal_status_name": "Renewed",
                "has_kpi_value": False,
            },
        )
        self.assertEqual(row.transaction_hash_id, "rtx-1")
        self.assertEqual(row.contract_start_date, "2026-04-01")
        self.assertEqual(row.contract_end_date, "2027-03-31")
        self.assertEqual(row.rent_contract_duration_months, "12")
        self.assertEqual(row.rent_contract_renewal_status_name, "Renewed")
        self.assertEqual(row.has_kpi_value, 0)


if __name__ == "__main__":
    unittest.main()

