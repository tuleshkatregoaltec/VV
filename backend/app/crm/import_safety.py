"""Bound spreadsheet expansion before openpyxl allocates workbook structures."""

import csv
import io
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile


class ImportInputError(ValueError):
    """A problem with the uploaded file that the person can fix; its message is safe to show."""


def client_message(exc: BaseException, fallback: str) -> str:
    """The exception's own text if it is a fixable file problem, else a generic message."""
    return str(exc) if isinstance(exc, ImportInputError) else fallback


MAX_IMPORT_ROWS = 500_000
MAX_IMPORT_COLUMNS = 512
_MAX_MEMBERS = 2_048
_MAX_EXPANDED_BYTES = 256 * 1024 * 1024
_MAX_MEMBER_BYTES = 128 * 1024 * 1024
_MAX_SHARED_STRINGS_BYTES = 32 * 1024 * 1024
_MAX_EXPANSION_RATIO = 200


def validate_xlsx(data: bytes) -> None:
    """Reject excessive or ambiguous archives before any workbook decoder runs."""
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > _MAX_MEMBERS:
                raise ImportInputError("Workbook contains too many archive members")
            names: set[str] = set()
            expanded = 0
            for member in members:
                name = member.filename
                if (
                    name in names
                    or PurePosixPath(name).is_absolute()
                    or ".." in PurePosixPath(name).parts
                ):
                    raise ImportInputError("Workbook contains ambiguous archive paths")
                names.add(name)
                if member.flag_bits & 1:
                    raise ImportInputError("Encrypted workbooks are not supported")
                expanded += member.file_size
                if expanded > _MAX_EXPANDED_BYTES or member.file_size > _MAX_MEMBER_BYTES:
                    raise ImportInputError("Workbook expanded size exceeds the import limit")
                if name == "xl/sharedStrings.xml" and member.file_size > _MAX_SHARED_STRINGS_BYTES:
                    raise ImportInputError("Workbook shared strings exceed the import limit")
                if (
                    member.file_size > 1024 * 1024
                    and member.file_size > max(1, member.compress_size) * _MAX_EXPANSION_RATIO
                ):
                    raise ImportInputError("Workbook compression ratio exceeds the import limit")
            if not {"[Content_Types].xml", "xl/workbook.xml"} <= names:
                raise ImportInputError("Upload a valid XLSX workbook")
    except BadZipFile as exc:
        raise ImportInputError("Upload a valid XLSX workbook") from exc


def csv_rows(data: bytes, *, max_rows: int = MAX_IMPORT_ROWS + 15) -> list[list[str]]:
    """Bound row and column materialization, including a small header preamble."""
    rows: list[list[str]] = []
    for row in csv.reader(io.StringIO(data.decode("utf-8-sig"))):
        if len(row) > MAX_IMPORT_COLUMNS:
            raise ImportInputError(f"Import exceeds the {MAX_IMPORT_COLUMNS}-column limit")
        if len(rows) >= max_rows:
            raise ImportInputError(f"Import exceeds the {MAX_IMPORT_ROWS:,}-row limit")
        rows.append(row)
    return rows
