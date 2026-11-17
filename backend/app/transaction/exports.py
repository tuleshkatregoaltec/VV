"""Excel and CSV exports of the Transactions pages.

An export holds at most MAX_TRANSACTION_EXPORT_ROWS filtered rows, newest first. When more rows
match, the file says so (a closing CSV row, the workbook's Metadata sheet) and so do the response
headers (X-Export-Truncated, X-Export-Rows, X-Export-Matching-Rows), which the page shows. Rows are
read from the warehouse in chunks and the CSV is streamed as they arrive; the workbook is written
row by row to a temporary file, so neither holds the whole export in memory.
"""

import asyncio
import csv
import tempfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from typing import Literal, Optional

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

from app.transaction import queries
from app.transaction.models import RentalFilters, SalesFilters

MAX_TRANSACTION_EXPORT_ROWS = 50_000
EXPORT_CHUNK_ROWS = 5_000
_FILE_CHUNK_BYTES = 64 * 1024

SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@")

SPREADSHEET_CONTROL_PREFIXES = ("\t", "\r", "\n")

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass(frozen=True)
class ExportFile:
    """An export ready to stream: its rows, how many matched, and its bytes in chunks."""

    media_type: str
    rows: int
    matching_rows: int
    _chunks: Callable[[], AsyncIterator[bytes]]

    @property
    def truncated(self) -> bool:
        return self.matching_rows > self.rows

    def chunks(self) -> AsyncIterator[bytes]:
        return self._chunks()

    async def content(self) -> bytes:
        return b"".join([chunk async for chunk in self.chunks()])

    def headers(self) -> dict[str, str]:
        return {
            "X-Export-Rows": str(self.rows),
            "X-Export-Matching-Rows": str(self.matching_rows),
            "X-Export-Truncated": "true" if self.truncated else "false",
        }


def truncation_notice(rows: int, matching_rows: int, noun: str) -> str:
    return (
        f"Truncated: this file holds the newest {rows:,} of {matching_rows:,} matching {noun}. "
        "Narrow the filters to export the rest."
    )


def _active_export_filters(filters: dict[str, object]) -> str:
    active_filters = [
        f"{key}={value}"
        for key, value in filters.items()
        if value is not None and value != "" and value != "All"
    ]
    return ", ".join(active_filters) if active_filters else "None"


def _bold(worksheet, value: object, **font) -> WriteOnlyCell:
    cell = WriteOnlyCell(worksheet, value=value)
    cell.font = Font(bold=True, **font)
    return cell


def _add_export_metadata(
    workbook: Workbook,
    *,
    title: str,
    generated_at: datetime,
    row_count: int,
    matching_rows: int,
    noun: str,
    filters: dict[str, object],
) -> None:
    metadata = workbook.create_sheet("Metadata")
    rows = [
        ("Publisher", "Vitevue"),
        ("Dataset", title),
        ("Generated at", generated_at.isoformat()),
        ("Rows exported", row_count),
        ("Maximum filtered rows", MAX_TRANSACTION_EXPORT_ROWS),
        ("Filters applied", _active_export_filters(filters)),
        ("Matching rows", matching_rows),
        (
            "Truncated",
            truncation_notice(row_count, matching_rows, noun)
            if matching_rows > row_count
            else "No",
        ),
    ]
    for label, value in rows:
        metadata.append([_bold(metadata, label), value])


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


def _csv_text(rows) -> str:
    text = StringIO()
    csv.writer(text).writerows(rows)
    return text.getvalue()


async def _csv_chunks(headers, row_chunks, notice: Optional[str]) -> AsyncIterator[bytes]:
    yield ("\ufeff" + _csv_text([headers])).encode("utf-8")
    async for rows in row_chunks:
        yield _csv_text(_sanitize_spreadsheet_row(row) for row in rows).encode("utf-8")
    if notice:
        yield _csv_text([[notice]]).encode("utf-8")


def _append_rows(worksheet, rows) -> None:
    for row in rows:
        worksheet.append(_sanitize_spreadsheet_row(row))


async def _workbook_chunks(
    *, title, filters, headers, row_chunks, row_count, matching_rows, noun
) -> AsyncIterator[bytes]:
    generated_at = datetime.now(UTC)
    wb = Workbook(write_only=True)
    _add_export_metadata(
        wb,
        title=title,
        generated_at=generated_at,
        row_count=row_count,
        matching_rows=matching_rows,
        noun=noun,
        filters=filters,
    )
    ws = wb.create_sheet(title)
    ws.append([_bold(ws, "Vitevue", size=14)])
    ws.append([_bold(ws, title)])
    ws.append([f"Generated at {generated_at.isoformat()}"])
    ws.append([])
    ws.append([_bold(ws, header) for header in headers])
    # openpyxl is CPU-bound (about 30 s for 50,000 rows): it runs in a worker thread so the
    # API keeps serving other requests meanwhile.
    async for rows in row_chunks:
        await asyncio.to_thread(_append_rows, ws, rows)
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as output:
        await asyncio.to_thread(wb.save, output)
        output.seek(0)
        while chunk := output.read(_FILE_CHUNK_BYTES):
            yield chunk


async def _export(
    *,
    file_format: Literal["xlsx", "csv"],
    title: str,
    noun: str,
    headers: list[str],
    filters: dict[str, object],
    matching_rows: int,
    row_chunks: Callable[[], AsyncIterator[list[dict]]],
    to_row: Callable[[dict], list[object]],
) -> ExportFile:
    row_count = min(matching_rows, MAX_TRANSACTION_EXPORT_ROWS)
    notice = (
        truncation_notice(row_count, matching_rows, noun) if matching_rows > row_count else None
    )

    async def rows():
        async for chunk in row_chunks():
            yield [to_row(row) for row in chunk]

    if file_format == "csv":
        return ExportFile(
            CSV_MEDIA_TYPE, row_count, matching_rows, lambda: _csv_chunks(headers, rows(), notice)
        )
    return ExportFile(
        XLSX_MEDIA_TYPE,
        row_count,
        matching_rows,
        lambda: _workbook_chunks(
            title=title,
            filters=filters,
            headers=headers,
            row_chunks=rows(),
            row_count=row_count,
            matching_rows=matching_rows,
            noun=noun,
        ),
    )


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


def _sale_row(row: dict) -> list[object]:
    return [
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


def _rental_row(row: dict) -> list[object]:
    return [
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


async def export_sales_transactions(
    filters: SalesFilters,
    transaction_ids: Optional[str] = None,
    file_format: Literal["xlsx", "csv"] = "xlsx",
) -> ExportFile:
    """DXBI sales as Excel or CSV: the selected rows, else up to 50,000 filtered rows."""
    ids = queries._ids(transaction_ids)
    return await _export(
        file_format=file_format,
        title="Sales Transactions",
        noun="sales",
        headers=SALES_EXPORT_HEADERS,
        filters={"transaction_ids": ",".join(ids)} if ids else filters.model_dump(),
        matching_rows=await queries.count_sales_export(filters, transaction_ids),
        row_chunks=lambda: queries.export_sales_chunks(
            filters, transaction_ids, MAX_TRANSACTION_EXPORT_ROWS, EXPORT_CHUNK_ROWS
        ),
        to_row=_sale_row,
    )


async def export_rental_contracts(
    filters: RentalFilters,
    contract_ids: Optional[str] = None,
    file_format: Literal["xlsx", "csv"] = "xlsx",
) -> ExportFile:
    """DXBI leases as Excel or CSV: the selected rows, else up to 50,000 filtered rows."""
    ids = queries._ids(contract_ids)
    return await _export(
        file_format=file_format,
        title="Rental Contracts",
        noun="leases",
        headers=RENTAL_EXPORT_HEADERS,
        filters={"contract_ids": ",".join(ids)} if ids else filters.model_dump(),
        matching_rows=await queries.count_rental_export(filters, contract_ids),
        row_chunks=lambda: queries.export_rental_chunks(
            filters, contract_ids, MAX_TRANSACTION_EXPORT_ROWS, EXPORT_CHUNK_ROWS
        ),
        to_row=_rental_row,
    )
