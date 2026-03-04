"""Load data/geocode.csv into ch_geo_buildings."""

import csv
import os
import sys

from clickhouse_driver import Client

CLICKHOUSE_HOST = os.environ.get("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.environ.get("CLICKHOUSE_PORT", "9001"))
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "vitevue")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "vitevue_dev")
CLICKHOUSE_DB = os.environ.get("CLICKHOUSE_DB", "vitevue")

CSV_PATH = os.environ.get(
    "GEOCODE_CSV_PATH",
    os.path.join(os.path.dirname(__file__), "../../../data/geocode.csv"),
)


def main():
    client = Client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        database=CLICKHOUSE_DB,
    )

    with open(CSV_PATH) as f:
        rows = list(csv.DictReader(f))

    data = [
        (
            r["address_key"],
            r["building_name_en"].strip(),
            r["project_name_en"].strip(),
            r["master_project_en"].strip(),
            r["area_name_en"].strip(),
            float(r["lat"]),
            float(r["lng"]),
        )
        for r in rows
        if r["lat"] and r["lng"]
    ]

    client.execute("TRUNCATE TABLE ch_geo_buildings")
    client.execute(
        "INSERT INTO ch_geo_buildings "
        "(address_key, building_name_en, project_name_en, master_project_en, area_name_en, lat, lng) "
        "VALUES",
        data,
    )

    print(f"Inserted {len(data)} rows into ch_geo_buildings")


if __name__ == "__main__":
    main()
