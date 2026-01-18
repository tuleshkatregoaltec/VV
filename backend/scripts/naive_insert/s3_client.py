"""Synchronous S3 client using boto3 for ETL operations."""

import os
import logging
from pathlib import Path

import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def get_s3_client() -> "S3Client":
    """Create S3 client from environment variables."""
    return S3Client(
        endpoint_url=os.environ["ETL_S3_ENDPOINT_URL"],
        access_key_id=os.environ["ETL_S3_ACCESS_KEY_ID"],
        secret_access_key=os.environ["ETL_S3_SECRET_ACCESS_KEY"],
        bucket_name=os.environ["ETL_S3_BUCKET_NAME"],
        region=os.environ.get("ETL_S3_REGION", "auto"),
    )


class S3Client:
    """Simple synchronous S3 client for ETL."""

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        region: str = "auto",
    ):
        self.bucket = bucket_name
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def upload_file(self, local_path: Path, s3_key: str) -> None:
        """Upload local file to S3."""
        self.client.upload_file(str(local_path), self.bucket, s3_key)

    def download_file(self, s3_key: str, local_path: Path) -> None:
        """Download S3 object to local file."""
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, s3_key, str(local_path))

    def download_bytes(self, s3_key: str) -> bytes:
        """Download S3 object as bytes."""
        response = self.client.get_object(Bucket=self.bucket, Key=s3_key)
        return response["Body"].read()

    def upload_bytes(self, s3_key: str, data: bytes) -> None:
        """Upload bytes to S3."""
        self.client.put_object(Bucket=self.bucket, Key=s3_key, Body=data)

    def list_objects(self, prefix: str) -> list[str]:
        """List object keys with given prefix."""
        paginator = self.client.get_paginator("list_objects_v2")
        keys = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def object_exists(self, s3_key: str) -> bool:
        """Check if object exists in S3."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=s3_key)
            return True
        except self.client.exceptions.ClientError:
            return False

    def delete_object(self, s3_key: str) -> None:
        """Delete object from S3."""
        self.client.delete_object(Bucket=self.bucket, Key=s3_key)
