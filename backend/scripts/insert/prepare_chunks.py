from __future__ import annotations

import json
import hashlib
import tempfile
from pathlib import Path

import boto3


def prepare_latest_csvs(
    *,
    bucket: str,
    region: str,
    access_key: str,
    secret_key: str,
    s3_base_url: str,
    uploads_prefix: str = "etl/uploads",
    out_prefix: str = "etl/runs/latest",
) -> dict[str, str]:
    s3 = boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    latest: dict[str, tuple[str, object]] = {}

    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(
        Bucket=bucket, Prefix=f"{uploads_prefix}/", Delimiter="/"
    ):
        for cp in page.get("CommonPrefixes", []):
            sid = cp["Prefix"].rstrip("/").split("/")[-1]
            meta_key = f"{uploads_prefix}/{sid}/metadata.json"
            try:
                meta = json.loads(
                    s3.get_object(Bucket=bucket, Key=meta_key)["Body"].read()
                )
                name = meta["filename"]
                lm = s3.head_object(Bucket=bucket, Key=meta_key)["LastModified"]
            except Exception:
                continue
            if name not in latest or lm > latest[name][1]:
                latest[name] = (sid, lm)

    out: dict[str, str] = {}

    for name, (sid, _) in latest.items():
        meta = json.loads(
            s3.get_object(Bucket=bucket, Key=f"{uploads_prefix}/{sid}/metadata.json")[
                "Body"
            ].read()
        )
        total = int(meta["total_chunks"])
        expected = meta.get("expected_hash")

        h = hashlib.sha256()
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            for i in range(1, total + 1):
                key = f"{uploads_prefix}/{sid}/chunk_{i:04d}"
                data = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
                tmp.write(data)
                h.update(data)

        if expected and h.hexdigest() != expected:
            tmp_path.unlink(missing_ok=True)
            raise ValueError(f"hash mismatch: {name}")

        out_key = f"{out_prefix}/{name}"
        s3.upload_file(str(tmp_path), bucket, out_key)
        tmp_path.unlink(missing_ok=True)

        out[name] = f"{s3_base_url.rstrip('/')}/{out_key}"

    return out
