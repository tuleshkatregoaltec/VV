import csv
import io
import re
from datetime import date, timedelta

from openpyxl import load_workbook

from app.transaction import exports as transaction_service
from app.transaction import queries
from app.transaction.models import RentalFilters, SalesFilters

SALES_ROW = {
    "transaction_id": "T-1",
    "transaction_date": date(2026, 5, 1),
    "unit_number": "1904",
    "building_name": "Marina Tower A",
    "project_name": "Marina Tower",
    "master_project": "Dubai Marina",
    "dld_area": "Marsa Dubai",
    "location": "Marina Tower A, Marina Tower, Dubai Marina, Marsa Dubai, Dubai",
    "map_url": "https://www.google.com/maps/search/?api=1&query=25.08%2C55.14",
    "location_name": "Dubai Marina",
    "property_type": "Apartment",
    "property_usage": "Residential",
    "bedrooms": "2 Beds",
    "status": "Ready",
    "size_sqft": 1_000.0,
    "price_aed": 1_500_000,
    "price_per_sqft": 1_500,
}

RENTAL_ROW = {
    "contract_id": "R-1",
    "lease_start": date(2026, 5, 1),
    "lease_end": date(2027, 4, 30),
    "unit_number": "G29",
    "building_name": "Marina Tower A",
    "project_name": "Marina Tower",
    "master_project": "Dubai Marina",
    "dld_area": "Marsa Dubai",
    "location": "Marina Tower A, Marina Tower, Dubai Marina, Marsa Dubai, Dubai",
    "map_url": "https://www.google.com/maps/search/?api=1&query=25.08%2C55.14",
    "location_name": "Dubai Marina",
    "property_type": "Apartment",
    "property_usage": "Residential",
    "bedrooms": "1 Bed",
    "size_sqft": 1_000.0,
    "annual_rent_aed": 120_000,
    "contract_amount_aed": 120_000,
    "term_months": 12.0,
    "contract_type": "New",
}


def fake_warehouse(monkeypatch, rows, *, matching=None, seen=None):
    """The page-table reads an export makes: its count, then its rows in keyset chunks."""

    async def fake_query(sql, params):
        if seen is not None:
            seen.setdefault("calls", []).append((sql, dict(params)))
        if "count() AS total" in sql:
            return [{"total": len(rows) if matching is None else matching}]
        if "after_date" in params:
            return []
        return rows[: params["chunk_rows"]]

    monkeypatch.setattr(queries, "query", fake_query)


async def workbook_of(export):
    return load_workbook(io.BytesIO(await export.content()))


async def csv_of(export) -> str:
    return (await export.content()).decode("utf-8-sig")


def assert_no_provider_attribution(workbook):
    # Metadata and hidden sheets are part of what the customer downloads, too.
    for sheet in workbook:
        for row in sheet.values:
            for value in row:
                assert not re.search(r"\b(DLD|DXBI|DXBInteract)\b", str(value), re.I)


async def test_sales_excel_export_keeps_metadata_without_exposing_providers(monkeypatch):
    seen = {}
    fake_warehouse(monkeypatch, [SALES_ROW], seen=seen)

    export = await transaction_service.export_sales_transactions(
        SalesFilters(location="Dubai Marina")
    )
    workbook = await workbook_of(export)

    sql, params = seen["calls"][-1]
    assert "dxbi_sales_page" in sql
    assert "ch_transactions" not in sql  # No DLD row reaches the DXBI page.
    assert "LIMIT {chunk_rows:Int32}" in sql
    assert params["chunk_rows"] == transaction_service.EXPORT_CHUNK_ROWS
    assert workbook.sheetnames[:2] == ["Metadata", "Sales Transactions"]
    metadata = workbook["Metadata"]
    assert metadata["B1"].value == "Vitevue"
    assert metadata["B4"].value == 1
    assert metadata["B5"].value == transaction_service.MAX_TRANSACTION_EXPORT_ROWS
    assert "location=Dubai Marina" in metadata["B6"].value
    assert_no_provider_attribution(workbook)
    sheet = workbook["Sales Transactions"]
    assert [cell.value for cell in sheet[5]] == transaction_service.SALES_EXPORT_HEADERS
    assert (sheet["A6"].value, sheet["C6"].value, sheet["P6"].value) == ("T-1", "1904", 1_500)


async def test_sales_csv_export_is_the_raw_rows_without_workbook_metadata(monkeypatch):
    fake_warehouse(monkeypatch, [SALES_ROW])

    export = await transaction_service.export_sales_transactions(SalesFilters(), file_format="csv")

    content = await csv_of(export)
    assert content.startswith("Transaction ID,Date,Unit,Building")
    assert "Vitevue" not in content
    assert "T-1,2026-05-01,1904,Marina Tower A" in content


async def test_exports_escape_spreadsheet_formula_strings(monkeypatch):
    dangerous_row = {
        **SALES_ROW,
        "project_name": '=HYPERLINK("https://example.com")',
        "building_name": "+SUM(1,1)",
        "location_name": "-2+3",
        "unit_number": "@malicious",
        "property_type": "\t=cmd",
    }

    fake_warehouse(monkeypatch, [dangerous_row])

    csv_export = await transaction_service.export_sales_transactions(
        SalesFilters(), file_format="csv"
    )
    csv_content = await csv_of(csv_export)
    for escaped in ("'=HYPERLINK", "'+SUM(1,1)", "'-2+3", "'@malicious", "'\t=cmd"):
        assert escaped in csv_content

    excel_export = await transaction_service.export_sales_transactions(SalesFilters())
    worksheet = (await workbook_of(excel_export))["Sales Transactions"]
    assert worksheet["C6"].value == "'@malicious"
    assert worksheet["D6"].value == "'+SUM(1,1)"
    assert worksheet["E6"].value.startswith("'=HYPERLINK")
    assert worksheet["J6"].value == "'-2+3"
    assert worksheet["K6"].value == "'\t=cmd"


async def test_rental_export_selected_ids_override_filters(monkeypatch):
    seen = {}
    fake_warehouse(monkeypatch, [RENTAL_ROW], seen=seen)

    export = await transaction_service.export_rental_contracts(
        RentalFilters(location="Elsewhere", timeframe_days=30), contract_ids="R-1, R-2"
    )
    workbook = await workbook_of(export)

    sql, params = seen["calls"][-1]
    assert "contract_id IN {ids:Array(String)}" in sql
    assert "has(dxbi_locations, {location:String})" not in sql
    assert params["ids"] == ["R-1", "R-2"]
    assert_no_provider_attribution(workbook)
    sheet = workbook["Rental Contracts"]
    assert [cell.value for cell in sheet[5]] == transaction_service.RENTAL_EXPORT_HEADERS
    assert sheet["A6"].value == "R-1"
    assert sheet["D6"].value == "G29"


async def test_selected_export_metadata_does_not_claim_ignored_filters(monkeypatch):
    # A downloaded workbook must accurately explain its contents to another analyst.
    # Selected IDs override the screen filters, so those filters were not applied.
    fake_warehouse(monkeypatch, [RENTAL_ROW])
    export = await transaction_service.export_rental_contracts(
        RentalFilters(location="Elsewhere", timeframe_days=7), contract_ids="R-1"
    )
    metadata = (await workbook_of(export))["Metadata"]["B6"].value
    assert "contract_ids=R-1" in metadata
    assert "location=Elsewhere" not in metadata
    assert "timeframe_days=7" not in metadata


async def test_selected_sale_export_metadata_omits_unapplied_filters(monkeypatch):
    fake_warehouse(monkeypatch, [SALES_ROW])
    export = await transaction_service.export_sales_transactions(
        SalesFilters(location="Elsewhere", timeframe_days=7), transaction_ids=" T-1, "
    )
    assert (await workbook_of(export))["Metadata"]["B6"].value == "transaction_ids=T-1"

    export = await transaction_service.export_sales_transactions(
        SalesFilters(location="Dubai Marina"), transaction_ids=" , "
    )
    assert "location=Dubai Marina" in (await workbook_of(export))["Metadata"]["B6"].value


# Truncation: the CSV used to stop at 50,000 rows with no word of it (2026-11-15 audit).


async def test_a_csv_past_the_row_cap_says_it_was_truncated(monkeypatch):
    fake_warehouse(monkeypatch, [SALES_ROW], matching=73_412)

    export = await transaction_service.export_sales_transactions(SalesFilters(), file_format="csv")
    lines = (await csv_of(export)).strip().splitlines()

    assert export.truncated
    assert export.headers() == {
        "X-Export-Rows": "50000",
        "X-Export-Matching-Rows": "73412",
        "X-Export-Truncated": "true",
    }
    assert lines[-1].startswith('"Truncated: this file holds the newest 50,000 of 73,412')


async def test_a_workbook_past_the_row_cap_says_it_was_truncated(monkeypatch):
    fake_warehouse(monkeypatch, [RENTAL_ROW], matching=60_000)

    export = await transaction_service.export_rental_contracts(RentalFilters())
    metadata = (await workbook_of(export))["Metadata"]

    assert (metadata["A7"].value, metadata["B7"].value) == ("Matching rows", 60_000)
    assert metadata["B8"].value.startswith("Truncated: this file holds the newest 50,000")


async def test_a_complete_export_is_not_marked_truncated(monkeypatch):
    fake_warehouse(monkeypatch, [SALES_ROW])

    export = await transaction_service.export_sales_transactions(SalesFilters(), file_format="csv")

    assert export.headers()["X-Export-Truncated"] == "false"
    assert "Truncated" not in await csv_of(export)


async def test_export_rows_stream_in_keyset_chunks(monkeypatch):
    # Rows arrive a chunk at a time, each chunk starting after the last row of the one before.
    rows = [
        {
            **SALES_ROW,
            "transaction_id": f"T-{n}",
            "transaction_date": date(2026, 5, 1) - timedelta(days=n),
        }
        for n in range(5)
    ]
    calls = []

    seen_sql = []

    async def fake_query(sql, params):
        calls.append(dict(params))
        seen_sql.append(sql)
        if "count() AS total" in sql:
            return [{"total": 5}]
        start = 0 if "after_id" not in params else int(params["after_id"][2:]) + 1
        return rows[start : start + params["chunk_rows"]]

    monkeypatch.setattr(queries, "query", fake_query)
    monkeypatch.setattr(transaction_service, "EXPORT_CHUNK_ROWS", 2)

    export = await transaction_service.export_sales_transactions(SalesFilters(), file_format="csv")
    records = list(csv.DictReader(io.StringIO(await csv_of(export))))

    assert [r["Transaction ID"] for r in records] == [f"T-{n}" for n in range(5)]
    assert [c.get("after_id") for c in calls[1:]] == [None, "T-1", "T-3"]
    chunk_sql = [sql for sql in seen_sql if "after_id" in sql]
    assert chunk_sql and all("transaction_id < {after_id:String}" in sql for sql in chunk_sql)


async def test_export_response_carries_the_truncation_headers(client, monkeypatch):
    fake_warehouse(monkeypatch, [SALES_ROW], matching=50_001)

    response = await client.get("/api/v1/transactions/sales/export?format=csv")

    assert response.status_code == 200, response.text
    assert response.headers["x-export-truncated"] == "true"
    assert response.headers["x-export-matching-rows"] == "50001"
    assert "X-Export-Truncated" in response.headers["access-control-expose-headers"]
    assert response.text.strip().splitlines()[-1].startswith('"Truncated:')
