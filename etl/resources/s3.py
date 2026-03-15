"""S3 resource: upload files, read/write manifests."""

from __future__ import annotations

import json
from pathlib import Path

import boto3
from dagster import ConfigurableResource, get_dagster_logger


class S3Resource(ConfigurableResource):
    bucket: str
    region: str = "us-east-1"
    endpoint_url: str = ""
    use_path_style: bool = False
    # Leave blank to use instance profile / env vars
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    def _client(self):
        kwargs: dict = {"region_name": self.region}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self.aws_access_key_id:
            kwargs["aws_access_key_id"] = self.aws_access_key_id
            kwargs["aws_secret_access_key"] = self.aws_secret_access_key
        if self.use_path_style:
            kwargs["config"] = boto3.session.Config(s3={"addressing_style": "path"})
        return boto3.client("s3", **kwargs)

    def upload_file(self, local_path: Path, s3_key: str) -> None:
        log = get_dagster_logger()
        log.info(f"Uploading {local_path} → s3://{self.bucket}/{s3_key}")
        self._client().upload_file(str(local_path), self.bucket, s3_key)

    def put_json(self, s3_key: str, data: dict | str) -> None:
        body = data if isinstance(data, str) else json.dumps(data, indent=2)
        self._client().put_object(
            Bucket=self.bucket,
            Key=s3_key,
            Body=body.encode(),
            ContentType="application/json",
        )

    def get_json(self, s3_key: str) -> dict:
        resp = self._client().get_object(Bucket=self.bucket, Key=s3_key)
        return json.loads(resp["Body"].read())

    def key_exists(self, s3_key: str) -> bool:
        client = self._client()
        try:
            client.head_object(Bucket=self.bucket, Key=s3_key)
            return True
        except client.exceptions.ClientError:
            return False

    def s3_url(self, s3_key: str) -> str:
        """Return an object URL suitable for ClickHouse s3() function."""
        if self.endpoint_url:
            base = self.endpoint_url.rstrip("/")
            if self.use_path_style:
                return f"{base}/{self.bucket}/{s3_key}"
            scheme, rest = base.split("://", 1)
            return f"{scheme}://{self.bucket}.{rest}/{s3_key}"
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{s3_key}"
