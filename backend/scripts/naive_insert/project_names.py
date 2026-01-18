"""Project English name extraction from Units/Buildings CSVs."""

import logging
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)


def build_project_name_cache(data_dir: Path) -> dict[int, str]:
    """Build project_id → project_name_en mapping from Units and Buildings CSVs."""
    cache: dict[int, str] = {}

    for csv_name in ["Units.csv", "Buildings.csv"]:
        csv_path = data_dir / csv_name
        if not csv_path.exists():
            continue
        try:
            df = (
                pl.scan_csv(csv_path, infer_schema_length=0)
                .select([
                    pl.col("project_id").cast(pl.Int64),
                    pl.col("project_name_en").cast(pl.Utf8),
                ])
                .filter(
                    pl.col("project_name_en").is_not_null()
                    & (pl.col("project_name_en").str.strip_chars() != "")
                )
                .unique(subset=["project_id"])
                .collect()
            )

            added = 0
            for row in df.iter_rows():
                if row[0] not in cache:
                    cache[row[0]] = row[1]
                    added += 1
            logger.info(f"Loaded {added} project names from {csv_name}")
        except Exception as e:
            logger.warning(f"Could not read {csv_name}: {e}")

    return cache


def enhance_projects_df(df: pl.DataFrame, cache: dict[int, str]) -> pl.DataFrame:
    """Add project_name_en column to projects DataFrame."""
    if df.is_empty() or "project_id" not in df.columns:
        return df

    # Get project_id as integers for lookup
    try:
        project_ids = df["project_id"].cast(pl.Int64).to_list()
    except Exception:
        project_ids = df["project_id"].to_list()

    names = [cache.get(int(pid)) if pid is not None else None for pid in project_ids]
    return df.with_columns(pl.Series("project_name_en", names))
