from typing import Any
from decimal import Decimal
from datetime import date
from pathlib import Path
import logging

import pandas as pd

logger = logging.getLogger(__name__)


def clean_value(val: Any) -> str | None:
    """Convert pandas Null/NaN to Python None and clean strings"""
    if pd.isna(val):
        return None
    if isinstance(val, str):
        val = val.strip()
        return val if val else None
    return val


def parse_date(val: Any) -> date | None:
    """Parse date string to date object | None"""
    val = clean_value(val)
    if val is None:
        return None
    try:
        return pd.to_datetime(val, dayfirst=True).date()
    except:
        return None


def parse_bool(val: Any) -> bool | None:
    """Parse boolean value | None"""
    if pd.isna(val):
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    return None


def parse_decimal(val: Any) -> Decimal | None:
    """Parse decimal value | None"""
    val = clean_value(val)
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except:
        return None


def parse_int(val: Any) -> int | None:
    """Parse integer | None"""
    if pd.isna(val):
        return None
    try:
        return int(float(val))
    except:
        return None


def parse_str_from_numeric(val: Any) -> str | None:
    """Convert numeric field to string (for IDs stored as strings) | None"""
    val = clean_value(val)
    if val is None:
        return None
    try:
        return str(int(float(val)))
    except:
        return str(val) if val else None


def rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize column names from CSV"""
    df.columns = df.columns.str.strip().str.strip('"').str.lower().str.replace(" ", "_")
    return df


def extract_lookup_from_files(
    data_dir: Path, files: list[str], columns: list[str], id_column: str
) -> dict[int, tuple]:
    """Extract unique lookup values from multiple CSV files"""
    lookup_dict: dict[int, tuple] = {}
    for file in files:
        logger.info(f"  Scanning {file}...")
        df = pd.read_csv(data_dir / file, usecols=columns, low_memory=False)
        df = rename_columns(df)

        unique_rows = df[columns].drop_duplicates()

        for _, row in unique_rows.iterrows():
            row_id = parse_int(row[id_column])
            if row_id and row_id not in lookup_dict:
                values = tuple(
                    clean_value(row[col]) for col in columns if col != id_column
                )
                lookup_dict[row_id] = values

    return lookup_dict
