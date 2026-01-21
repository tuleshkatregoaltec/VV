"""S3 utilities for downloading and assembling chunked uploads."""

import json
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any
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
