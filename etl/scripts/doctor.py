#!/usr/bin/env python3
"""Health check: verify connectivity to S3, ClickHouse, Dagster Postgres, and definitions."""

import os
import sys


def check_s3():
    import boto3
    from botocore.exceptions import ClientError

    bucket = os.environ.get("S3_BUCKET", "")
    if not bucket:
        return False, "S3_BUCKET not set"
    try:
        kwargs = {
            "region_name": os.environ.get("AWS_REGION", "us-east-1"),
            "endpoint_url": os.environ.get("S3_ENDPOINT_URL") or None,
            "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID") or None,
            "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY") or None,
        }
        if os.environ.get("S3_USE_PATH_STYLE", "false").lower() == "true":
            kwargs["config"] = boto3.session.Config(s3={"addressing_style": "path"})
        s3 = boto3.client("s3", **kwargs)
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
    url = os.environ.get("DAGSTER_POSTGRES_URL", "")
    if not url:
        return False, "DAGSTER_POSTGRES_URL not set"
    try:
        try:
            import psycopg  # type: ignore

            conn = psycopg.connect(url)
        except ImportError:
            import psycopg2  # type: ignore

            conn = psycopg2.connect(url)
        conn.close()
        return True, "connected"
    except ImportError:
        return None, "psycopg/psycopg2 not installed"
    except Exception as e:
        return False, str(e)


def check_definitions():
    try:
        from dagster import Definitions

        from etl.definitions import defs

        Definitions.validate_loadable(defs)
        return True, "Definitions.validate_loadable() OK"
    except Exception as e:
        return False, str(e)


def main():
    checks = [
        ("S3", check_s3),
        ("ClickHouse", check_clickhouse),
        ("Postgres (Dagster metadata)", check_postgres),
        ("Dagster definitions", check_definitions),
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
