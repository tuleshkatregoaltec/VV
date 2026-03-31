"""S3 path conventions for Holocron sources."""

from __future__ import annotations


def raw_key(dataset: str, release_id: str, filename: str) -> str:
    return f"raw/{dataset}/{release_id}/{filename}"


def manifest_key(dataset: str, release_id: str) -> str:
    return f"manifests/{dataset}/{release_id}.json"
