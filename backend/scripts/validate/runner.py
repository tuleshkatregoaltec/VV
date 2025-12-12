"""Database validator - Compare row counts between database tables and CSV files."""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import polars as pl
import psycopg2
from dotenv import load_dotenv

# Load .env file from backend directory
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from backend.app.db.models import *  # noqa: F401, F403
from backend.scripts.etl.config import (
    PROCESSING_ORDER,
    get_data_paths,
    get_table_configs,
)


def setup_logging(log_dir: Path | None = None) -> logging.Logger:
    """Configure file and console logging."""
    if log_dir is None:
        log_dir = Path(__file__).parent.parent.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("validator")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fh = logging.FileHandler(
        log_dir / f"validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def get_connection_params() -> dict:
    """Parse DATABASE_URL into psycopg2 connection params."""
    url = os.environ.get("DATABASE_URL", "").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "user": parsed.username or "admin",
        "password": parsed.password or "admin",
        "dbname": parsed.path.lstrip("/") or "analytics",
    }


def get_table_row_count(conn, table_name: str) -> int:
    """Get row count from database table."""
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            return cur.fetchone()[0]
    except Exception as e:
        raise Exception(f"Failed to count rows in {table_name}: {e}")


def get_csv_row_count(csv_path: Path) -> int:
    """Get row count from CSV file (excluding header)."""
    try:
        # Use polars lazy API for fast row counting
        return pl.scan_csv(csv_path).select(pl.len()).collect().item()
    except Exception as e:
        raise Exception(f"Failed to count rows in {csv_path.name}: {e}")


def validate_tables(
    data_dir: Path | None = None,
    tables: list[str] | None = None,
) -> dict:
    """Validate database tables against CSV files."""
    logger = setup_logging()
    logger.info("=" * 70 + "\nDatabase Validation\n" + "=" * 70)

    current_dir, previous_dir, current_pks_dir, previous_pks_dir = get_data_paths(
        data_dir
    )
    logger.info(f"Data directory: {current_dir}\n")

    # Get table configurations
    all_configs = get_table_configs()
    tables_to_check = tables if tables else PROCESSING_ORDER

    # Connect to database
    logger.info("Connecting to database...")
    try:
        conn = psycopg2.connect(**get_connection_params())
        logger.info("  ✓ Connected\n")
    except Exception as e:
        logger.error(f"  ✗ Connection failed: {e}")
        return {"success": False, "error": str(e)}

    results = []
    all_match = True

    try:
        for table_name in tables_to_check:
            config = all_configs.get(table_name)
            if not config:
                logger.warning(f"⚠️  {table_name}: No configuration found")
                continue

            # Skip lookup tables that are extracted (no standalone CSV)
            if config.is_lookup:
                logger.info(f"⏭️  {table_name}: Lookup table (extracted, skipped)")
                continue

            # Find CSV file
            csv_path = current_dir / config.csv_file
            if not csv_path.exists():
                logger.warning(
                    f"⚠️  {table_name}: CSV file not found ({config.csv_file})"
                )
                results.append(
                    {
                        "table": table_name,
                        "db_count": None,
                        "csv_count": None,
                        "match": False,
                        "error": "CSV not found",
                    }
                )
                all_match = False
                continue

            # Get counts
            try:
                db_count = get_table_row_count(conn, config.model_class.__tablename__)
                csv_count = get_csv_row_count(csv_path)
                match = db_count == csv_count

                status = "✓" if match else "✗"
                diff = db_count - csv_count
                diff_str = f" (diff: {diff:+,})" if not match else ""

                logger.info(
                    f"{status}  {table_name:25} | DB: {db_count:>10,} | CSV: {csv_count:>10,}{diff_str}"
                )

                results.append(
                    {
                        "table": table_name,
                        "db_count": db_count,
                        "csv_count": csv_count,
                        "difference": diff,
                        "match": match,
                        "error": None,
                    }
                )

                if not match:
                    all_match = False

            except Exception as e:
                logger.error(f"✗  {table_name}: {e}")
                results.append(
                    {
                        "table": table_name,
                        "db_count": None,
                        "csv_count": None,
                        "match": False,
                        "error": str(e),
                    }
                )
                all_match = False

    finally:
        conn.close()

    # Summary
    logger.info(f"\n{'=' * 70}\nValidation Summary\n{'=' * 70}")

    matched = sum(1 for r in results if r["match"])
    total = len(results)

    if all_match:
        logger.info(f"✓ All tables match ({matched}/{total})")
    else:
        logger.error(f"✗ Validation failed: {matched}/{total} tables match")

        # Show mismatches
        mismatches = [r for r in results if not r["match"]]
        if mismatches:
            logger.info(f"\nMismatches:")
            for r in mismatches:
                if r["error"]:
                    logger.info(f"  • {r['table']}: {r['error']}")
                else:
                    logger.info(
                        f"  • {r['table']}: DB={r['db_count']:,}, CSV={r['csv_count']:,} (diff: {r['difference']:+,})"
                    )

    return {
        "success": all_match,
        "matched": matched,
        "total": total,
        "results": results,
    }


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate database against CSV files")
    parser.add_argument(
        "--table",
        "-t",
        action="append",
        dest="tables",
        help="Specific table(s) to validate",
    )
    parser.add_argument(
        "--data-dir",
        "-d",
        type=Path,
        help="Data directory (default: <project_root>/data)",
    )
    args = parser.parse_args()

    result = validate_tables(data_dir=args.data_dir, tables=args.tables)
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
