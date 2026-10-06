from datetime import date

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
    "location_name": "Dubai Marina",
    "property_type": "Apartment",
    "property_usage": "Residential",
    "bedrooms": "2 Beds",
    "status": "Ready",
    "size_sqm": 100.0,
    "price_aed": 1_500_000,
    "price_per_sqm": 15_000,
}

RENTAL_ROW = {
    "contract_id": "R-1",
    "lease_start": date(2026, 5, 1),
    "lease_end": date(2027, 4, 30),
    "unit_number": "G29",
    "building_name": "Marina Tower A",
    "project_name": "Marina Tower",
    "location_name": "Dubai Marina",
    "property_type": "Apartment",
    "property_usage": "Residential",
    "bedrooms": "1 Bed",
    "size_sqm": 100.0,
    "annual_rent_aed": 120_000,
    "contract_amount_aed": 120_000,
    "term_months": 12.0,
    "contract_type": "New",
}


async def test_sales_excel_export_names_dxbi_and_caps_rows(monkeypatch):
    seen = {}

    async def fake_query(sql, params):
        seen["sql"] = sql
        seen["params"] = params
        return [SALES_ROW]

    monkeypatch.setattr(queries, "query", fake_query)

    stream = await transaction_service.export_sales_transactions(
        SalesFilters(location="Dubai Marina")
    )

    assert "dxbi_sales_unit_events" in seen["sql"]
    assert "ch_transactions" not in seen["sql"]  # No DLD row reaches the DXBI page.
    assert "LIMIT {max_rows:Int32}" in seen["sql"]
    assert seen["params"]["max_rows"] == transaction_service.MAX_TRANSACTION_EXPORT_ROWS

    workbook = load_workbook(stream)
    assert workbook.sheetnames[:2] == ["Metadata", "Sales Transactions"]
    metadata = workbook["Metadata"]
    assert (metadata["B1"].value, metadata["B4"].value) == (
        "Vitevue",
        "DXBInteract (DXBI) sold transactions",
    )
    assert metadata["B5"].value == 1
    assert metadata["B6"].value == transaction_service.MAX_TRANSACTION_EXPORT_ROWS
    assert "location=Dubai Marina" in metadata["B7"].value
    sheet = workbook["Sales Transactions"]
    assert [cell.value for cell in sheet[6]] == transaction_service.SALES_EXPORT_HEADERS
    assert (sheet["A7"].value, sheet["C7"].value, sheet["L7"].value) == ("T-1", "1904", 15_000)


async def test_sales_csv_export_is_the_raw_rows_without_workbook_metadata(monkeypatch):
    async def fake_query(sql, params):
        return [SALES_ROW]

    monkeypatch.setattr(queries, "query", fake_query)

    stream = await transaction_service.export_sales_transactions(SalesFilters(), file_format="csv")

    content = stream.getvalue().decode("utf-8-sig")
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

    async def fake_query(sql, params):
        return [dangerous_row]

    monkeypatch.setattr(queries, "query", fake_query)

    csv_stream = await transaction_service.export_sales_transactions(
        SalesFilters(), file_format="csv"
    )
    csv_content = csv_stream.getvalue().decode("utf-8-sig")
    for escaped in ("'=HYPERLINK", "'+SUM(1,1)", "'-2+3", "'@malicious", "'\t=cmd"):
        assert escaped in csv_content

    excel_stream = await transaction_service.export_sales_transactions(SalesFilters())
    worksheet = load_workbook(excel_stream)["Sales Transactions"]
    assert worksheet["C7"].value == "'@malicious"
    assert worksheet["D7"].value == "'+SUM(1,1)"
    assert worksheet["E7"].value.startswith("'=HYPERLINK")
    assert worksheet["F7"].value == "'-2+3"
    assert worksheet["G7"].value == "'\t=cmd"


async def test_rental_export_selected_ids_override_filters(monkeypatch):
    seen = {}

    async def fake_query(sql, params):
        seen["sql"] = sql
        seen["params"] = params
        return [RENTAL_ROW]

    monkeypatch.setattr(queries, "query", fake_query)

    stream = await transaction_service.export_rental_contracts(
        RentalFilters(location="Elsewhere", timeframe_days=30), contract_ids="R-1, R-2"
    )

    assert "contract_id IN {ids:Array(String)}" in seen["sql"]
    assert "location_name = {location:String}" not in seen["sql"]
    assert seen["params"]["ids"] == ["R-1", "R-2"]
    workbook = load_workbook(stream)
    assert workbook["Metadata"]["B4"].value == "DXBInteract (DXBI) rental contracts"
    sheet = workbook["Rental Contracts"]
    assert [cell.value for cell in sheet[6]] == transaction_service.RENTAL_EXPORT_HEADERS
    assert sheet["A7"].value == "R-1"
    assert sheet["D7"].value == "G29"
