"""Type transformers using Polars - handles schema enforcement at read time."""

from typing import Any
import polars as pl


def get_model_schema(model_class: Any) -> dict[str, pl.DataType]:
    """Extract column types from SQLModel class as Polars schema."""
    if not hasattr(model_class, "__table__"):
        return {}

    schema = {}
    for col in model_class.__table__.columns:
        t = type(col.type).__name__.lower()
        if t in ("integer", "biginteger", "smallinteger"):
            schema[col.name] = pl.Int64
        elif t in ("numeric", "decimal", "float", "real"):
            schema[col.name] = pl.Float64
        elif t == "date":
            schema[col.name] = pl.Date
        elif t in ("datetime", "timestamp"):
            schema[col.name] = pl.Datetime
        elif t == "boolean":
            schema[col.name] = pl.Boolean
        else:
            schema[col.name] = pl.Utf8
    return schema


def infer_type(col: str) -> type[pl.DataType]:
    """Infer column type from naming conventions."""
    c = col.lower()
    if c.endswith("_id") or c == "id":
        return pl.Int64
    if (
        c.startswith("no_of_")
        or c.startswith("num_")
        or c
        in (
            "floors",
            "rooms",
            "car_parks",
            "shops",
            "flats",
            "offices",
            "swimming_pools",
            "elevators",
            "bld_levels",
            "percent_completed",
        )
    ):
        return pl.Int64
    if any(w in c for w in ("area", "worth", "price", "value", "amount", "rent")):
        return pl.Float64
    if c.endswith("_date") or c in ("instance_date",):
        return pl.Date
    if c.startswith("is_") or c.startswith("has_"):
        return pl.Boolean
    return pl.Utf8


def transform_dataframe(df: pl.DataFrame, model_class: Any) -> pl.DataFrame:
    """Transform DataFrame columns to match model types."""
    if df.is_empty():
        return df

    model_schema = get_model_schema(model_class)
    exprs = []

    for col in df.columns:
        target_type = model_schema.get(col, infer_type(col))

        if target_type == pl.Int64:
            # Parse integers, handle nulls properly
            exprs.append(
                pl.col(col)
                .str.strip_chars()
                .replace("", None)
                .cast(pl.Float64, strict=False)
                .cast(pl.Int64, strict=False)
                .alias(col)
            )
        elif target_type == pl.Float64:
            exprs.append(
                pl.col(col)
                .str.strip_chars()
                .replace("", None)
                .cast(pl.Float64, strict=False)
                .alias(col)
            )
        elif target_type == pl.Date:
            # Parse dates - try common formats with coalesce fallback
            cleaned = pl.col(col).str.strip_chars().replace("", None)
            exprs.append(
                pl.coalesce(
                    cleaned.str.to_date(
                        format="%d-%m-%Y", strict=False
                    ),  # DD-MM-YYYY (our CSVs)
                    cleaned.str.to_date(format="%d/%m/%Y", strict=False),  # DD/MM/YYYY
                    cleaned.str.to_date(format="%Y-%m-%d", strict=False),  # ISO format
                ).alias(col)
            )
        elif target_type == pl.Boolean:
            exprs.append(
                pl.col(col)
                .str.to_lowercase()
                .replace({"true": "1", "yes": "1", "false": "0", "no": "0", "": None})
                .cast(pl.Int8, strict=False)
                .cast(pl.Boolean, strict=False)
                .alias(col)
            )
        else:
            # String - clean and convert "null" string to actual null
            exprs.append(
                pl.col(col)
                .str.strip_chars()
                .replace({"": None, "null": None, "NULL": None})
                .alias(col)
            )

    return df.with_columns(exprs)
