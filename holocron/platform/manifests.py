from __future__ import annotations


def manifest_s3_key(*, source: str, run_id: str) -> str:
    return f"raw/source={source}/manifests/{run_id}.json"


def raw_file_s3_key(*, source: str, extract_date: str, run_id: str, file_name: str) -> str:
    return f"raw/source={source}/extract_date={extract_date}/run_id={run_id}/{file_name}"
