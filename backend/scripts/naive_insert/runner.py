"""Run-based ETL pipeline with S3 integration."""

import argparse
import gc
import json
import logging
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import polars as pl
from dotenv import load_dotenv

# Load .env from backend directory (two levels up from scripts/naive_insert/)
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from app.db.models import *  # noqa: F401, F403 - Import all models to register metadata

from .assembler import assemble_chunks, cleanup_session
from .config import PROCESSING_ORDER, TableConfig, get_table_configs
from .differ import (
    apply_column_renames,
    drop_empty_rows,
    extract_pk_keys,
    fill_null_pks_with_hash,
    normalize_columns,
)
from .manifest import generate_run_id, get_previous_run_id, save_manifest
from .project_names import build_project_name_cache, enhance_projects_df
from .s3_client import S3Client, get_s3_client
from .transformers import transform_dataframe
from .upserter import CopyUpserter, get_connection


def setup_logging(log_dir: Path | None = None) -> logging.Logger:
    """Configure file and console logging."""
    if log_dir is None:
        log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("naive_insert")
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


def discover_new_sessions(
    s3: S3Client, since_timestamp: str | None = None
) -> list[str]:
    """Discover new upload sessions in S3.

    Args:
        s3: S3 client instance
        since_timestamp: ISO timestamp - only return sessions uploaded after this time

    Returns:
        List of session IDs with new uploads
    """
    logger = logging.getLogger("naive_insert")
    logger.info("\n🔍 Discovering new upload sessions...")

    # List all session directories
    prefix = "etl/uploads/"
    all_keys = s3.list_objects(prefix)

    # Extract unique session IDs
    session_ids = set()
    for key in all_keys:
        if key.endswith("/metadata.json"):
            session_id = key.split("/")[2]  # etl/uploads/{session_id}/metadata.json
            session_ids.add(session_id)

    if not session_ids:
        logger.info("  No upload sessions found")
        return []

    logger.info(f"  Found {len(session_ids)} total sessions")

    # Filter by timestamp if provided
    if since_timestamp:
        from datetime import datetime

        cutoff = datetime.fromisoformat(since_timestamp.replace("Z", "+00:00"))
        new_sessions = []

        for session_id in session_ids:
            try:
                metadata_key = f"etl/uploads/{session_id}/metadata.json"
                metadata = json.loads(s3.download_bytes(metadata_key).decode("utf-8"))
                uploaded_at = datetime.fromisoformat(
                    metadata["uploaded_at"].replace("Z", "+00:00")
                )

                if uploaded_at > cutoff:
                    new_sessions.append(session_id)
                    logger.info(
                        f"  ✓ New: {session_id} (uploaded {metadata['uploaded_at']})"
                    )
                else:
                    logger.debug(f"  ⊘ Skip: {session_id} (already processed)")
            except Exception as e:
                logger.warning(f"  ⚠ Could not read metadata for {session_id}: {e}")
                continue

        logger.info(f"  Found {len(new_sessions)} new sessions since {since_timestamp}")
        return new_sessions
    else:
        logger.info(f"  Using all {len(session_ids)} sessions (no timestamp filter)")
        return list(session_ids)


def load_previous_pks(
    s3: S3Client, prev_run_id: str | None, table_name: str
) -> set[str]:
    """Load PK cache from previous run."""
    if prev_run_id is None:
        return set()

    pk_key = f"etl/runs/{prev_run_id}/pks/{table_name}.pks"
    try:
        data = s3.download_bytes(pk_key).decode("utf-8")
        return {line.strip() for line in data.split("\n") if line.strip()}
    except Exception:
        return set()


def save_current_pks(s3: S3Client, run_id: str, table_name: str, pks: set[str]) -> None:
    """Save PK cache for current run."""
    pk_key = f"etl/runs/{run_id}/pks/{table_name}.pks"
    data = "\n".join(sorted(pks)).encode("utf-8")
    s3.upload_bytes(pk_key, data)


def extract_lookup_df(data_dir: Path, config: TableConfig) -> pl.DataFrame:
    """Extract unique lookup values from source files."""
    all_dfs = []
    source_files = config.extract_from_files or [config.csv_file]
    extract_cols = config.extract_columns or []
    pk_col = config.primary_keys[0]

    if not extract_cols:
        return pl.DataFrame()

    for filename in source_files:
        filepath = data_dir / filename
        if not filepath.exists():
            continue
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
    combined = apply_column_renames(combined, config.column_renames)
    pk_renamed = config.column_renames.get(pk_col, pk_col)
    return combined.drop_nulls(subset=[pk_renamed])


def process_lookup_table(
    conn,
    config: TableConfig,
    data_dir: Path,
    prev_pks: set[str],
    logger: logging.Logger,
    dry_run: bool = False,
) -> tuple[dict, set[str]]:
    """Process a lookup table extracted from source files."""
    logger.info(f"\n{'─' * 60}\n📋 {config.name} (lookup)\n{'─' * 60}")
    start = time.time()
    stats = {"table": config.name, "inserted": 0, "updated": 0, "errors": []}

    try:
        df = extract_lookup_df(data_dir, config)
        if df.is_empty():
            logger.info("  ✓ No data found")
            return stats, set()

        pk_cols = [config.column_renames.get(pk, pk) for pk in config.primary_keys]
        current_pks = set(extract_pk_keys(df, pk_cols).to_list())

        new_mask = ~extract_pk_keys(df, pk_cols).is_in(list(prev_pks))
        new_df = df.filter(new_mask)

        logger.info(f"  Found: {len(new_df)} new, {len(df) - len(new_df)} existing")

        if new_df.is_empty():
            logger.info("  ✓ No new records")
            return stats, current_pks

        upserter = CopyUpserter(conn, config.model_class, config.primary_keys)
        new_df = drop_empty_rows(
            fill_null_pks_with_hash(
                transform_dataframe(new_df, config.model_class), config.primary_keys
            ),
            config.primary_keys,
        )

        if dry_run:
            logger.info(f"  [DRY RUN] Would insert {len(new_df)} new rows")
            stats["inserted"] = len(new_df)
        else:
            stats["inserted"] = upserter.insert_batch(new_df)

        stats["errors"] = upserter.errors
        logger.info(f"  ✓ Inserted: {stats['inserted']} ({time.time() - start:.1f}s)")
        return stats, current_pks

    except Exception as e:
        logger.error(f"  ✗ Error: {e}")
        stats["errors"].append(str(e))
        return stats, prev_pks


def process_csv_table(
    conn,
    config: TableConfig,
    data_dir: Path,
    prev_pks: set[str],
    logger: logging.Logger,
    dry_run: bool = False,
    transform_hook: Callable[[pl.DataFrame], pl.DataFrame] | None = None,
) -> tuple[dict, set[str]]:
    """Process a table from CSV file."""
    logger.info(f"\n{'─' * 60}\n📄 {config.name}\n{'─' * 60}")
    start = time.time()
    stats = {"table": config.name, "inserted": 0, "scanned": 0, "errors": []}

    csv_path = data_dir / config.csv_file
    if not csv_path.exists():
        logger.warning(f"  ✗ File not found: {csv_path}")
        return stats, prev_pks

    try:
        df = pl.scan_csv(csv_path, infer_schema_length=0).collect()
        df = apply_column_renames(normalize_columns(df), config.column_renames)
        stats["scanned"] = len(df)

        if transform_hook:
            df = transform_hook(df)

        pk_cols = [c.lower().replace(" ", "_") for c in config.primary_keys]
        current_pks = set(extract_pk_keys(df, pk_cols).to_list())

        new_mask = ~extract_pk_keys(df, pk_cols).is_in(list(prev_pks))
        new_df = df.filter(new_mask)

        logger.info(f"  Scanned: {len(df):,}, New: {len(new_df):,}")

        if new_df.is_empty():
            logger.info("  ✓ No new records")
            return stats, current_pks

        upserter = CopyUpserter(conn, config.model_class, config.primary_keys)

        # Process in batches
        batch_size = config.batch_size
        for i in range(0, len(new_df), batch_size):
            batch = new_df.slice(i, batch_size)
            batch = drop_empty_rows(
                fill_null_pks_with_hash(
                    transform_dataframe(batch, config.model_class), config.primary_keys
                ),
                config.primary_keys,
            )
            if batch.is_empty():
                continue

            if dry_run:
                stats["inserted"] += len(batch)
            else:
                stats["inserted"] += upserter.insert_batch(batch)

            del batch
            gc.collect()

        stats["errors"] = upserter.errors
        elapsed = time.time() - start
        logger.info(
            f"  ✓ Inserted: {stats['inserted']:,} from {stats['scanned']:,} ({elapsed:.1f}s, {stats['scanned'] / elapsed:,.0f} rows/s)"
        )
        return stats, current_pks

    except Exception as e:
        logger.error(f"  ✗ Error: {e}")
        import traceback

        traceback.print_exc()
        stats["errors"].append(str(e))
        return stats, prev_pks


def run_etl(
    session_ids: list[str],
    tables: list[str] | None = None,
    full_refresh: bool = False,
    dry_run: bool = False,
    local_data_dir: Path | None = None,
) -> dict:
    """Run the ETL pipeline.

    Args:
        session_ids: List of upload session IDs to process (auto-discovers if empty)
        tables: Optional list of specific tables to process
        full_refresh: If True, ignore previous PK caches and insert all rows
        dry_run: If True, simulate without writing to DB
        local_data_dir: Optional local directory to use instead of S3

    Returns:
        dict with success status, run_id, timing, and per-table statistics
    """
    logger = setup_logging()
    logger.info("=" * 70 + "\nVitevue ETL Pipeline (Run-Based)\n" + "=" * 70)

    run_id = generate_run_id()
    logger.info(f"Run ID: {run_id}")
    logger.info(f"Full refresh: {full_refresh}")
    logger.info(f"Dry run: {dry_run}")

    # Setup data directory
    if local_data_dir:
        data_dir = local_data_dir
        s3 = None
        prev_run_id = None
        logger.info(f"Using local data: {data_dir}")
    else:
        s3 = get_s3_client()
        prev_run_id = None if full_refresh else get_previous_run_id(s3)
        logger.info(f"Previous run: {prev_run_id or 'None (initial load)'}")

        # Auto-discover new sessions if none provided
        if not session_ids:
            from .manifest import load_manifest

            manifest = load_manifest(s3)
            since_timestamp = (
                manifest.updated_at if manifest and not full_refresh else None
            )
            session_ids = discover_new_sessions(s3, since_timestamp)

            if not session_ids:
                logger.info("\n✓ No new data to process")
                return {
                    "success": True,
                    "run_id": run_id,
                    "elapsed": 0,
                    "total_inserted": 0,
                    "total_updated": 0,
                    "total_errors": 0,
                    "tables": [],
                    "message": "No new upload sessions found",
                }

        logger.info(
            f"\nProcessing {len(session_ids)} session(s): {', '.join(session_ids[:5])}{f' and {len(session_ids) - 5} more...' if len(session_ids) > 5 else ''}"
        )

        # Create temp directory for assembled files
        temp_dir = Path(tempfile.mkdtemp(prefix="etl_"))
        data_dir = temp_dir / "datasets"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Assemble chunks from each session
        for session_id in session_ids:
            logger.info(f"\nAssembling from session: {session_id}")
            result = assemble_chunks(s3, session_id, data_dir)
            if not result.verified:
                logger.error(f"Hash verification failed for {result.filename}")
                return {"success": False, "error": "Hash verification failed"}

            # Upload assembled file to runs archive
            archive_key = f"etl/runs/{run_id}/datasets/{result.filename}"
            s3.upload_file(result.local_path, archive_key)
            logger.info(f"  Archived to s3://.../{run_id}/datasets/{result.filename}")

    # Build project name cache
    logger.info("\nBuilding project name cache...")
    project_name_cache = build_project_name_cache(data_dir)
    logger.info(f"  Cached {len(project_name_cache)} project names")

    # Get table configs
    all_configs = get_table_configs()
    tables_to_process = [t for t in PROCESSING_ORDER if not tables or t in tables]
    logger.info(f"\nTables: {', '.join(tables_to_process)}")

    # Connect to database
    logger.info("\nConnecting to database...")
    try:
        conn = get_connection(disable_fk=True)
        logger.info("  ✓ Connected (FK checks disabled)")
    except Exception as e:
        logger.error(f"  ✗ Connection failed: {e}")
        return {"success": False, "error": str(e)}

    # Process tables
    start = time.time()
    results = []

    try:
        for table_name in tables_to_process:
            config = all_configs.get(table_name)
            if not config:
                continue

            # Load previous PKs
            prev_pks = (
                set()
                if full_refresh
                else load_previous_pks(s3, prev_run_id, table_name)
                if s3
                else set()
            )

            # Determine transform hook for projects
            transform_hook = None
            if table_name == "projects":
                transform_hook = lambda df: enhance_projects_df(df, project_name_cache)

            # Process table
            if config.is_lookup:
                stats, current_pks = process_lookup_table(
                    conn, config, data_dir, prev_pks, logger, dry_run
                )
            else:
                stats, current_pks = process_csv_table(
                    conn, config, data_dir, prev_pks, logger, dry_run, transform_hook
                )

            results.append(stats)

            # Save current PKs to S3
            if s3 and not dry_run and current_pks:
                save_current_pks(s3, run_id, table_name, current_pks)

    finally:
        conn.close()

    # Update manifest
    if s3 and not dry_run:
        save_manifest(s3, run_id, prev_run_id)

        # Cleanup upload sessions
        for session_id in session_ids:
            cleanup_session(s3, session_id)

    # Summary
    elapsed = time.time() - start
    total_inserted = sum(r.get("inserted", 0) for r in results)
    total_updated = sum(r.get("updated", 0) for r in results)
    total_errors = sum(len(r.get("errors", [])) for r in results)

    logger.info(f"\n{'=' * 70}\nETL Complete\n{'=' * 70}")
    logger.info(f"  Run ID: {run_id}")
    logger.info(f"  Inserted: {total_inserted:,}")
    logger.info(f"  Updated: {total_updated:,}")
    logger.info(f"  Errors: {total_errors}")
    logger.info(f"  Time: {elapsed:.1f}s")

    return {
        "success": total_errors == 0,
        "run_id": run_id,
        "elapsed": elapsed,
        "total_inserted": total_inserted,
        "total_updated": total_updated,
        "total_errors": total_errors,
        "tables": results,
    }


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="ViteVue ETL Pipeline (Run-Based)",
        epilog="""
Examples:
  # Auto-discover and process new uploads from S3
  python -m scripts.naive_insert

  # Process specific session IDs
  python -m scripts.naive_insert session_abc123 session_def456

  # Process only transactions table
  python -m scripts.naive_insert -t transactions

  # Full refresh (all rows, ignore PK caches)
  python -m scripts.naive_insert --full-refresh

  # Test with local CSV files
  python -m scripts.naive_insert --local /path/to/csvs

  # Dry run (don't write to DB)
  python -m scripts.naive_insert --dry-run
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "session_ids",
        nargs="*",
        help="Upload session IDs to process (auto-discovers new sessions if omitted)",
    )
    parser.add_argument(
        "--table",
        "-t",
        action="append",
        dest="tables",
        help="Specific table(s) to process (can be used multiple times)",
    )
    parser.add_argument(
        "--full-refresh",
        "-f",
        action="store_true",
        help="Ignore previous PK caches and insert all rows",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Simulate ETL without writing to DB"
    )
    parser.add_argument(
        "--local", "-l", type=Path, help="Use local data directory instead of S3"
    )
    args = parser.parse_args()

    result = run_etl(
        session_ids=args.session_ids or [],
        tables=args.tables,
        full_refresh=args.full_refresh,
        dry_run=args.dry_run,
        local_data_dir=args.local,
    )
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
