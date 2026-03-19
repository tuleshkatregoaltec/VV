import json
import unittest

from holocron.sources.dxbi_transactions.extract import (
    _extract_pagination_calls,
    _load_page_urls,
    parse_rental_transactions_html,
    parse_sales_transactions_html,
)


SALES_HTML = """
<table id="report_table_soldhistory">
  <tbody>
    <tr>
      <td>
        <div class="bold-title">Binghatti Starlight, Al Jaddaf</div>
        <p>Ready</p>
      </td>
      <td>
        AED 1,250,000
        <span>(+10.4%)</span>
        AED 1,540 /sqft
      </td>
      <td>
        811 sqft
        811 sqft
        1 Bed
      </td>
      <td>
        14 Feb 2026
        Resale market
      </td>
    </tr>
  </tbody>
</table>
"""


RENTALS_HTML = """
<table id="report_table_rentHistory">
  <tbody>
    <tr>
      <td>
        <div class="bold-title">Binghatti Starlight, Al Jaddaf</div>
        <p>Renewed</p>
      </td>
      <td>
        811 sqft
        1 Bed
      </td>
      <td>
        AED 95,000
        7.2%
      </td>
      <td>
        01 Jan 2026
        31 Dec 2026
        12 months
      </td>
      <td>
        AED 1,200,000
      </td>
    </tr>
  </tbody>
</table>
"""

PAGINATION_HTML = """
<div class="t-Report-paginationText">
  <strong>1</strong>
  <a href="javascript:apex.widget.report.paginate('192', 'abc', {min:14,max:13,fetched:13});">2</a>
  <a href="javascript:apex.widget.report.paginate('192', 'abc', {min:27,max:13,fetched:13});">3</a>
</div>
<div class="t-Report-paginationText">
  <strong>1</strong>
  <a href="javascript:apex.widget.report.paginate('555', 'def', {min:16,max:15,fetched:15});">2</a>
</div>
"""


class DxbiTransactionsExtractTest(unittest.TestCase):
    def test_load_page_urls_merges_and_dedupes_sources(self) -> None:
        urls = _load_page_urls(
            page_urls_text="https://dxbinteract.com/projects/a\nhttps://dxbinteract.com/projects/b",
            page_urls_file="",
        )
        self.assertEqual(
            urls,
            [
                "https://dxbinteract.com/projects/a",
                "https://dxbinteract.com/projects/b",
            ],
        )

    def test_load_page_urls_defaults_to_homepage(self) -> None:
        self.assertEqual(_load_page_urls(page_urls_text="", page_urls_file=""), ["https://dxbinteract.com/"])

    def test_extract_pagination_calls_by_table_index(self) -> None:
        sales = _extract_pagination_calls(PAGINATION_HTML, table_index=0)
        rentals = _extract_pagination_calls(PAGINATION_HTML, table_index=1)
        self.assertEqual(len(sales), 2)
        self.assertEqual(len(rentals), 1)
        self.assertEqual(sales[0]["region_id"], "192")
        self.assertEqual(sales[0]["options"], {"min": 14, "max": 13, "fetched": 13})
        self.assertEqual(rentals[0]["region_id"], "555")

    def test_parse_sales_transactions_html(self) -> None:
        rows = parse_sales_transactions_html(
            SALES_HTML,
            run_id="run-1",
            source_page="https://dxbinteract.com/projects/binghatti-starlight",
            scope_slug="binghatti-starlight",
            filters={"sort": "newest"},
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.location_path, "Binghatti Starlight, Al Jaddaf")
        self.assertEqual(row.status_text, "Ready")
        self.assertEqual(row.price_aed, "1250000")
        self.assertEqual(row.capital_gain_text, "+10.4%")
        self.assertEqual(row.price_per_sqft_aed, "1540")
        self.assertEqual(row.transaction_size_sqft, "811")
        self.assertEqual(row.transaction_date, "2026-02-14")
        self.assertEqual(row.seller_type, "Resale market")
        self.assertEqual(json.loads(row.filters_json), {"sort": "newest"})
        self.assertTrue(row.transaction_key)

    def test_parse_rental_transactions_html(self) -> None:
        rows = parse_rental_transactions_html(
            RENTALS_HTML,
            run_id="run-1",
            source_page="https://dxbinteract.com/projects/binghatti-starlight",
            scope_slug="binghatti-starlight",
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.location_path, "Binghatti Starlight, Al Jaddaf")
        self.assertEqual(row.status_text, "Renewed")
        self.assertEqual(row.bedrooms_label, "1 Bed")
        self.assertEqual(row.size_sqft, "811")
        self.assertEqual(row.annual_rent_aed, "95000")
        self.assertEqual(row.rental_yield_pct, "7.2")
        self.assertEqual(row.lease_start_date, "2026-01-01")
        self.assertEqual(row.lease_end_date, "2026-12-31")
        self.assertEqual(row.duration_text, "12 months")
        self.assertEqual(row.purchase_price_aed, "1200000")
        self.assertTrue(row.transaction_key)


if __name__ == "__main__":
    unittest.main()
