from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

from holocron.platform.settings import Settings


class S3Client:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.s3_bucket
        session = boto3.session.Session(region_name=settings.s3_region)
        config = Config(s3={"addressing_style": "path" if settings.s3_use_path_style else "auto"})
        self._client = session.client("s3", endpoint_url=settings.s3_endpoint_url, config=config)

    @property
    def bucket(self) -> str:
        return self._bucket

    def upload_file(self, *, path: str | Path, key: str, content_type: str | None = None) -> None:
        extra_args = {"ContentType": content_type} if content_type else None
        self._client.upload_file(str(path), self._bucket, key, ExtraArgs=extra_args or {})

    def put_json(self, *, key: str, payload: dict[str, Any]) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=json.dumps(payload, sort_keys=True).encode("utf-8"),
            ContentType="application/json",
        )

    def put_bytes(self, *, key: str, payload: bytes, content_type: str | None = None) -> None:
        extra_args: dict[str, Any] = {}
        if content_type:
            extra_args["ContentType"] = content_type
        self._client.put_object(Bucket=self._bucket, Key=key, Body=payload, **extra_args)
