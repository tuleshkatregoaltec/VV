"""S3 utilities for downloading and assembling chunked uploads."""

import json
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import boto3
from botocore.exceptions import ClientError

from .config import S3_BUCKET, S3_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

logger = logging.getLogger(__name__)


class S3Downloader:
    """Download and assemble chunked CSV files from S3."""

    def __init__(self):
        self.s3_client = boto3.client(
            "s3",
            region_name=S3_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )
        self.bucket = S3_BUCKET

    def get_metadata(self, session_id: str) -> Dict[str, Any]:
        """
        Fetch metadata.json for an upload session.

        Args:
            session_id: Upload session UUID

        Returns:
            Metadata dict with keys: session_id, filename, total_chunks, etc.
        """
        metadata_key = f"etl/uploads/{session_id}/metadata.json"

        try:
            response = self.s3_client.get_object(Bucket=self.bucket, Key=metadata_key)
            metadata = json.loads(response["Body"].read())
            logger.info(
                f"Loaded metadata for session {session_id}: {metadata['filename']}"
            )
            return metadata
        except ClientError as e:
            logger.error(f"Failed to fetch metadata for session {session_id}: {e}")
            raise

    def list_all_sessions(self) -> List[str]:
        """
        List all upload session IDs from S3.

        Returns:
            List of session UUIDs
        """
        try:
            prefix = "etl/uploads/"
            paginator = self.s3_client.get_paginator("list_objects_v2")

            session_ids = set()
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    key = obj["Key"]
                    if key.endswith("/metadata.json"):
                        # Extract session_id from etl/uploads/{session_id}/metadata.json
                        parts = key.split("/")
                        if len(parts) >= 3:
                            session_id = parts[2]
                            session_ids.add(session_id)

            return list(session_ids)

        except ClientError as e:
            logger.error(f"Failed to list upload sessions: {e}")
            return []

    def get_most_recent_session(self) -> Optional[str]:
        """
        Find the most recently uploaded session by checking metadata timestamps.

        Returns:
            Session ID of the most recent upload, or None if no sessions found
        """
        session_ids = self.list_all_sessions()

        if not session_ids:
            logger.warning("No upload sessions found in S3")
            return None

        logger.info(
            f"Found {len(session_ids)} upload sessions, determining most recent..."
        )

        most_recent_session = None
        most_recent_time = None

        for session_id in session_ids:
            try:
                metadata = self.get_metadata(session_id)
                uploaded_at_str = metadata.get("uploaded_at")

                if not uploaded_at_str:
                    logger.warning(
                        f"No uploaded_at timestamp in session {session_id} metadata"
                    )
                    continue

                # Parse ISO timestamp
                uploaded_at = datetime.fromisoformat(
                    uploaded_at_str.replace("Z", "+00:00")
                )

                if most_recent_time is None or uploaded_at > most_recent_time:
                    most_recent_time = uploaded_at
                    most_recent_session = session_id

                logger.debug(f"Session {session_id}: uploaded {uploaded_at_str}")

            except Exception as e:
                logger.warning(f"Failed to read metadata for session {session_id}: {e}")
                continue

        if most_recent_session:
            logger.info(
                f"Most recent session: {most_recent_session} (uploaded {most_recent_time})"
            )
        else:
            logger.warning("Could not determine most recent session")

        return most_recent_session

    def download_and_assemble(
        self,
        session_id: str,
        output_dir: Path,
    ) -> Path:
        """
        Download all chunks and assemble into a single CSV file.

        Args:
            session_id: Upload session UUID
            output_dir: Directory to save assembled file

        Returns:
            Path to assembled CSV file
        """
        metadata = self.get_metadata(session_id)

        filename = metadata["filename"]
        total_chunks = metadata["total_chunks"]
        expected_hash = metadata.get("expected_hash")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / filename

        logger.info(f"Assembling {filename} from {total_chunks} chunks...")

        hasher = hashlib.sha256()

        with open(output_file, "wb") as outf:
            for chunk_index in range(1, total_chunks + 1):
                chunk_key = f"etl/uploads/{session_id}/chunk_{chunk_index:04d}"

                try:
                    response = self.s3_client.get_object(
                        Bucket=self.bucket, Key=chunk_key
                    )
                    chunk_data = response["Body"].read()
                    outf.write(chunk_data)
                    hasher.update(chunk_data)

                    if chunk_index % 10 == 0:
                        logger.info(f"Downloaded chunk {chunk_index}/{total_chunks}")

                except ClientError as e:
                    logger.error(f"Failed to download chunk {chunk_index}: {e}")
                    raise

        actual_hash = hasher.hexdigest()

        if expected_hash and actual_hash != expected_hash:
            logger.error(
                f"Hash mismatch for {filename}: expected {expected_hash}, got {actual_hash}"
            )
            raise ValueError(f"File integrity check failed for {filename}")

        logger.info(
            f"Successfully assembled {filename} ({output_file.stat().st_size:,} bytes)"
        )

        return output_file

    def download_csv(
        self, session_id: str, csv_filename: str, output_dir: Path
    ) -> Path:
        """
        Download and assemble a specific CSV file from an upload session.

        This is a convenience wrapper around download_and_assemble that
        verifies the filename matches.

        Args:
            session_id: Upload session UUID
            csv_filename: Expected filename (e.g., "Transactions.csv")
            output_dir: Directory to save assembled file

        Returns:
            Path to assembled CSV file
        """
        assembled_path = self.download_and_assemble(session_id, output_dir)

        if assembled_path.name != csv_filename:
            logger.warning(
                f"Filename mismatch: expected {csv_filename}, got {assembled_path.name}"
            )

        return assembled_path
