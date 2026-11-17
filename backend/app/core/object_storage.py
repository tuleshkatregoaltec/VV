import logging
from contextlib import asynccontextmanager
from inspect import isawaitable

import aioboto3
from botocore.config import Config

logger = logging.getLogger(__name__)


class ObjectStorageClient:
    """Async object-storage client for chunk storage."""

    def __init__(
        self,
        endpoint_url: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
        bucket_name: str,
        region: str = "auto",
        use_path_style: bool = True,
    ):
        self.endpoint_url = endpoint_url
        self.bucket_name = bucket_name
        self.session = aioboto3.Session()
        self.client_kwargs = {
            "region_name": region,
            "config": Config(s3={"addressing_style": "path" if use_path_style else "auto"}),
        }
        # Without static keys the SDK's default chain applies (e.g. a container task role).
        if access_key_id and secret_access_key:
            self.client_kwargs["aws_access_key_id"] = access_key_id
            self.client_kwargs["aws_secret_access_key"] = secret_access_key
        if endpoint_url:
            self.client_kwargs["endpoint_url"] = endpoint_url

    @asynccontextmanager
    async def client(self):
        """Get the SDK client context."""
        async with self.session.client("s3", **self.client_kwargs) as s3:  # type: ignore
            yield s3

    async def upload(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        content_disposition: str | None = None,
    ):
        """Upload data to object storage."""
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        if content_disposition:
            extra["ContentDisposition"] = content_disposition
        async with self.client() as s3:
            await s3.put_object(Bucket=self.bucket_name, Key=key, Body=data, **extra)

    async def download(self, key: str) -> bytes:
        """Download data from object storage."""
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


class ObjectStorageSigningError(Exception):
    """The SDK rejected a synchronous presign request."""


async def sign_object_url(
    *,
    bucket: str,
    key: str,
    expires_in: int,
    client_kwargs: dict[str, str],
    response_content_disposition: str | None = None,
) -> str:
    """A presigned GET; `response_content_disposition` overrides the stored header for this link."""
    params = {"Bucket": bucket, "Key": key}
    if response_content_disposition:
        params["ResponseContentDisposition"] = response_content_disposition
    session = aioboto3.Session()
    async with session.client("s3", **client_kwargs) as s3:
        try:
            signed_url = s3.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=expires_in,
            )
        except Exception as exc:
            raise ObjectStorageSigningError() from exc
        if isawaitable(signed_url):
            signed_url = await signed_url
        return str(signed_url)
