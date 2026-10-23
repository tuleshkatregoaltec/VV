#!/usr/bin/env python3
"""Dry-run DXBI name repairs from retained provider report JSONL (optionally gzip).

Reads the configured warehouse; never writes it. Output is a private JSONL file
with source checksums, line references, original values and unresolved reasons.
Run with the local environment loaded and PYTHONPATH=holocron from repo root.
"""

import argparse
import gzip
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

import clickhouse_connect

from holocron.sources.dxbi.repairs import propose_name_repair
from holocron.sources.dxbi.sales_units import compact_payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    client = clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
        port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
        username=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        database=os.environ.get("CLICKHOUSE_DATABASE", "default"),
        secure=os.environ.get("CLICKHOUSE_SECURE", "").lower() in {"true", "1"},
    )
    counts: Counter[str] = Counter()
    try:
        with args.output.open("x", encoding="utf-8") as output:
            args.output.chmod(0o600)
            for file in args.files:
                with file.open("rb") as source:
                    digest = hashlib.file_digest(source, "sha256").hexdigest()
                opener = gzip.open if file.suffix == ".gz" else open
                with opener(file, "rt", encoding="utf-8") as raw:
                    for line_number, line in enumerate(raw, 1):
                        try:
                            payload = compact_payload(line)
                            url = payload.get("detail_url", "")
                            rows = (
                                list(
                                    client.query(
                                        "SELECT * FROM dxbi_sales_unit_events FINAL WHERE detail_url={url:String}",
                                        parameters={"url": url},
                                    ).named_results()
                                )
                                if url and payload.get("location_title")
                                else []
                            )
                            proposal = propose_name_repair(payload, rows)
                        except (ValueError, TypeError, KeyError):
                            proposal = {"status": "unresolved", "reason": "invalid_source_record"}
                        counts[proposal["status"]] += 1
                        output.write(
                            json.dumps(
                                {
                                    **proposal,
                                    "source_file": str(file),
                                    "source_sha256": digest,
                                    "line": line_number,
                                }
                            )
                            + "\n"
                        )
                with file.open("rb") as source:
                    final_digest = hashlib.file_digest(source, "sha256").hexdigest()
                if final_digest != digest:
                    raise RuntimeError("Source changed during dry-run; discard proposals")
        print(json.dumps({"mode": "dry_run_only", "outcomes": counts}))
    finally:
        client.close()


if __name__ == "__main__":
    main()
