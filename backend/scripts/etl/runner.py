"""ETL Runner using PostgreSQL COPY for high-performance bulk inserts."""

import gc
import io
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import polars as pl
import psycopg2

from .config import PROCESSING_ORDER, TableConfig, get_data_paths, get_table_configs
from .differ import CSVDiffer, LookupExtractor, drop_empty_rows, fill_null_pks_with_hash
from .transformers import transform_dataframe


def setup_logging(log_dir: Path | None = None) -> logging.Logger:
    """Configure file and console logging."""
    if log_dir is None:
        log_dir = Path(__file__).parent.parent.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("etl")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fh = logging.FileHandler(
        log_dir / f"etl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
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


def get_connection(disable_fk: bool = True):
    """Get psycopg2 connection, optionally disabling FK checks."""
    conn = psycopg2.connect(**get_connection_params())
    conn.autocommit = False
    if disable_fk:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = 'replica'")
        conn.commit()
    return conn


class CopyUpserter:
    """High-performance upserter using COPY + temp table + ON CONFLICT."""

    def __init__(self, conn, model_class, primary_keys: list[str]):
        self.conn = conn
        self.table_name = model_class.__tablename__
        self.primary_keys = primary_keys
        self.columns = (
            [col.name for col in model_class.__table__.columns]
            if hasattr(model_class, "__table__")
            else []
        )
        self.total_inserted = 0
        self.total_updated = 0
        self.errors: list[str] = []

    def _to_buffer(self, df: pl.DataFrame, cols: list[str]) -> io.BytesIO:
        """Convert DataFrame to tab-separated CSV buffer."""
        buf = io.BytesIO()
        df.select(cols).write_csv(
            buf, include_header=False, separator="\t", null_value="\\N"
        )
        buf.seek(0)
        return buf

    def insert_batch(self, df: pl.DataFrame) -> int:
        """Insert batch via COPY to temp table, then INSERT with ON CONFLICT DO NOTHING."""
        if df.is_empty():
            return 0

        cols = [c for c in self.columns if c in df.columns]
        col_list, pk_list = ", ".join(cols), ", ".join(self.primary_keys)
        temp = f"_temp_{self.table_name}"

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    f"CREATE TEMP TABLE IF NOT EXISTS {temp} (LIKE {self.table_name} INCLUDING DEFAULTS) ON COMMIT DELETE ROWS"
                )
                cur.copy_expert(
                    f"COPY {temp} ({col_list}) FROM STDIN WITH (FORMAT CSV, DELIMITER E'\\t', NULL '\\N')",
                    self._to_buffer(df, cols),
                )
                cur.execute(
                    f"INSERT INTO {self.table_name} ({col_list}) SELECT {col_list} FROM {temp} ON CONFLICT ({pk_list}) DO NOTHING"
                )
                inserted = cur.rowcount
            self.conn.commit()
            self.total_inserted += inserted
            return inserted
        except Exception as e:
            self.conn.rollback()
            self.errors.append(f"COPY error: {str(e)[:200]}")
            return 0

    def upsert_batch(self, df: pl.DataFrame) -> int:
        """Upsert batch via COPY to temp table, then INSERT with ON CONFLICT DO UPDATE."""
        if df.is_empty():
            return 0

        cols = [c for c in self.columns if c in df.columns]
        col_list, pk_list = ", ".join(cols), ", ".join(self.primary_keys)
        update_cols = [c for c in cols if c not in self.primary_keys]
        update_clause = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])
        temp = f"_temp_{self.table_name}"

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    f"CREATE TEMP TABLE IF NOT EXISTS {temp} (LIKE {self.table_name} INCLUDING DEFAULTS) ON COMMIT DELETE ROWS"
                )
                cur.copy_expert(
                    f"COPY {temp} ({col_list}) FROM STDIN WITH (FORMAT CSV, DELIMITER E'\\t', NULL '\\N')",
                    self._to_buffer(df, cols),
                )
                if update_clause:
                    cur.execute(
                        f"INSERT INTO {self.table_name} ({col_list}) SELECT {col_list} FROM {temp} ON CONFLICT ({pk_list}) DO UPDATE SET {update_clause}"
                    )
                else:
                    cur.execute(
                        f"INSERT INTO {self.table_name} ({col_list}) SELECT {col_list} FROM {temp} ON CONFLICT ({pk_list}) DO NOTHING"
                    )
                updated = cur.rowcount
            self.conn.commit()
            self.total_updated += updated
            return updated
        except Exception as e:
            self.conn.rollback()
            self.errors.append(f"Upsert error: {str(e)[:200]}")
            return 0


def process_lookup_table(
    conn,
    config: TableConfig,
    current_dir: Path,
    previous_dir: Path,
    logger,
    full_refresh: bool = False,
) -> dict:
    """Process a lookup table extracted from source files."""
    logger.info(f"\n{'─' * 60}\n📋 {config.name} (lookup)\n{'─' * 60}")
    start, stats = (
        time.time(),
        {"table": config.name, "inserted": 0, "updated": 0, "errors": []},
    )

    try:
        # Use nonexistent path for full refresh to treat all as new
        prev_dir = Path("/nonexistent") if full_refresh else previous_dir
        extractor = LookupExtractor(current_dir, prev_dir, config)
        new_df, updated_df = extractor.get_diff()
        logger.info(f"  Found: {len(new_df)} new, {len(updated_df)} updated")

        if new_df.is_empty() and updated_df.is_empty():
            logger.info("  ✓ No changes")
            return stats

        upserter = CopyUpserter(conn, config.model_class, config.primary_keys)

        if not new_df.is_empty():
            new_df = drop_empty_rows(
                fill_null_pks_with_hash(
                    transform_dataframe(new_df, config.model_class), config.primary_keys
                ),
                config.primary_keys,
            )
            stats["inserted"] = upserter.insert_batch(new_df)

        if not updated_df.is_empty():
            updated_df = transform_dataframe(updated_df, config.model_class)
            stats["updated"] = upserter.upsert_batch(updated_df)

        stats["errors"] = upserter.errors
        logger.info(
            f"  ✓ Inserted: {stats['inserted']}, Updated: {stats['updated']} ({time.time() - start:.1f}s)"
        )
    except Exception as e:
        logger.error(f"  ✗ Error: {e}")
        stats["errors"].append(str(e))

    return stats


def process_csv_table(
    conn,
    config: TableConfig,
    current_dir: Path,
    previous_dir: Path,
    logger,
    full_refresh: bool = False,
) -> dict:
    """Process a table from CSV file."""
    logger.info(f"\n{'─' * 60}\n📄 {config.name}\n{'─' * 60}")
    start, stats = (
        time.time(),
        {"table": config.name, "inserted": 0, "scanned": 0, "errors": []},
    )

    try:
        differ = CSVDiffer(
            current_dir, Path("/nonexistent") if full_refresh else previous_dir, config
        )
        if full_refresh:
            differ.is_initial_load = True

        can_proceed, message = differ.check_files()
        if not can_proceed:
            logger.error(f"  ✗ {message}")
            stats["errors"].append(message)
            return stats

        logger.info(f"  {message}")
        if differ.files_identical:
            logger.info("  ✓ Files identical, skipping")
            return stats

        upserter = CopyUpserter(conn, config.model_class, config.primary_keys)

        for new_df, existing_df, total_scanned, chunk_num in differ.get_diff_rows():
            stats["scanned"] = total_scanned
            if new_df.is_empty():
                continue

            new_df = drop_empty_rows(
                fill_null_pks_with_hash(
                    transform_dataframe(new_df, config.model_class), config.primary_keys
                ),
                config.primary_keys,
            )
            if new_df.is_empty():
                continue

            inserted = upserter.insert_batch(new_df)
            stats["inserted"] += inserted

            logger.info(
                f"  Batch {chunk_num}: {total_scanned:,} scanned, {len(new_df)} new → {inserted} inserted"
            )
            del new_df, existing_df
            gc.collect()

        differ.save_pk_file()
        stats["errors"] = upserter.errors
        elapsed = time.time() - start
        logger.info(
            f"  ✓ Total: {stats['inserted']:,} inserted from {stats['scanned']:,} rows ({elapsed:.1f}s, {stats['scanned'] / elapsed:,.0f} rows/s)"
        )
    except Exception as e:
        logger.error(f"  ✗ Error: {e}")
        stats["errors"].append(str(e))
        import traceback

        traceback.print_exc()

    return stats


def run_etl(
    tables: list[str] | None = None,
    full_refresh: bool = False,
    data_dir: Path | None = None,
) -> dict:
    """Run the ETL pipeline."""
    logger = setup_logging()
    logger.info("=" * 70 + "\nViteVue ETL Pipeline\n" + "=" * 70)

    current_dir, previous_dir = get_data_paths(data_dir)
    if not current_dir.exists():
        logger.error(f"Data directory not found: {current_dir}")
        return {"success": False, "error": "Data directory not found"}

    logger.info(
        f"Current:  {current_dir}\nPrevious: {previous_dir}\nFull refresh: {full_refresh}"
    )

    all_configs = get_table_configs()
    tables_to_process = [t for t in PROCESSING_ORDER if not tables or t in tables]
    logger.info(f"Tables: {', '.join(tables_to_process)}")

    logger.info("\nConnecting to database...")
    try:
        conn = get_connection(disable_fk=True)
        logger.info("  ✓ Connected (FK checks disabled)")
    except Exception as e:
        logger.error(f"  ✗ Connection failed: {e}")
        return {"success": False, "error": str(e)}

    start, results = time.time(), []
    try:
        for table_name in tables_to_process:
            config = all_configs.get(table_name)
            if not config:
                continue
            if config.is_lookup:
                results.append(
                    process_lookup_table(
                        conn, config, current_dir, previous_dir, logger, full_refresh
                    )
                )
            else:
                results.append(
                    process_csv_table(
                        conn, config, current_dir, previous_dir, logger, full_refresh
                    )
                )
    finally:
        conn.close()

    elapsed = time.time() - start
    total_inserted = sum(r.get("inserted", 0) for r in results)
    total_errors = sum(len(r.get("errors", [])) for r in results)

    logger.info(f"\n{'=' * 70}\nETL Complete\n{'=' * 70}")
    logger.info(
        f"  Inserted: {total_inserted:,}\n  Errors: {total_errors}\n  Time: {elapsed:.1f}s"
    )

    return {
        "success": total_errors == 0,
        "elapsed": elapsed,
        "total_inserted": total_inserted,
        "total_errors": total_errors,
        "tables": results,
    }


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="ViteVue ETL Pipeline")
    parser.add_argument(
        "--table", "-t", action="append", dest="tables", help="Specific table(s)"
    )
    parser.add_argument(
        "--full-refresh", "-f", action="store_true", help="Ignore previous data"
    )
    parser.add_argument("--data-dir", "-d", type=Path, help="Data directory")
    args = parser.parse_args()

    result = run_etl(
        tables=args.tables, full_refresh=args.full_refresh, data_dir=args.data_dir
    )
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
