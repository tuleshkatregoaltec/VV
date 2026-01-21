"""ETL pipeline orchestration."""

import csv
import logging
import uuid
from pathlib import Path
from typing import Dict, Any
import clickhouse_connect

from .config import (
    ClickHouseConfig,
    TABLES,
    TABLE_ORDER,
)
from .s3 import S3Downloader
from .differ import (
    fetch_current_state,
    stream_csv_and_diff,
    detect_deletions,
)
from .transformer import (
    transform_transactions_row,
    transform_rent_contracts_row,
    transform_projects_row,
    transform_buildings_row,
    transform_units_row,
    transform_land_registry_row,
    transform_developers_row,
    transform_areas_row,
)
from .loader import ClickHouseLoader

logger = logging.getLogger(__name__)


class ETLRunner:
    """Main ETL pipeline orchestrator."""

    def __init__(
        self,
        ch_config: ClickHouseConfig,
        session_id: str,
        work_dir: Path,
        local_csv_dir: Path | None = None,
    ):
        self.session_id = session_id
        self.work_dir = work_dir
        self.run_id = str(uuid.uuid4())
        self.local_csv_dir = local_csv_dir

        # Initialize ClickHouse client
        self.ch_client = clickhouse_connect.get_client(
            host=ch_config.host,
            port=ch_config.port,
            username=ch_config.username,
            password=ch_config.password,
            database=ch_config.database,
        )

        self.s3_downloader = S3Downloader() if not local_csv_dir else None
        self.loader = ClickHouseLoader(self.ch_client)

        # Project name cache (built from Units/Buildings)
        self.project_name_cache: Dict[str, str] = {}

    def get_csv_file(self, csv_filename: str) -> Path:
        """
        Get CSV file path, either from local directory or S3 download.

        Args:
            csv_filename: Name of CSV file (e.g., "Transactions.csv")

        Returns:
            Path to CSV file
        """
        if self.local_csv_dir:
            # Local mode - read from specified directory
            csv_path = self.local_csv_dir / csv_filename
            if not csv_path.exists():
                raise FileNotFoundError(f"CSV file not found: {csv_path}")
            logger.info(f"Using local CSV: {csv_path}")
            return csv_path
        else:
            # S3 mode - download and assemble
            return self.s3_downloader.download_csv(
                self.session_id,
                csv_filename,
                self.work_dir,
            )

    def build_project_name_cache(self):
        """
        Build project name cache from Units and Buildings CSVs.

        Projects.csv only has Arabic names, English names come from Units/Buildings.
        """
        logger.info("Building project name cache...")

        # Scan Units.csv
        try:
            units_csv = self.get_csv_file("Units.csv")

            with open(units_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    project_number = row.get("project_number")
                    project_name_en = row.get("project_name_en")
                    if project_number and project_name_en:
                        self.project_name_cache[project_number] = project_name_en

            logger.info(
                f"Extracted {len(self.project_name_cache)} project names from Units.csv"
            )

        except Exception as e:
            logger.warning(f"Failed to process Units.csv for project names: {e}")

        # Scan Buildings.csv
        try:
            buildings_csv = self.get_csv_file("Buildings.csv")

            with open(buildings_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    project_number = row.get("project_number")
                    project_name_en = row.get("project_name_en")
                    if project_number and project_name_en:
                        self.project_name_cache[project_number] = project_name_en

            logger.info(
                f"Total {len(self.project_name_cache)} project names after Buildings.csv"
            )

        except Exception as e:
            logger.warning(f"Failed to process Buildings.csv for project names: {e}")

    def process_table(self, table_key: str):
        """
        Process a single table through the ETL pipeline.

        Args:
            table_key: Table key from TABLES config
        """
        table_config = TABLES[table_key]
        table_name = table_config.name

        logger.info(f"\n{'=' * 80}")
        logger.info(f"Processing table: {table_name}")
        logger.info(f"{'=' * 80}\n")

        # Get CSV file (local or S3)
        csv_file = self.get_csv_file(table_config.csv_filename)

        # Fetch current state
        current_state = fetch_current_state(
            self.ch_client,
            table_name,
            table_config.primary_key_cols,
        )

        # Stream CSV, diff, and collect changes
        changed_rows, seen_pks = stream_csv_and_diff(
            csv_file,
            table_config,
            current_state,
            self.run_id,
        )

        # Transform rows
        logger.info(f"Transforming {len(changed_rows):,} rows...")
        transformed_rows = []

        for row in changed_rows:
            try:
                if table_key == "transactions":
                    transformed = transform_transactions_row(
                        row, self.project_name_cache
                    )
                elif table_key == "rent_contracts":
                    transformed = transform_rent_contracts_row(
                        row, self.project_name_cache
                    )
                elif table_key == "projects":
                    transformed = transform_projects_row(row)
                elif table_key == "buildings":
                    transformed = transform_buildings_row(row)
                elif table_key == "units":
                    transformed = transform_units_row(row)
                elif table_key == "land_registry":
                    transformed = transform_land_registry_row(row)
                elif table_key == "developers":
                    transformed = transform_developers_row(row)
                elif table_key == "areas":
                    transformed = transform_areas_row(row)
                else:
                    transformed = row

                transformed_rows.append(transformed)

            except Exception as e:
                logger.error(f"Failed to transform row: {e}")
                continue

        # Insert changed rows
        if transformed_rows:
            self.loader.insert_batch(table_name, transformed_rows)

        # Detect and insert deletions
        deleted_rows = detect_deletions(
            current_state,
            seen_pks,
            table_config,
            self.run_id,
        )

        if deleted_rows:
            self.loader.insert_batch(table_name, deleted_rows)

        logger.info(f"\nCompleted processing {table_name}")
        logger.info(f"  - Changed/new rows: {len(transformed_rows):,}")
        logger.info(f"  - Deleted rows: {len(deleted_rows):,}")

    def run(self):
        """Run the full ETL pipeline."""
        logger.info(f"\n{'#' * 80}")
        logger.info(f"Starting ClickHouse ETL")
        logger.info(f"Session ID: {self.session_id}")
        logger.info(f"Run ID: {self.run_id}")
        if self.local_csv_dir:
            logger.info(f"Mode: Local CSV directory ({self.local_csv_dir})")
        else:
            logger.info(f"Mode: S3 download")
        logger.info(f"{'#' * 80}\n")

        # Build project name cache first
        self.build_project_name_cache()

        # Process each table in order
        for table_key in TABLE_ORDER:
            try:
                self.process_table(table_key)
            except Exception as e:
                logger.error(f"Failed to process table {table_key}: {e}")
                raise

        logger.info(f"\n{'#' * 80}")
        logger.info(f"ETL pipeline completed successfully")
        logger.info(f"Run ID: {self.run_id}")
        logger.info(f"{'#' * 80}\n")


def run_etl(
    session_id: str,
    work_dir: Path | None = None,
    ch_config: ClickHouseConfig | None = None,
    local_csv_dir: Path | None = None,
):
    """
    Main entry point for running the ETL pipeline.

    Args:
        session_id: Upload session UUID
        work_dir: Working directory for CSV downloads
        ch_config: ClickHouse configuration
        local_csv_dir: Local directory with CSV files (skips S3 download if provided)
    """
    if work_dir is None:
        work_dir = Path("/tmp/chETL")

    if ch_config is None:
        ch_config = ClickHouseConfig()

    work_dir.mkdir(parents=True, exist_ok=True)

    runner = ETLRunner(ch_config, session_id, work_dir, local_csv_dir)
    runner.run()
