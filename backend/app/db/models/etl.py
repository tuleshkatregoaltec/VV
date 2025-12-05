"""ETL Metadata models for tracking data pipeline runs."""

from typing import Optional, LiteralString
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Index
from sqlalchemy import Text, DateTime


class ETLRunLog(SQLModel, table=True):
    """Tracks each ETL run with statistics and status per table."""

    __tablename__: LiteralString = "etl_run_logs"

    __table_args__ = (
        Index("idx_etl_run_logs_table_status", "table_name", "status"),
        Index("idx_etl_run_logs_completed", "run_completed_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Run identification
    run_id: str = Field(max_length=50, index=True)  # e.g., "2025-12-03T08:00:00"
    table_name: str = Field(max_length=100)

    # Timing - use TIMESTAMPTZ for timezone-aware datetimes
    run_started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
    run_completed_at: Optional[datetime] = Field(
        default=None,
        sa_type=DateTime(timezone=True),
    )

    # Status: 'running', 'completed', 'failed', 'skipped'
    status: str = Field(max_length=20, default="running")

    # Statistics
    rows_scanned: int = Field(default=0)
    rows_inserted: int = Field(default=0)
    rows_updated: int = Field(default=0)
    rows_skipped: int = Field(default=0)
    rows_errored: int = Field(default=0)

    # Error tracking (JSON array of error messages)
    errors: Optional[str] = Field(default=None, sa_type=Text)

    # File tracking
    current_csv_hash: Optional[str] = Field(default=None, max_length=64)
    previous_csv_hash: Optional[str] = Field(default=None, max_length=64)

    # Metadata
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )


class ETLState(SQLModel, table=True):
    """Tracks the current state of an in-progress ETL run for resumability."""

    __tablename__: LiteralString = "etl_state"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Current run info
    run_id: str = Field(max_length=50, unique=True)
    status: str = Field(
        max_length=20, default="in_progress"
    )  # 'in_progress', 'completed', 'failed'

    # Progress tracking
    current_table: Optional[str] = Field(default=None, max_length=100)
    current_offset: int = Field(default=0)
    completed_tables: str = Field(
        default="[]", sa_type=Text
    )  # JSON array of table names

    # Timing - use TIMESTAMPTZ for timezone-aware datetimes
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )

    # Configuration snapshot
    config_snapshot: Optional[str] = Field(
        default=None, sa_type=Text
    )  # JSON of run config


class ETLMetadata(SQLModel, table=True):
    """Tracks ETL pipeline runs for auditing and resumability.

    Each row represents a single table load within an ETL run.
    Use this to:
    - Find when data was last successfully loaded
    - Debug failed runs
    - Track row counts over time
    - Verify data integrity via CSV hashes
    """

    __tablename__: LiteralString = "etl_metadata"

    __table_args__ = (
        Index("idx_etl_metadata_table_status", "table_name", "status"),
        Index("idx_etl_metadata_completed", "run_completed_at"),
    )

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Run identification
    run_id: str = Field(
        max_length=50,
        index=True,
        description="Unique ID for the ETL run (timestamp-based)",
    )
    table_name: str = Field(
        max_length=100, description="Name of the table being loaded"
    )

    # Timing - use TIMESTAMPTZ for timezone-aware datetimes
    run_started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
        description="When this table load started",
    )
    run_completed_at: Optional[datetime] = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        description="When this table load completed (null if still running/failed)",
    )

    # Status
    status: str = Field(
        max_length=20,
        default="running",
        description="Current status: 'running', 'completed', 'failed'",
    )

    # Row counts
    rows_scanned: int = Field(default=0, description="Total rows scanned from CSV diff")
    rows_inserted: int = Field(default=0, description="New rows inserted")
    rows_updated: int = Field(default=0, description="Existing rows updated")
    rows_skipped: int = Field(default=0, description="Rows skipped (no changes)")
    rows_errored: int = Field(default=0, description="Rows that failed to process")

    # Error tracking
    errors: Optional[str] = Field(
        default=None, sa_type=Text, description="JSON array of error messages"
    )

    # File verification
    csv_row_count: Optional[int] = Field(
        default=None, description="Total row count in the source CSV"
    )
    csv_file_hash: Optional[str] = Field(
        default=None, max_length=64, description="SHA256 hash of the CSV file"
    )
    previous_csv_hash: Optional[str] = Field(
        default=None,
        max_length=64,
        description="SHA256 hash of the previous CSV (for diff verification)",
    )

    # Metadata
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )

    def mark_completed(
        self, inserted: int, updated: int, skipped: int, errored: int = 0
    ) -> None:
        """Mark this table load as completed."""
        self.status = "completed"
        self.run_completed_at = datetime.now(timezone.utc)
        self.rows_inserted = inserted
        self.rows_updated = updated
        self.rows_skipped = skipped
        self.rows_errored = errored

    def mark_failed(self, error_message: str) -> None:
        """Mark this table load as failed."""
        self.status = "failed"
        self.run_completed_at = datetime.now(timezone.utc)
        self.errors = error_message
