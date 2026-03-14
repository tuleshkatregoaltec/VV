#!/usr/bin/env python3
"""
Health check: verify connectivity to S3, ClickHouse, and Dagster Postgres.

Usage:
    python -m etl.scripts.doctor
"""

import os
import sys


def check_s3():
    import boto3
    from botocore.exceptions import ClientError

    bucket = os.environ.get("S3_BUCKET", "")
    if not bucket:
        return False, "S3_BUCKET not set"
    try:
        s3 = boto3.client(
            "s3",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID") or None,
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY") or None,
        )
        s3.head_bucket(Bucket=bucket)
        return True, f"bucket={bucket} OK"
    except ClientError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


def check_clickhouse():
    import clickhouse_connect

    try:
        client = clickhouse_connect.get_client(
            host=os.environ["CLICKHOUSE_HOST"],
            port=int(os.environ.get("CLICKHOUSE_PORT", "8443")),
            username=os.environ.get("CLICKHOUSE_USER", "default"),
            password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
            database=os.environ.get("CLICKHOUSE_DATABASE", "default"),
            secure=os.environ.get("CLICKHOUSE_SECURE", "true").lower() == "true",
        )
        version = client.query("SELECT version()").first_row[0]
        return True, f"version={version}"
    except Exception as e:
        return False, str(e)


def check_postgres():
    import urllib.parse

    url = os.environ.get("DAGSTER_POSTGRES_URL", "")
    if not url:
        return False, "DAGSTER_POSTGRES_URL not set"
    try:
        import psycopg2  # type: ignore

        conn = psycopg2.connect(url)
        conn.close()
        return True, "connected"
    except ImportError:
        return None, "psycopg2 not installed (optional)"
    except Exception as e:
        return False, str(e)


def main():
    checks = [
        ("S3", check_s3),
        ("ClickHouse", check_clickhouse),
        ("Postgres (Dagster metadata)", check_postgres),
    ]

    all_ok = True
    for name, fn in checks:
        ok, msg = fn()
        if ok is True:
            status = "OK"
        elif ok is False:
            status = "FAIL"
            all_ok = False
        else:
            status = "SKIP"
        print(f"[{status:4s}] {name}: {msg}")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
