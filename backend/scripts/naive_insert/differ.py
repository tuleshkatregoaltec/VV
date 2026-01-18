"""CSV diffing utilities for PK-based incremental loads."""

import logging
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)


def normalize_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Standardize column names: lowercase, underscores, stripped."""
    return df.rename(
        {c: c.strip().strip('"').lower().replace(" ", "_") for c in df.columns}
    )


def apply_column_renames(df: pl.DataFrame, renames: dict[str, str]) -> pl.DataFrame:
    """Apply column renames from config."""
    existing = {k: v for k, v in renames.items() if k in df.columns}
    return df.rename(existing) if existing else df


def compute_row_hash(df: pl.DataFrame, exclude_cols: list[str]) -> pl.Series:
    """Compute deterministic negative int64 hashes for rows."""
    cols = sorted([c for c in df.columns if c not in exclude_cols])
    if not cols:
        return pl.Series(range(-1, -len(df) - 1, -1))

    hash_expr = pl.concat_str(
        [pl.col(c).fill_null("").cast(pl.Utf8) for c in cols]
    ).hash()
    hashes = df.select(hash_expr.alias("h"))["h"]
    return -(hashes % 2147483647).cast(pl.Int64) - 1


def is_null_pk(series: pl.Series) -> pl.Series:
    """Check for null/empty PK values in a Series."""
    is_na = series.is_null()
    str_lower = series.cast(pl.Utf8).str.to_lowercase().str.strip_chars()
    is_null_str = str_lower.is_in(["", "null", "none", "nan", "na", "<na>"])
    return is_na | is_null_str


def is_null_pk_expr(col: pl.Expr) -> pl.Expr:
    """Check for null/empty PK values as an expression."""
    is_na = col.is_null()
    str_lower = col.cast(pl.Utf8).str.to_lowercase().str.strip_chars()
    is_null_str = str_lower.is_in(["", "null", "none", "nan", "na", "<na>"])
    return is_na | is_null_str


def extract_pk_keys(
    df: pl.DataFrame, pk_cols: list[str], fill_null: bool = True
) -> pl.Series:
    """Extract composite PK as string, optionally filling nulls with hashes."""
    if len(pk_cols) == 1:
        pk_series = df[pk_cols[0]].cast(pl.Utf8)
    else:
        pk_series = df.select(
            pl.concat_str(
                [pl.col(c).cast(pl.Utf8) for c in pk_cols], separator="\t"
            ).alias("_pk")
        )["_pk"]

    if not fill_null:
        return pk_series

    null_mask = is_null_pk(pk_series)
    if not null_mask.any():
        return pk_series

    null_df = df.filter(null_mask)
    synthetic = compute_row_hash(null_df, pk_cols).cast(pl.Utf8)

    null_indices = null_mask.arg_true().to_list()
    synthetic_list = synthetic.to_list()

    pk_list = pk_series.to_list()
    for i, idx in enumerate(null_indices):
        pk_list[idx] = synthetic_list[i]

    return pl.Series(pk_list)


def fill_null_pks_with_hash(df: pl.DataFrame, pk_cols: list[str]) -> pl.DataFrame:
    """Fill null PKs with deterministic hash-based negative integers."""
    result = df.clone()
    pk_cols_lower = [c.lower().replace(" ", "_") for c in pk_cols]

    for pk_col in pk_cols_lower:
        if pk_col not in result.columns:
            continue

        null_mask = is_null_pk(result[pk_col])
        if not null_mask.any():
            continue

        hash_cols = sorted([c for c in result.columns if c not in pk_cols_lower])
        if not hash_cols:
            hash_cols = list(result.columns)

        hash_expr = pl.concat_str(
            [pl.col(c).fill_null("").cast(pl.Utf8) for c in hash_cols]
        ).hash()

        synthetic_expr = -(hash_expr % 2147483647).cast(pl.Int64) - 1

        result = result.with_columns(
            pl.when(is_null_pk_expr(pl.col(pk_col)))
            .then(synthetic_expr)
            .otherwise(pl.col(pk_col))
            .alias(pk_col)
        )
    return result


def drop_empty_rows(df: pl.DataFrame, pk_cols: list[str]) -> pl.DataFrame:
    """Drop rows where all non-PK fields are null/empty."""
    if df.is_empty():
        return df

    pk_cols_lower = [c.lower().replace(" ", "_") for c in pk_cols]
    non_pk_cols = [c for c in df.columns if c not in pk_cols_lower]

    if not non_pk_cols:
        return df

    has_data_expr = pl.lit(False)
    for col in non_pk_cols:
        col_type = df[col].dtype
        if col_type == pl.Utf8:
            has_data_expr = has_data_expr | (
                pl.col(col).is_not_null() & (pl.col(col) != "")
            )
        else:
            has_data_expr = has_data_expr | pl.col(col).is_not_null()

    return df.filter(has_data_expr)


def load_pk_set(filepath: Path) -> set[str]:
    """Load PK set from a .pks file."""
    if not filepath.exists():
        return set()
    with open(filepath) as f:
        return {line.strip() for line in f if line.strip()}


def save_pk_set(filepath: Path, pks: set[str]) -> None:
    """Save PK set to a .pks file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        f.writelines(f"{pk}\n" for pk in sorted(pks))
