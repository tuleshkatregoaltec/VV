import csv
from datetime import UTC, datetime
from io import BytesIO, StringIO
from typing import Literal, Optional

from openpyxl import Workbook
from openpyxl.styles import Font

from app.transaction import queries
from app.transaction.models import RentalFilters, SalesFilters

MAX_TRANSACTION_EXPORT_ROWS = 50_000

SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@")

SPREADSHEET_CONTROL_PREFIXES = ("\t", "\r", "\n")


def _active_export_filters(filters: dict[str, object]) -> str:
    active_filters = [
        f"{key}={value}"
        for key, value in filters.items()
        if value is not None and value != "" and value != "All"
    ]
    return ", ".join(active_filters) if active_filters else "None"


def _add_export_metadata(
    workbook: Workbook,
    *,
    title: str,
    generated_at: datetime,
    row_count: int,
    filters: dict[str, object],
) -> None:
    metadata = workbook.create_sheet("Metadata", 0)
    rows = [
        ("Publisher", "Vitevue"),
        ("Dataset", title),
        ("Generated at", generated_at.isoformat()),
        ("Rows exported", row_count),
        ("Maximum filtered rows", MAX_TRANSACTION_EXPORT_ROWS),
        ("Filters applied", _active_export_filters(filters)),
    ]
    for row in rows:
        metadata.append(row)
    for cell in metadata["A"]:
        cell.font = Font(bold=True)


def _add_export_header(
    worksheet,
    *,
    title: str,
    generated_at: datetime,
) -> None:
    worksheet.append(["Vitevue"])
    worksheet.append([title])
    worksheet.append([f"Generated at {generated_at.isoformat()}"])
    worksheet.append([])
    worksheet["A1"].font = Font(bold=True, size=14)
    worksheet["A2"].font = Font(bold=True)


def _sanitize_spreadsheet_value(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value

    stripped = value.lstrip()
    if value.startswith(SPREADSHEET_CONTROL_PREFIXES) or (
        stripped and stripped.startswith(SPREADSHEET_FORMULA_PREFIXES)
    ):
        return f"'{value}"
    return value


def _sanitize_spreadsheet_row(row: list[object]) -> list[object]:
    return [_sanitize_spreadsheet_value(value) for value in row]


def _rows_to_csv(headers: list[str], rows: list[list[object]]) -> BytesIO:
    csv_text = StringIO()
    writer = csv.writer(csv_text)
    writer.writerow(headers)
    writer.writerows(_sanitize_spreadsheet_row(row) for row in rows)

    output = BytesIO()
    output.write(csv_text.getvalue().encode("utf-8-sig"))
    output.seek(0)
    return output


def _workbook(
    *,
    title: str,
    filters: dict[str, object],
    headers: list[str],
    rows: list[list[object]],
) -> BytesIO:
    generated_at = datetime.now(UTC)
    wb = Workbook()
    ws = wb.active
    ws.title = title
    _add_export_metadata(
        wb,
        title=title,
        generated_at=generated_at,
        row_count=len(rows),
        filters=filters,
    )
    _add_export_header(ws, title=title, generated_at=generated_at)
    ws.append(headers)
    for cell in ws[5]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(_sanitize_spreadsheet_row(row))
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output


SALES_EXPORT_HEADERS = [
    "Transaction ID",
    "Date",
    "Unit",
    "Building",
    "Project",
    "Master Project",
    "District",
    "Full Location",
    "Map",
    "Location",
    "Property Type",
    "Bedrooms",
    "Status",
    "Size (sq ft)",
    "Price (AED)",
    "Price/sq ft (AED)",
]

RENTAL_EXPORT_HEADERS = [
    "Contract ID",
    "Start Date",
    "End Date",
    "Unit",
    "Building",
    "Project",
    "Master Project",
    "District",
    "Full Location",
    "Map",
    "Location",
    "Property Type",
    "Bedrooms",
    "Size (sq ft)",
    "Annual Rent (AED)",
    "Contract Amount (AED)",
    "Term (months)",
    "Contract Type",
]


async def export_sales_transactions(
    filters: SalesFilters,
    transaction_ids: Optional[str] = None,
    file_format: Literal["xlsx", "csv"] = "xlsx",
) -> BytesIO:
    """DXBI sales as Excel or CSV: the selected rows, else up to 50,000 filtered rows."""
    results = await queries.export_sales_rows(filters, transaction_ids, MAX_TRANSACTION_EXPORT_ROWS)
    rows = [
        [
            row["transaction_id"],
            row["transaction_date"],
            row["unit_number"],
            row["building_name"],
            row["project_name"],
            row["master_project"],
            row["dld_area"],
            row["location"],
            row["map_url"],
            row["location_name"],
            row["property_type"],
            row["bedrooms"],
            row["status"],
            row["size_sqft"],
            row["price_aed"],
            row["price_per_sqft"],
        ]
        for row in results
    ]
    if file_format == "csv":
        return _rows_to_csv(SALES_EXPORT_HEADERS, rows)
    return _workbook(
        title="Sales Transactions",
        filters=(
            {"transaction_ids": ",".join(queries._ids(transaction_ids))}
            if queries._ids(transaction_ids)
            else filters.model_dump()
        ),
        headers=SALES_EXPORT_HEADERS,
        rows=rows,
    )


async def export_rental_contracts(
    filters: RentalFilters,
    contract_ids: Optional[str] = None,
    file_format: Literal["xlsx", "csv"] = "xlsx",
) -> BytesIO:
    """DXBI leases as Excel or CSV: the selected rows, else up to 50,000 filtered rows."""
    results = await queries.export_rental_rows(filters, contract_ids, MAX_TRANSACTION_EXPORT_ROWS)
    rows = [
        [
            row["contract_id"],
            row["lease_start"],
            row["lease_end"],
            row["unit_number"],
            row["building_name"],
            row["project_name"],
            row["master_project"],
            row["dld_area"],
            row["location"],
            row["map_url"],
            row["location_name"],
            row["property_type"],
            row["bedrooms"],
            row["size_sqft"],
            row["annual_rent_aed"],
            row["contract_amount_aed"],
            row["term_months"],
            row["contract_type"],
        ]
        for row in results
    ]
    if file_format == "csv":
        return _rows_to_csv(RENTAL_EXPORT_HEADERS, rows)
    return _workbook(
        title="Rental Contracts",
        filters=(
            {"contract_ids": ",".join(queries._ids(contract_ids))}
            if queries._ids(contract_ids)
            else filters.model_dump()
        ),
        headers=RENTAL_EXPORT_HEADERS,
        rows=rows,
    )
