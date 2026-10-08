"""Check the DXBI Transactions API against the raw DXBI tables, independently.

The Transactions pages show DXBI records only (app.transaction.queries). This script recomputes
the last 365 days in pandas straight from dxbi_sales_unit_events and dxbi_rental_events, with the
page's rules re-implemented here rather than imported (one row per sale or lease, the location
spelling, Residential / Commercial grouping, bedroom labels, DXBI's own sizes in sq ft and price per sq
ft, half-open bands, the date window), and compares the live API with it:

- totals and the first, a middle and the last page of every period (7-365 days) and usage;
- every field of every compared row;
- one page per filter value (types, bedrooms, status / contract type, top locations, buildings);
- every size, price, price per sq ft and rent band, and that the bands' totals add up to the rows
  that have a value (no overlap, no gap);
- the filter options.

Read-only: one SELECT-only ClickHouse connection and GET requests.

    VERIFY_API_TOKEN=<bearer token> uv run python -m scripts.clickhouse.verify_dxbi_transactions
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

import clickhouse_connect
import pandas as pd

from app.config import settings

RESIDENTIAL = {"Apartment", "Villa", "Townhouse", "Hotel Apartment"}
COMMERCIAL = {
    "Office",
    "Shop",
    "Show Rooms",
    "Warehouse",
    "Workshop",
    "Clinic",
    "Gymnasium",
    "Hotel",
    "Sized Partition",
    "Building",
    "Commercial",
}
SIZE_BANDS = [(None, 500), (500, 1_000), (1_000, 2_000), (2_000, 5_000), (5_000, None)]
PRICE_BANDS = [
    (None, 500_000),
    (500_000, 1_000_000),
    (1_000_000, 2_000_000),
    (2_000_000, 5_000_000),
    (5_000_000, None),
]
PRICE_SQFT_BANDS = [(None, 1_000), (1_000, 2_000), (2_000, 3_000), (3_000, None)]
RENT_BANDS = [(None, 50_000), (50_000, 100_000), (100_000, 200_000), (200_000, None)]


class Verifier:
    def __init__(self, api_url: str, token: str) -> None:
        self.api_url = api_url.rstrip("/") + "/api/v1"
        self.token = token
        self.today = date.today()
        self.checks = 0
        self.failures: list[str] = []
        self.ch = clickhouse_connect.get_client(
            host=settings.CLICKHOUSE_HOST,
            port=settings.CLICKHOUSE_PORT,
            username=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD,
            database=settings.CLICKHOUSE_DATABASE,
            secure=settings.CLICKHOUSE_SECURE,
            send_receive_timeout=900,
            settings={"readonly": 1},
        )

    # -- plumbing ----------------------------------------------------------------------------
    def check(self, ok: bool, message: str) -> None:
        self.checks += 1
        if not ok:
            self.failures.append(message)
            print("FAIL", message, flush=True)

    def api(self, path: str, **params) -> dict:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        request = urllib.request.Request(
            f"{self.api_url}/{path}?{query}", headers={"Authorization": f"Bearer {self.token}"}
        )
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read())

    # -- independent expectation -------------------------------------------------------------
    def load(self) -> None:
        names = self.ch.query_df(
            "SELECT area_name, count() AS n FROM (SELECT area_name FROM dxbi_sales_unit_events "
            "UNION ALL SELECT area_name FROM dxbi_rental_events) WHERE area_name != '' "
            "GROUP BY area_name"
        )
        names["k"] = names.area_name.map(_letters)
        self.spelling = (
            names.sort_values(["k", "n"], ascending=[True, False])
            .drop_duplicates("k")
            .set_index("k")
            .area_name.to_dict()
        )
        start = self.today - timedelta(days=364)
        self.sales = self._sales(start)
        self.rentals = self._rentals(start)

    def _location(self, area: str) -> str:
        if area == "" or area.startswith("No."):
            return ""
        if re.search(r"\sDubai$", area):
            stripped = _letters(re.sub(r"\s+Dubai$", "", area))
            if stripped in self.spelling:
                return self.spelling[stripped]
        return self.spelling.get(_letters(area), area)

    def _sales(self, start: date) -> pd.DataFrame:
        sales = self.ch.query_df(
            "SELECT sale_key, transaction_date, unit_number, building_name, building_key, "
            "project_name, area_name, property_type, market_status, bedrooms, size_sqft, size_key, "
            "sale_amount_aed, price_per_sqft_aed, detail_url, loaded_at FROM dxbi_sales_unit_events "
            f"WHERE transaction_date BETWEEN '{start}' AND '{self.today}'"
        )
        raw = len(sales)
        # Latest version of each sale; ties go to the more complete listing.
        sales["no_area"] = sales.area_name == ""
        sales["no_beds"] = sales.bedrooms == ""
        sales["no_status"] = sales.market_status == ""
        sales["building_length"] = sales.building_name.str.len()
        sales = sales.sort_values(
            [
                "sale_key",
                "loaded_at",
                "no_area",
                "no_beds",
                "no_status",
                "building_length",
                "building_key",
                "bedrooms",
                "size_key",
            ],
            ascending=[True, False, True, True, True, True, True, True, True],
            kind="mergesort",
        ).drop_duplicates("sale_key")
        versions = raw - len(sales)
        # One real (numbered) unit sold on one day at one price is one sale; the scrape wins.
        numbered = sales.unit_number.str.contains(r"[0-9]")
        sales["same"] = sales.sale_key
        sales.loc[numbered, "same"] = (
            sales.building_key
            + "|"
            + sales.unit_number
            + "|"
            + sales.transaction_date.astype(str)
            + "|"
            + sales.sale_amount_aed.astype(str)
        )[numbered]
        sales["no_url"] = sales.detail_url == ""
        before = len(sales)
        sales = sales.sort_values(
            ["same", "no_url", "loaded_at", "sale_key"],
            ascending=[True, True, False, True],
            kind="mergesort",
        ).drop_duplicates("same")
        print(
            f"sales: {raw} raw rows in 365 days -> {len(sales)} sales "
            f"({versions} older or duplicate versions, {before - len(sales)} same-unit same-day "
            "copies removed)"
        )
        sales["location"] = sales.area_name.map(self._location)
        sales["usage"] = sales.property_type.map(_usage)
        sales["beds"] = sales.bedrooms.map(_bedrooms)
        sales["status"] = sales.market_status.map({"Offplan": "Off-Plan", "Ready": "Ready"}).fillna(
            ""
        )
        sales["size"] = [s if s > 0 else None for s in sales.size_sqft]
        # DXBI's own price per sq ft when it has one (villas: price / built-up area), else price / size.
        sales["ppsqft"] = [
            int(round(f))
            if _missing(f) is not None and f > 0
            else int(round(p / s))
            if s > 0
            else None
            for p, s, f in zip(sales.sale_amount_aed, sales.size_sqft, sales.price_per_sqft_aed)
        ]
        sales["d"] = pd.to_datetime(sales.transaction_date).dt.date
        return sales

    def _rentals(self, start: date) -> pd.DataFrame:
        rentals = self.ch.query_df(
            "SELECT contract_key, occurrence_index, unit_number, location_name, building_name, "
            "project_name, area_name, property_type, bedrooms, size_sqft, contract_amount_aed, "
            "annual_rent_aed, contract_term_months, lease_start, lease_end, contract_state, "
            "loaded_at FROM dxbi_rental_events "
            f"WHERE lease_start BETWEEN '{start}' AND '{self.today}'"
        )
        raw = len(rentals)
        rentals = rentals.sort_values("loaded_at", ascending=False).drop_duplicates(
            ["lease_start", "contract_key"]
        )
        current = len(rentals)
        # A lease listed without its unit whose terms equal a numbered lease's is that lease.
        terms = [
            "area_name",
            "property_type",
            "bedrooms",
            "size_sqft",
            "lease_start",
            "lease_end",
            "contract_amount_aed",
            "contract_state",
        ]
        numbered_terms = set(
            rentals[rentals.unit_number != ""][terms].astype(str).agg("|".join, axis=1)
        )
        copy = (rentals.unit_number == "") & rentals[terms].astype(str).agg("|".join, axis=1).isin(
            numbered_terms
        )
        rentals = rentals[~copy]
        copies = int(copy.sum())
        # A numbered unit holds one copy of a lease; unnumbered identical rows all count.
        numbered = rentals.unit_number != ""
        identity = [
            "unit_number",
            "location_name",
            "property_type",
            "bedrooms",
            "size_sqft",
            "lease_start",
            "lease_end",
            "contract_amount_aed",
            "contract_state",
        ]
        rentals["same"] = rentals.contract_key
        rentals.loc[numbered, "same"] = (
            rentals[numbered][identity].astype(str).agg("|".join, axis=1)
        )
        rentals = rentals.sort_values(
            ["occurrence_index", "contract_key"], kind="mergesort"
        ).drop_duplicates("same")
        print(
            f"rentals: {raw} raw rows starting in 365 days -> {len(rentals)} leases "
            f"({raw - current} superseded, {copies} unit-less copies of numbered leases and "
            f"{current - copies - len(rentals)} repeated numbered-unit rows removed)"
        )
        rentals["location"] = rentals.area_name.map(self._location)
        rentals["usage"] = rentals.property_type.map(_usage)
        rentals["beds"] = rentals.bedrooms.map(_bedrooms)
        rentals["size"] = [s if s > 0 else None for s in rentals.size_sqft]
        rentals["d"] = pd.to_datetime(rentals.lease_start).dt.date
        return rentals

    # -- comparisons ---------------------------------------------------------------------------
    def window(self, frame: pd.DataFrame, days: int) -> pd.DataFrame:
        return frame[(frame.d > self.today - timedelta(days=days)) & (frame.d <= self.today)]

    def expected(self, kind: str, days: int, **f) -> pd.DataFrame:
        sales = kind == "sales"
        frame = self.window(self.sales if sales else self.rentals, days)
        equal = [
            ("usage", "property_usage"),
            ("property_type", "property_type"),
            ("beds", "bedrooms"),
            ("location", "location"),
            ("building_name", "building"),
            ("status", "status") if sales else ("contract_state", "contract_type"),
        ]
        for column, name in equal:
            if f.get(name):
                frame = frame[frame[column] == f[name]]
        bands = (
            [("size", "size"), ("sale_amount_aed", "price"), ("ppsqft", "price_per_sqft")]
            if sales
            else [("size", "size"), ("annual_rent_aed", "rent")]
        )
        for column, name in bands:
            low, high = f.get(f"{name}_min"), f.get(f"{name}_max")
            if low is None and high is None:
                continue
            values = frame[column].astype("float64")
            if name == "rent":
                values = values.where(values > 0)
            mask = values.notna()
            if low is not None:
                mask &= values >= low
            if high is not None:
                mask &= values < high
            frame = frame[mask]
        key = "sale_key" if sales else "contract_key"
        return frame.sort_values(["d", key], ascending=[False, True])

    def compare_page(self, kind: str, days: int, offset: int, filters: dict) -> None:
        expected = self.expected(kind, days, **filters)
        body = self.api(
            f"transactions/{kind}", timeframe_days=days, limit=30, offset=offset, **filters
        )
        label = f"{kind} {days}d {filters} offset {offset}"
        self.check(
            body["total"] == len(expected), f"{label}: total {body['total']} != {len(expected)}"
        )
        rows = body["transactions" if kind == "sales" else "contracts"]
        want = [
            _sale_fields(r) if kind == "sales" else _rental_fields(r)
            for r in expected.iloc[offset : offset + 30].itertuples()
        ]
        self.check(len(rows) == len(want), f"{label}: {len(rows)} rows != {len(want)}")
        for got, exp in zip(rows, want):
            if got != exp:
                diff = {k: (got.get(k), exp.get(k)) for k in exp if got.get(k) != exp.get(k)}
                self.check(False, f"{label}: row differs {diff}")
                return

    def compare_options(self, kind: str, days: int, **filters) -> None:
        body = self.api(f"filters/{kind}", timeframe_days=days, **filters)
        expected = self.expected(kind, days, **filters)
        alphabetical = _alphabetical
        want = {
            "locations": alphabetical(expected.location),
            "buildings": alphabetical(v.strip() for v in expected.building_name),
            "property_types": alphabetical(expected.property_type),
            "bedrooms": sorted(
                {v for v in expected.beds if v},
                key=lambda b: (0, 0) if b == "Studio" else (1, int(b.split()[0])),
            ),
        }
        if kind == "sales":
            want["statuses"] = alphabetical(expected.status)
        else:
            want["contract_types"] = alphabetical(expected.contract_state)
        for field, values in want.items():
            self.check(body[field] == values, f"options {kind} {days}d {filters} {field}")

    def run(self) -> int:
        self.load()
        for days in (7, 30, 90, 180, 365):
            for usage in (None, "Residential", "Commercial"):
                filters = {"property_usage": usage} if usage else {}
                for kind in ("sales", "rentals"):
                    total = len(self.expected(kind, days, **filters))
                    offsets = {0}
                    if total > 60:
                        offsets |= {(total // 60) * 30, ((total - 1) // 30) * 30}
                    for offset in sorted(offsets):
                        self.compare_page(kind, days, offset, filters)

        year = {"sales": self.window(self.sales, 365), "rentals": self.window(self.rentals, 365)}
        values = {
            "sales": [
                ("property_type", "property_type"),
                ("bedrooms", "beds"),
                ("status", "status"),
            ],
            "rentals": [
                ("property_type", "property_type"),
                ("bedrooms", "beds"),
                ("contract_type", "contract_state"),
            ],
        }
        for kind, fields in values.items():
            frame = year[kind]
            for name, column in fields:
                for value in sorted(v for v in frame[column].unique() if v):
                    self.compare_page(kind, 365, 0, {name: value})
            for value in frame.location.value_counts().index[:8]:
                self.compare_page(kind, 365, 0, {"location": value})
            buildings = frame[frame.building_name != ""].building_name.value_counts().index[:4]
            for value in buildings:
                self.compare_page(kind, 365, 0, {"building": value})

        for kind, name, bands, column in (
            ("sales", "size", SIZE_BANDS, "size"),
            ("sales", "price", PRICE_BANDS, "sale_amount_aed"),
            ("sales", "price_per_sqft", PRICE_SQFT_BANDS, "ppsqft"),
            ("rentals", "size", SIZE_BANDS, "size"),
            ("rentals", "rent", RENT_BANDS, "annual_rent_aed"),
        ):
            total = 0
            for low, high in bands:
                band = {
                    k: v
                    for k, v in {f"{name}_min": low, f"{name}_max": high}.items()
                    if v is not None
                }
                self.compare_page(kind, 365, 0, band)
                total += self.api(f"transactions/{kind}", timeframe_days=365, limit=1, **band)[
                    "total"
                ]
            values_ = year[kind][column].astype("float64")
            with_value = int((values_.notna() & (values_ > 0 if name == "rent" else True)).sum())
            self.check(
                total == with_value,
                f"{kind} {name} bands add up to {total}, rows with a value {with_value}",
            )

        self.compare_options("sales", 365, property_usage="Residential")
        self.compare_options("sales", 30, property_usage="Commercial")
        self.compare_options("sales", 90)
        self.compare_options("rentals", 365, property_usage="Residential")
        self.compare_options("rentals", 30)

        print(f"\n{self.checks} checks, {len(self.failures)} failures")
        return 1 if self.failures else 0


def _alphabetical(values) -> list[str]:
    return sorted({v for v in values if v}, key=lambda v: (v.casefold(), v))


def _letters(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _usage(kind: str) -> str:
    return "Residential" if kind in RESIDENTIAL else "Commercial" if kind in COMMERCIAL else ""


def _bedrooms(value: str) -> str:
    if value == "Studio":
        return "Studio"
    match = re.fullmatch(r"([0-9]+) Beds?", value)
    if not match:
        return ""
    return f"{match.group(1)} Bed" + ("" if match.group(1) == "1" else "s")


def _missing(value):
    return (
        None
        if value is None or value == "" or (isinstance(value, float) and pd.isna(value))
        else value
    )


def _sale_fields(r) -> dict:
    return {
        "transaction_id": r.sale_key,
        "transaction_date": str(r.d),
        "unit_number": _missing(r.unit_number),
        "building_name": _missing(r.building_name),
        "project_name": _missing(r.project_name),
        "location_name": _missing(r.location),
        "property_type": _missing(r.property_type),
        "bedrooms": _missing(r.beds),
        "status": _missing(r.status),
        "size_sqft": _missing(r.size),
        "price_aed": int(r.sale_amount_aed),
        "price_per_sqft_aed": None if _missing(r.ppsqft) is None else int(r.ppsqft),
    }


def _rental_fields(r) -> dict:
    return {
        "contract_id": r.contract_key,
        "lease_start": str(r.d),
        "lease_end": str(pd.Timestamp(r.lease_end).date()),
        "unit_number": _missing(r.unit_number),
        "building_name": _missing(r.building_name),
        "project_name": _missing(r.project_name),
        "location_name": _missing(r.location),
        "property_type": _missing(r.property_type),
        "bedrooms": _missing(r.beds),
        "size_sqft": _missing(r.size),
        "annual_rent_aed": int(r.annual_rent_aed) or None,
        "contract_amount_aed": int(r.contract_amount_aed) or None,
        "term_months": float(r.contract_term_months) or None,
        "contract_type": _missing(r.contract_state),
    }


def main() -> int:
    token = os.environ.get("VERIFY_API_TOKEN")
    if not token:
        print("Set VERIFY_API_TOKEN to a bearer token of a subscribed user.", file=sys.stderr)
        return 2
    return Verifier(os.environ.get("VERIFY_API_URL", "http://localhost:8000"), token).run()


if __name__ == "__main__":
    sys.exit(main())
