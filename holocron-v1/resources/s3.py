"""S3 resource: upload files and read/write manifests."""

from __future__ import annotations

import json
from pathlib import Path

import boto3
from dagster import ConfigurableResource, get_dagster_logger
from pydantic import PrivateAttr


class S3Resource(ConfigurableResource):
    bucket: str
    region: str = "us-east-1"
    endpoint_url: str = ""
    use_path_style: bool = False
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    _client_instance: object = PrivateAttr(default=None)

    def _client(self):
        if self._client_instance is None:
            kwargs: dict = {"region_name": self.region}
            if self.endpoint_url:
                kwargs["endpoint_url"] = self.endpoint_url
            if self.aws_access_key_id:
                kwargs["aws_access_key_id"] = self.aws_access_key_id
                kwargs["aws_secret_access_key"] = self.aws_secret_access_key
            if self.use_path_style:
                kwargs["config"] = boto3.session.Config(s3={"addressing_style": "path"})
            self._client_instance = boto3.client("s3", **kwargs)
        return self._client_instance

    def upload_file(self, local_path: Path, s3_key: str) -> None:
        get_dagster_logger().info(f"Uploading {local_path} -> s3://{self.bucket}/{s3_key}")
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

    def s3_url(self, s3_key: str) -> str:
        if self.endpoint_url:
            base = self.endpoint_url.rstrip("/")
            if self.use_path_style:
                return f"{base}/{self.bucket}/{s3_key}"
            scheme, rest = base.split("://", 1)
            return f"{scheme}://{self.bucket}.{rest}/{s3_key}"
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{s3_key}"
