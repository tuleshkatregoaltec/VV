"""ETL Pipeline - COPY-based bulk loader with PK-only diff comparison."""

from .runner import run_etl

__all__ = ["run_etl"]
