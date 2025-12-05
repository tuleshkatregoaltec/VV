"""CSV diff engine using Polars for fast incremental updates."""

import hashlib
import logging
from pathlib import Path
from typing import Iterator

import polars as pl

from .config import TableConfig

logger = logging.getLogger(__name__)
DEFAULT_CHUNK_SIZE = 50_000


def compute_file_hash(filepath: Path) -> str:
    """Compute SHA256 hash of a file for identical-file detection."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def normalize_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Standardize column names: lowercase, underscores, stripped."""
    return df.rename(
        {c: c.strip().strip('"').lower().replace(" ", "_") for c in df.columns}
    )


def apply_column_renames(df: pl.DataFrame, renames: dict[str, str]) -> pl.DataFrame:
    """Apply column renames from config."""
    existing = {k: v for k, v in renames.items() if k in df.columns}
    return df.rename(existing) if existing else df


def get_pk_file_path(csv_path: Path) -> Path:
    """Get path for PK cache file corresponding to a CSV."""
    return csv_path.with_suffix(".pks")


def compute_row_hash(df: pl.DataFrame, exclude_cols: list[str]) -> pl.Series:
    """Compute deterministic negative int64 hashes for rows."""
    cols = sorted([c for c in df.columns if c not in exclude_cols])
    if not cols:
        return pl.Series(range(-1, -len(df) - 1, -1))

    # Polars native hash - much faster than pandas
    hash_expr = pl.concat_str(
        [pl.col(c).fill_null("").cast(pl.Utf8) for c in cols]
    ).hash()
    hashes = df.select(hash_expr.alias("h"))["h"]
    # Convert to negative int64 for synthetic PKs
    # Modulo first to avoid overflow when casting UInt64 -> Int64
    return -(hashes % 2147483647).cast(pl.Int64) - 1


def is_null_pk(series: pl.Series) -> pl.Series:
    """Check for null/empty PK values."""
    is_na = series.is_null()
    str_lower = series.cast(pl.Utf8).str.to_lowercase().str.strip_chars()
    is_null_str = str_lower.is_in(["", "null", "none", "nan", "na", "<na>"])
    return is_na | is_null_str


def extract_pk_keys(
    df: pl.DataFrame, pk_cols: list[str], fill_null: bool = True
) -> pl.Series:
    """Extract composite PK as string, optionally filling nulls with hashes."""
    if len(pk_cols) == 1:
        pk_series = df[pk_cols[0]].cast(pl.Utf8)
    else:
        # Evaluate concat_str expression to get a Series
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

    # Compute hashes for null rows and build replacement series
    null_df = df.filter(null_mask)
    synthetic = compute_row_hash(null_df, pk_cols).cast(pl.Utf8)

    # Use when/then/otherwise pattern for replacement
    result_df = pl.DataFrame({"_pk": pk_series, "_null": null_mask})

    # Create a mapping of null positions to synthetic values
    null_indices = null_mask.arg_true().to_list()
    synthetic_list = synthetic.to_list()

    # Build new series with replacements
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

        # Compute hash for ALL rows, then only apply where null
        # Using all non-PK columns for the hash
        hash_cols = sorted([c for c in result.columns if c not in pk_cols_lower])
        if not hash_cols:
            hash_cols = list(result.columns)

        # Build hash expression inline for the full dataframe
        hash_expr = pl.concat_str(
            [pl.col(c).fill_null("").cast(pl.Utf8) for c in hash_cols]
        ).hash()

        # Create synthetic PKs: -(hash % 2147483647) - 1
        synthetic_expr = -(hash_expr % 2147483647).cast(pl.Int64) - 1

        # Apply only where null
        result = result.with_columns(
            pl.when(is_null_pk(pl.col(pk_col)))
            .then(synthetic_expr)
            .otherwise(pl.col(pk_col))
            .alias(pk_col)
        )
    return result


def drop_empty_rows(df: pl.DataFrame, pk_cols: list[str]) -> pl.DataFrame:
    """Drop rows where all non-PK fields are null/empty.
    
    In a data warehouse we preserve rows with partial data, but rows that have
    no meaningful data (only PKs, everything else null) should be dropped.
    """
    if df.is_empty():
        return df
    
    pk_cols_lower = [c.lower().replace(" ", "_") for c in pk_cols]
    non_pk_cols = [c for c in df.columns if c not in pk_cols_lower]
    
    if not non_pk_cols:
        return df
    
    # Build expression: at least one non-PK column is not null/empty
    has_data_expr = pl.lit(False)
    for col in non_pk_cols:
        col_type = df[col].dtype
        if col_type == pl.Utf8:
            # For strings: not null AND not empty string
            has_data_expr = has_data_expr | (pl.col(col).is_not_null() & (pl.col(col) != ""))
        else:
            # For other types: just not null
            has_data_expr = has_data_expr | pl.col(col).is_not_null()
    
    return df.filter(has_data_expr)


class CSVDiffer:
    """Fast CSV differ using PK-only comparison."""

    def __init__(self, current_dir: Path, previous_dir: Path, config: TableConfig):
        self.current_dir = current_dir
        self.previous_dir = previous_dir
        self.config = config
        self.current_file = current_dir / config.csv_file
        self.previous_file = previous_dir / config.csv_file
        self.pk_file = get_pk_file_path(self.previous_file)
        self.current_hash: str | None = None
        self.previous_hash: str | None = None
        self.is_initial_load = False
        self.files_identical = False

    def check_files(self) -> tuple[bool, str]:
        """Check file availability and determine load mode."""
        if not self.current_file.exists():
            return False, f"Current file not found: {self.current_file}"

        self.current_hash = compute_file_hash(self.current_file)

        if self.pk_file.exists():
            return True, f"Incremental mode (PK file: {self.pk_file.name})"

        if self.previous_file.exists():
            self.previous_hash = compute_file_hash(self.previous_file)
            if self.current_hash == self.previous_hash:
                self.files_identical = True
                return True, "Files identical (skipping)"
            return True, "Building PK index from previous CSV"

        self.is_initial_load = True
        return True, "Initial load (no previous data)"

    def get_diff_rows(
        self, chunk_size: int | None = None
    ) -> Iterator[tuple[pl.DataFrame, pl.DataFrame, int, int]]:
        """Yield (new_rows, existing_rows, scanned_count, chunk_num)."""
        chunk_size = chunk_size or self.config.batch_size

        if self.is_initial_load:
            yield from self._yield_all_as_new(chunk_size)
        elif self.pk_file.exists():
            yield from self._yield_diff_with_pk_file(chunk_size)
        else:
            yield from self._yield_diff_build_pk_file(chunk_size)

    def _yield_all_as_new(
        self, chunk_size: int
    ) -> Iterator[tuple[pl.DataFrame, pl.DataFrame, int, int]]:
        """Initial load: all rows are new."""
        total, chunk_num = 0, 0

        # Read full file lazily and process in row-based chunks
        full_df = pl.scan_csv(self.current_file, infer_schema_length=0).collect()
        full_df = apply_column_renames(
            normalize_columns(full_df), self.config.column_renames
        )
        n_rows = len(full_df)

        for start in range(0, n_rows, chunk_size):
            chunk_num += 1
            chunk = full_df.slice(start, chunk_size)
            total += len(chunk)
            yield chunk, pl.DataFrame(schema=chunk.schema), total, chunk_num

    def _yield_diff_with_pk_file(
        self, chunk_size: int
    ) -> Iterator[tuple[pl.DataFrame, pl.DataFrame, int, int]]:
        """Incremental mode using cached PK file."""
        pk_cols = [c.lower().replace(" ", "_") for c in self.config.primary_keys]

        with open(self.pk_file) as f:
            previous_pks = {line.strip() for line in f if line.strip()}

        yield from self._compare_against_pks(chunk_size, pk_cols, previous_pks)

    def _yield_diff_build_pk_file(
        self, chunk_size: int
    ) -> Iterator[tuple[pl.DataFrame, pl.DataFrame, int, int]]:
        """Build PK set from previous CSV, then compare."""
        pk_cols = [c.lower().replace(" ", "_") for c in self.config.primary_keys]
        previous_pks: set[str] = set()

        # Read previous file and build PK set
        prev_df = pl.scan_csv(self.previous_file, infer_schema_length=0).collect()
        prev_df = apply_column_renames(
            normalize_columns(prev_df), self.config.column_renames
        )
        previous_pks.update(extract_pk_keys(prev_df, pk_cols).to_list())
        del prev_df

        yield from self._compare_against_pks(chunk_size, pk_cols, previous_pks)

    def _compare_against_pks(
        self, chunk_size: int, pk_cols: list[str], previous_pks: set[str]
    ) -> Iterator[tuple[pl.DataFrame, pl.DataFrame, int, int]]:
        """Stream current CSV and compare PKs."""
        total, chunk_num = 0, 0

        # Read full file and process in chunks
        full_df = pl.scan_csv(self.current_file, infer_schema_length=0).collect()
        full_df = apply_column_renames(
            normalize_columns(full_df), self.config.column_renames
        )
        n_rows = len(full_df)

        for start in range(0, n_rows, chunk_size):
            chunk_num += 1
            chunk = full_df.slice(start, chunk_size)
            total += len(chunk)

            pk_keys = extract_pk_keys(chunk, pk_cols)
            is_new = ~pk_keys.is_in(list(previous_pks))

            yield chunk.filter(is_new), chunk.filter(~is_new), total, chunk_num

    def save_pk_file(self) -> None:
        """Save PK cache file for next incremental run."""
        pk_cols = [c.lower().replace(" ", "_") for c in self.config.primary_keys]
        output = get_pk_file_path(self.current_file)

        # Read full file and extract PKs
        df = pl.scan_csv(self.current_file, infer_schema_length=0).collect()
        df = apply_column_renames(normalize_columns(df), self.config.column_renames)

        with open(output, "w") as f:
            f.writelines(f"{pk}\n" for pk in extract_pk_keys(df, pk_cols).to_list())


class LookupExtractor:
    """Extracts lookup values from multiple source files."""

    def __init__(self, current_dir: Path, previous_dir: Path, config: TableConfig):
        self.current_dir = current_dir
        self.previous_dir = previous_dir
        self.config = config

    def extract_from_dir(self, directory: Path) -> pl.DataFrame:
        """Extract unique lookup values from source files."""
        all_dfs = []
        source_files = self.config.extract_from_files or [self.config.csv_file]
        extract_cols = self.config.extract_columns or []
        pk_col = self.config.primary_keys[0]

        if not extract_cols:
            return pl.DataFrame()

        for filename in source_files:
            filepath = directory / filename
            if not filepath.exists():
                continue

            # Read only needed columns using lazy scan
            try:
                df = pl.scan_csv(filepath, infer_schema_length=0).collect()
                df = normalize_columns(df)
                available = [c for c in extract_cols if c in df.columns]
                if available:
                    all_dfs.append(df.select(available).unique())
            except Exception:
                continue

        if not all_dfs:
            return pl.DataFrame()

        combined = pl.concat(all_dfs).unique(subset=[pk_col])
        combined = apply_column_renames(combined, self.config.column_renames)
        pk_renamed = self.config.column_renames.get(pk_col, pk_col)
        return combined.drop_nulls(subset=[pk_renamed])

    def get_diff(self) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Get new and updated lookup values."""
        current_df = self.extract_from_dir(self.current_dir)
        if current_df.is_empty():
            return pl.DataFrame(), pl.DataFrame()

        pk_cols = [
            self.config.column_renames.get(pk, pk) for pk in self.config.primary_keys
        ]
        has_previous = any(
            (self.previous_dir / f).exists()
            for f in (self.config.extract_from_files or [self.config.csv_file])
        )

        if not has_previous:
            return current_df, pl.DataFrame(schema=current_df.schema)

        previous_df = self.extract_from_dir(self.previous_dir)
        if previous_df.is_empty():
            return current_df, pl.DataFrame(schema=current_df.schema)

        # Find new rows using anti-join
        new_df = current_df.join(previous_df.select(pk_cols), on=pk_cols, how="anti")

        # Find updated rows
        data_cols = [c for c in current_df.columns if c not in pk_cols]
        if not data_cols:
            return new_df, pl.DataFrame(schema=current_df.schema)

        # Join and compare
        joined = current_df.join(previous_df, on=pk_cols, how="inner", suffix="_prev")

        # Check for changes in any data column
        change_expr = pl.lit(False)
        for col in data_cols:
            prev_col = f"{col}_prev"
            if prev_col in joined.columns:
                change_expr = change_expr | (
                    pl.col(col).fill_null("") != pl.col(prev_col).fill_null("")
                )

        changed_pks = joined.filter(change_expr).select(pk_cols)
        updated_df = (
            current_df.join(changed_pks, on=pk_cols, how="inner")
            if len(changed_pks) > 0
            else pl.DataFrame(schema=current_df.schema)
        )

        return new_df, updated_df
