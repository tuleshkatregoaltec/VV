"""CLI entry point for ClickHouse ETL."""

import argparse
import logging
import sys
from pathlib import Path

from .config import ClickHouseConfig
from .runner import run_etl


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="ClickHouse ETL Pipeline - Smart Diff CSV Loader"
    )

    parser.add_argument(
        "session_id",
        nargs="?",  # Make session_id optional
        help="Upload session UUID (auto-discovers most recent if omitted)",
    )

    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("/tmp/chETL"),
        help="Working directory for CSV downloads (default: /tmp/chETL)",
    )

    parser.add_argument(
        "--ch-host",
        default=None,
        help="ClickHouse host (default: from CLICKHOUSE_HOST env var)",
    )

    parser.add_argument(
        "--ch-port",
        type=int,
        default=None,
        help="ClickHouse port (default: from CLICKHOUSE_PORT env var)",
    )

    parser.add_argument(
        "--ch-user",
        default=None,
        help="ClickHouse username (default: from CLICKHOUSE_USER env var)",
    )

    parser.add_argument(
        "--ch-password",
        default=None,
        help="ClickHouse password (default: from CLICKHOUSE_PASSWORD env var)",
    )

    parser.add_argument(
        "--ch-database",
        default=None,
        help="ClickHouse database (default: from CLICKHOUSE_DB env var)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    parser.add_argument(
        "--local-csv-dir",
        type=Path,
        default=None,
        help="Local directory containing CSV files (skips S3 download)",
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    # Build ClickHouse config
    ch_config_kwargs = {}
    if args.ch_host:
        ch_config_kwargs["host"] = args.ch_host
    if args.ch_port:
        ch_config_kwargs["port"] = args.ch_port
    if args.ch_user:
        ch_config_kwargs["username"] = args.ch_user
    if args.ch_password:
        ch_config_kwargs["password"] = args.ch_password
    if args.ch_database:
        ch_config_kwargs["database"] = args.ch_database

    ch_config = ClickHouseConfig(**ch_config_kwargs)

    try:
        run_etl(
            session_id=args.session_id,
            work_dir=args.work_dir,
            ch_config=ch_config,
            local_csv_dir=args.local_csv_dir,
        )
        print("\n[SUCCESS] ETL pipeline completed successfully")
        sys.exit(0)

    except Exception as e:
        print(f"\n[FAILED] ETL pipeline failed: {e}")
        logging.exception("ETL pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
