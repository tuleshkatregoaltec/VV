"""Measure what Market API requests cost ClickHouse, from system.query_log (read-only).

Each cold request uses a page size no cache holds yet, waits for ClickHouse to flush its query
log, then sums the queries that started inside the request's window and read the request's
tables. The summary repeat checks that a second identical call starts no warehouse query.

    python backend/scripts/clickhouse/measure_market_api.py \\
        --api https://api-pilot.vitevue.com --token-file /path/to/token --ssh maan@HOST

The token is read from a file and never printed. Run at most a few times: each run makes 9 GETs.
"""

import argparse
import json
import random
import subprocess
import time
import urllib.request
from collections.abc import Mapping
from datetime import datetime

SCENARIOS = [
    # (label, path, tables a matching query reads)
    (
        "transactions sales all-time (count + page)",
        "/api/v1/transactions/sales?limit={n}",
        ("dxbi_sales_page", "dxbi_sales_unit_events"),
    ),
    (
        "transactions sales Residential 30d (count + page)",
        "/api/v1/transactions/sales?property_usage=Residential&timeframe_days=30&limit={n}",
        ("dxbi_sales_page", "dxbi_sales_unit_events"),
    ),
    (
        "filters sales all-time",
        "/api/v1/filters/sales?size_min=0.{n}",
        ("dxbi_sales_page", "dxbi_sales_unit_events"),
    ),
    (
        "transactions rentals Residential 30d (count + page)",
        "/api/v1/transactions/rentals?property_usage=Residential&timeframe_days=30&limit={n}",
        ("dxbi_leases_page", "dxbi_rental_events"),
    ),
]
SUMMARY = "/api/v1/analytics/project/summary?summary_days={n}&usage=auto"


def clickhouse(ssh: str, sql: str) -> list[dict]:
    command = (  # read-only: the script never writes to the warehouse
        "sudo docker exec -i vv-clickhouse-1 clickhouse-client -d vitevue --readonly 1 "
        "-f JSONEachRow"
    )
    output = subprocess.run(
        ["ssh", ssh, command], input=sql, capture_output=True, text=True, check=True
    ).stdout
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def server_now(ssh: str) -> str:
    return clickhouse(ssh, "SELECT toString(now64(3)) AS measure_now")[0]["measure_now"]


def get(api: str, token: str, path: str) -> tuple[int, float, int, Mapping[str, str]]:
    request = urllib.request.Request(
        api + path, headers={"Authorization": f"Bearer {token}", "User-Agent": "vv-measure"}
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
            return response.status, time.perf_counter() - started, len(body), response.headers
    except urllib.error.HTTPError as error:
        return error.code, time.perf_counter() - started, 0, error.headers


def window_queries(ssh: str, start: str, end: str, tables: tuple[str, ...] = ()) -> list[dict]:
    reads = " OR ".join(f"position(query, '{table}') > 0" for table in tables) or "1"
    return clickhouse(
        ssh,
        f"""
        SELECT normalized_query_hash AS hash, query_duration_ms AS ms, read_rows,
               memory_usage AS memory
        FROM system.query_log
        WHERE type = 'QueryFinish' AND query_kind = 'Select'
          AND query_start_time_microseconds BETWEEN '{start}' AND '{end}'
          AND position(query, 'system.') = 0 AND position(query, 'AS measure_now') = 0
          AND ({reads})
        """,
    )


def measure(ssh, api, token, path, tables=()):
    start = server_now(ssh)
    status, seconds, size, headers = get(api, token, path)
    end = server_now(ssh)
    time.sleep(9)  # query_log flushes every 7.5 s
    return status, seconds, size, window_queries(ssh, start, end, tables)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--ssh", required=True)
    args = parser.parse_args()
    token = open(args.token_file).read().strip()
    nonce = random.randint(11, 29)
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} page size {nonce} (cold)")
    for label, path, tables in SCENARIOS:
        status, seconds, size, rows = measure(
            args.ssh, args.api, token, path.format(n=nonce), tables
        )
        print(
            f"{label:52} HTTP {status} {seconds:5.2f}s {size / 1024:7.1f} KiB | "
            f"queries={len(rows)} read_rows={sum(int(r['read_rows']) for r in rows):,} "
            f"peak={max([int(r['memory']) for r in rows] or [0]) / 2**20:.1f} MiB "
            f"ch_ms={sum(int(r['ms']) for r in rows)}"
        )
    summary = SUMMARY.format(n=3000 + nonce)
    first = measure(args.ssh, args.api, token, summary)
    second = measure(args.ssh, args.api, token, summary)
    hashes = {row["hash"] for row in first[3]}
    repeated = [row for row in second[3] if row["hash"] in hashes]
    print(
        f"{'analytics summary first call':52} HTTP {first[0]} {first[1]:5.2f}s | "
        f"queries={len(first[3])} read_rows={sum(int(r['read_rows']) for r in first[3]):,}"
    )
    print(
        f"{'analytics summary repeat (same params)':52} HTTP {second[0]} {second[1]:5.2f}s | "
        f"summary queries repeated={len(repeated)} (0 = served from cache)"
    )
    status, seconds, size, headers = get(
        args.api, token, "/api/v1/transactions/sales/export?format=csv"
    )
    print(
        f"{'sales CSV export, all time':52} HTTP {status} {seconds:5.2f}s "
        f"{size / 2**20:.1f} MiB | X-Export-Truncated={headers.get('X-Export-Truncated')} "
        f"rows={headers.get('X-Export-Rows')} matching={headers.get('X-Export-Matching-Rows')}"
    )


if __name__ == "__main__":
    main()
