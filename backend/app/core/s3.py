import logging
from contextlib import asynccontextmanager

import aioboto3
from botocore.config import Config

logger = logging.getLogger(__name__)


class S3Client:
    """Simple async S3 client for chunk storage"""

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        region: str = "auto",
        use_path_style: bool = True,
    ):
        self.endpoint_url = endpoint_url
        self.bucket_name = bucket_name
        self.session = aioboto3.Session()
        self.client_kwargs = {
            "endpoint_url": endpoint_url,
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
            "region_name": region,
            "config": Config(s3={"addressing_style": "path" if use_path_style else "auto"}),
        }

    @asynccontextmanager
    async def client(self):
        """Get S3 client context"""
        async with self.session.client("s3", **self.client_kwargs) as s3:  # type: ignore
            yield s3

    async def upload(self, key: str, data: bytes):
        """Upload data to S3"""
        async with self.client() as s3:
            await s3.put_object(Bucket=self.bucket_name, Key=key, Body=data)

    async def download(self, key: str) -> bytes:
        """Download data from S3"""
        async with self.client() as s3:
            response = await s3.get_object(Bucket=self.bucket_name, Key=key)
            return await response["Body"].read()

    async def delete_many(self, keys: list[str]):
        """Delete multiple objects"""
        if not keys:
            return
        async with self.client() as s3:
            objects = [{"Key": key} for key in keys]
            await s3.delete_objects(Bucket=self.bucket_name, Delete={"Objects": objects})
