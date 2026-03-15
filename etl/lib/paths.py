"""S3 path conventions for all datasets."""

from __future__ import annotations


def raw_key(dataset: str, release_id: str, filename: str) -> str:
    return f"raw/{dataset}/{release_id}/{filename}"


def manifest_key(dataset: str, release_id: str) -> str:
    return f"manifests/{dataset}/{release_id}.json"


def dld_raw_prefix(batch_id: str) -> str:
    return f"raw/dld/{batch_id}"


def dld_raw_key(batch_id: str, filename: str) -> str:
    return raw_key("dld", batch_id, filename)


def dld_manifest_key(batch_id: str) -> str:
    return manifest_key("dld", batch_id)


def gis_raw_prefix(run_id: str) -> str:
    return f"raw/gis/{run_id}"


def gis_raw_key(run_id: str, filename: str) -> str:
    return raw_key("gis", run_id, filename)


def gis_manifest_key(run_id: str) -> str:
    return manifest_key("gis", run_id)


def gis_layer_manifest_key(run_id: str, layer: str) -> str:
    return f"manifests/gis/{run_id}/{layer}.json"


def geo_raw_prefix(run_id: str) -> str:
    return f"raw/geo/{run_id}"


def geo_raw_key(run_id: str, filename: str) -> str:
    return raw_key("geo", run_id, filename)


def geo_manifest_key(run_id: str) -> str:
    return manifest_key("geo", run_id)


def dxbi_raw_prefix(run_id: str) -> str:
    return f"raw/dxbi/{run_id}"


def dxbi_raw_key(run_id: str, filename: str) -> str:
    return raw_key("dxbi", run_id, filename)


def dxbi_manifest_key(run_id: str) -> str:
    return manifest_key("dxbi", run_id)


def s3_url(bucket: str, key: str, region: str = "us-east-1") -> str:
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
