"""Check the Analytics API against the served market tables, independently.

The Analytics pages read the combined DXBI + DLD layer (``ch_transactions`` /
``ch_rent_contracts``). This script reads the last two years of served rows into pandas,
re-implements each endpoint's rules here rather than importing them, and compares the live API
with them:

- /analytics/sales: every period (30-365 days), usage, market type, the busiest communities,
  property types, bedroom counts, registration types, and price and area buckets;
- /analytics/rentals: every period, usage, the busiest communities, property types, and rent and
  area buckets;
- /analytics/market-trend: every period and market type, point by point, with the change on the
  previous period;
- /analytics/project/summary for the whole Dubai market.

Rules re-implemented: a period is every whole day from today minus N days to today; a bucket is a
half-open range ('1M-2M' is 1,000,000 up to, not including, 2,000,000; areas in sq ft); a market
type is a transaction group and uniform property types.

Read-only: one SELECT-only ClickHouse connection and GET requests.

    VERIFY_API_TOKEN=<bearer token> uv run python -m scripts.clickhouse.verify_analytics
"""

from __future__ import annotations

import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

import clickhouse_connect
import pandas as pd

from app.config import settings

SQFT_PER_SQM = 10.7639
PERIODS = (30, 90, 180, 365)
# A market type: its transaction group and the rows it holds.
MARKET_TYPES = {
    "residential_units": (
        "Sales",
        lambda f: (f.property_usage_en == "Residential")
        & f.property_type.isin(["Apartment", "Hotel Apartment"]),
    ),
    "villas": ("Sales", lambda f: f.property_type.isin(["Villa", "Townhouse"])),
    "commercial_units": (
        "Sales",
        lambda f: f.property_usage_en.isin(["Commercial", "Hospitality"])
        & ~f.property_type.isin(["Villa", "Townhouse", "Plot", "Building", ""]),
    ),
    "bulk_building": ("Sales", lambda f: f.property_type == "Building"),
    "land": ("Sales", lambda f: f.property_type == "Plot"),
    "mortgages": ("Mortgages", lambda f: f.property_type == f.property_type),
    "gifts": ("Gifts", lambda f: f.property_type == f.property_type),
}
PRICE_BUCKETS = {
    "<500K": (None, 5e5),
    "500K-1M": (5e5, 1e6),
    "1M-2M": (1e6, 2e6),
    "5M+": (5e6, None),
}
RENT_BUCKETS = {
    "<50K": (None, 5e4),
    "50K-100K": (5e4, 1e5),
    "100K-200K": (1e5, 2e5),
    "200K+": (2e5, None),
}
AREA_BUCKETS = {
    "<500": (None, 500),
    "500-1K": (500, 1000),
    "1K-2K": (1000, 2000),
    "2K+": (2000, None),
}


class Failed(Exception):
    """An API call that did not answer: recorded as a failed check."""


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

    def close(self, label: str, got, want, places: int = 2) -> None:
        """Equal to the API's rounding: counts exactly, amounts to ``places`` decimals."""
        if want is None or (isinstance(want, float) and math.isnan(want)):
            self.check(got in (None, 0, 0.0), f"{label}: API {got}, expected none")
            return
        tolerance = 0 if isinstance(want, int) else 10**-places * 1.01 + abs(want) * 1e-9
        self.check(
            got is not None and abs(float(got) - float(want)) <= tolerance,
            f"{label}: API {got} != {want}",
        )

    def api(self, path: str, **params) -> dict:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        request = urllib.request.Request(
            f"{self.api_url}/{path}?{query}", headers={"Authorization": f"Bearer {self.token}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise Failed(f"{path} {params}: HTTP {error.code}") from error

    # -- served rows -------------------------------------------------------------------------
    def load(self) -> None:
        start = self.today - timedelta(days=2 * max(PERIODS) + 2)
        self.sales = self.ch.query_df(
            "SELECT toDate(instance_date) AS d, trans_group_en, property_usage_en, property_type, "
            "toFloat64(actual_worth) AS price, toFloat64(meter_sale_price) AS per_sqm, "
            "toFloat64(size_sqm) AS sqm, master_project_en, rooms_en, reg_type_en "
            f"FROM ch_transactions WHERE toDate(instance_date) >= '{start}'"
        )
        self.rents = self.ch.query_df(
            "SELECT toDate(contract_start_date) AS d, property_usage_en, property_type, "
            "toFloat64(annual_amount) AS rent, toFloat64(size_sqm) AS sqm, master_project_en "
            "FROM ch_rent_contracts "
            f"WHERE toDate(contract_start_date) >= '{self.today - timedelta(days=max(PERIODS) + 1)}'"
        )
        for frame in (self.sales, self.rents):
            frame["d"] = pd.to_datetime(frame.d).dt.date
        print(f"served rows: {len(self.sales)} sales, {len(self.rents)} leases", flush=True)

    def period(self, frame: pd.DataFrame, days: int, end: date | None = None) -> pd.DataFrame:
        end = end or self.today
        return frame[(frame.d >= end - timedelta(days=days)) & (frame.d <= end)]

    @staticmethod
    def within(values: pd.Series, bounds) -> pd.Series:
        low, high = bounds
        mask = values == values
        if low is not None:
            mask &= values >= low
        if high is not None:
            mask &= values < high
        return mask

    # -- expectations ------------------------------------------------------------------------
    def expected_sales(self, days: int, usage: str = "Residential", **f) -> pd.DataFrame:
        frame = self.period(self.sales, days)
        if f.get("market_type"):  # a market type replaces the usage
            group, holds = MARKET_TYPES[f["market_type"]]
            frame = frame[frame.trans_group_en == group]
            frame = frame[holds(frame)]
        else:
            frame = frame[frame.trans_group_en == "Sales"]
            if usage:
                frame = frame[frame.property_usage_en == usage]
        for column, key in (
            ("master_project_en", "master_project"),
            ("property_type", "property_type"),
            ("rooms_en", "rooms"),
            ("reg_type_en", "reg_type"),
        ):
            if f.get(key):
                frame = frame[frame[column] == f[key]]
        if f.get("price_bucket"):
            frame = frame[self.within(frame.price, PRICE_BUCKETS[f["price_bucket"]])]
        if f.get("area_bucket"):
            frame = frame[self.within(frame.sqm * SQFT_PER_SQM, AREA_BUCKETS[f["area_bucket"]])]
        return frame

    def compare_sales(self, days: int, usage: str = "Residential", **f) -> None:
        frame = self.expected_sales(days, usage, **f)
        label = f"sales {days}d {usage} {f}"
        body = self.api("analytics/sales", timeframe_days=days, property_usage=usage, **f)
        body = body["summary"]
        self.close(f"{label} count", body["transaction_count"], len(frame))
        if frame.empty:
            return
        sized = frame[frame.sqm > 0]
        self.close(f"{label} volume", body["total_volume"], round(frame.price.sum(), 2))
        self.close(f"{label} avg", body["avg_price"], round(frame.price.mean(), 2))
        self.close(f"{label} min", body["min_price"], round(frame.price.min(), 2))
        self.close(f"{label} max", body["max_price"], round(frame.price.max(), 2))
        self.close(
            f"{label} avg/sqft",
            body["avg_price_sqft"],
            round((sized.price / sized.sqm).mean() / SQFT_PER_SQM, 2) if len(sized) else 0.0,
        )

    def compare_rentals(self, days: int, usage: str = "Residential", **f) -> None:
        frame = self.period(self.rents, days)
        frame = frame[frame.property_usage_en == usage]
        for column, key in (
            ("master_project_en", "master_project"),
            ("property_type", "property_type"),
        ):
            if f.get(key):
                frame = frame[frame[column] == f[key]]
        if f.get("rent_bucket"):
            frame = frame[self.within(frame.rent, RENT_BUCKETS[f["rent_bucket"]])]
        if f.get("area_bucket"):
            frame = frame[self.within(frame.sqm * SQFT_PER_SQM, AREA_BUCKETS[f["area_bucket"]])]
        label = f"rentals {days}d {usage} {f}"
        body = self.api("analytics/rentals", timeframe_days=days, property_usage=usage, **f)[
            "summary"
        ]
        self.close(f"{label} count", body["contract_count"], len(frame))
        if frame.empty:
            return
        sized = frame[frame.sqm > 0]
        self.close(f"{label} value", body["total_annual_value"], round(frame.rent.sum(), 2))
        self.close(f"{label} avg", body["avg_annual_rent"], round(frame.rent.mean(), 2))
        self.close(f"{label} min", body["min_annual_rent"], round(frame.rent.min(), 2))
        self.close(f"{label} max", body["max_annual_rent"], round(frame.rent.max(), 2))
        self.close(
            f"{label} avg/sqft",
            body["avg_rent_sqft"],
            round((sized.rent / sized.sqm).mean() / SQFT_PER_SQM, 2) if len(sized) else 0.0,
        )

    def compare_trend(self, days: int, market: str | None = None) -> None:
        def rows(end: date) -> pd.DataFrame:
            frame = self.period(self.sales, days, end)
            if market:
                group, holds = MARKET_TYPES[market]
                frame = frame[frame.trans_group_en == group]
                return frame[holds(frame)]
            frame = frame[frame.trans_group_en == "Sales"]
            return frame[frame.property_usage_en == "Residential"]

        current = rows(self.today)
        previous = rows(self.today - timedelta(days=days + 1))
        if days <= 30:
            current = current.assign(p=current.d)
        elif days <= 180:  # weeks start on Sunday (ClickHouse toStartOfWeek mode 0)
            current = current.assign(
                p=[d - timedelta(days=(d.weekday() + 1) % 7) for d in current.d]
            )
        else:
            current = current.assign(p=[d.replace(day=1) for d in current.d])
        label = f"trend {days}d {market or 'residential'}"
        body = self.api("analytics/market-trend", days=days, market_type=market)
        points = {date.fromisoformat(point["date"]): point for point in body["data"]}
        groups = current.groupby("p")
        self.close(f"{label} points", len(points), groups.ngroups)
        self.close(f"{label} total", body["total_transactions"], len(current))
        for period, group in groups:
            point = points.get(period)
            if point is None:
                self.check(False, f"{label} {period}: missing")
                continue
            self.close(f"{label} {period} count", point["transaction_count"], len(group))
            self.close(f"{label} {period} avg", point["avg_price"], round(group.price.mean(), 2))
            per_sqm = group.per_sqm.dropna()
            self.close(
                f"{label} {period} avg/sqft",
                point["avg_price_sqft"],
                round(per_sqm.mean() / SQFT_PER_SQM, 2) if len(per_sqm) else None,
            )
        if len(current) and len(previous):
            change = round(
                (round(current.price.mean(), 2) - round(previous.price.mean(), 2))
                / round(previous.price.mean(), 2)
                * 100,
                1,
            )
            self.close(f"{label} change", body["avg_price_change_pct"], change, places=1)

    def compare_dubai_summary(self) -> None:
        """The whole market by the project summary's definitions, over all served history."""
        sales = self.ch.query(
            "SELECT count(), avg(actual_worth), medianExact(actual_worth), "
            "medianExactIf(actual_worth, reg_type_en = 'Existing Properties') "
            "FROM ch_transactions WHERE trans_group_en = 'Sales' AND actual_worth > 0 "
            "AND property_usage_en = 'Residential' AND property_type NOT IN ('Plot', 'Building', '')"
        ).result_rows[0]
        rents = self.ch.query(
            "SELECT count(), medianExact(annual_amount), "
            "medianExact(annual_amount / nullIf(actual_area * 10.7639, 0)) "
            "FROM ch_rent_contracts WHERE property_usage_en = 'Residential' AND annual_amount > 0"
        ).result_rows[0]
        body = self.api("analytics/project/summary")  # no project or community: all of Dubai
        self.close("dubai sales count", body["sales"]["transaction_count"], int(sales[0]))
        self.close("dubai avg price", body["sales"]["avg_price"], round(sales[1], 2))
        self.close("dubai median price", body["sales"]["median_price"], round(sales[2], 2))
        self.close("dubai leases", body["rentals"]["contract_count"], int(rents[0]))
        self.close("dubai median rent", body["rentals"]["median_annual_rent"], round(rents[1], 2))
        self.close(
            "dubai median rent/sqft", body["rentals"]["median_rent_sqft"], round(rents[2], 2)
        )
        self.close(
            "dubai yield", body["overall_gross_yield_pct"], round(rents[1] / sales[3] * 100, 2)
        )

    # -- run ---------------------------------------------------------------------------------
    def attempt(self, compare, *args, **kwargs) -> None:
        try:
            compare(*args, **kwargs)
        except Failed as failure:
            self.check(False, str(failure))

    def run(self) -> int:
        self.load()
        year_sales = self.expected_sales(365)
        busiest = year_sales.master_project_en[year_sales.master_project_en != ""]
        communities = busiest.value_counts().index[:5].tolist()
        for days in PERIODS:
            for usage in ("Residential", "Commercial"):
                self.attempt(self.compare_sales, days, usage=usage)
                self.attempt(self.compare_rentals, days, usage=usage)
            for market in MARKET_TYPES:
                self.attempt(self.compare_sales, days, market_type=market)
                self.attempt(self.compare_trend, days, market)
            self.attempt(self.compare_trend, days)
        for community in communities:
            self.attempt(self.compare_sales, 365, master_project=community)
            self.attempt(self.compare_rentals, 365, master_project=community)
        for kind in sorted(v for v in year_sales.property_type.unique() if v):
            self.attempt(self.compare_sales, 365, property_type=kind)
            self.attempt(self.compare_rentals, 365, property_type=kind)
        for rooms in year_sales.rooms_en.value_counts().index[:6]:
            if rooms:
                self.attempt(self.compare_sales, 365, rooms=rooms)
        for reg_type in sorted(v for v in year_sales.reg_type_en.unique() if v):
            self.attempt(self.compare_sales, 365, reg_type=reg_type)
        for bucket in PRICE_BUCKETS:
            self.attempt(self.compare_sales, 365, price_bucket=bucket)
        for bucket in AREA_BUCKETS:
            self.attempt(self.compare_sales, 365, area_bucket=bucket)
            self.attempt(self.compare_rentals, 365, area_bucket=bucket)
        for bucket in RENT_BUCKETS:
            self.attempt(self.compare_rentals, 365, rent_bucket=bucket)
        self.attempt(self.compare_dubai_summary)

        print(f"{self.checks} checks, {len(self.failures)} failed")
        for failure in self.failures[:40]:
            print("  ", failure)
        return 1 if self.failures else 0


def main() -> int:
    token = os.environ.get("VERIFY_API_TOKEN")
    if not token:
        print("set VERIFY_API_TOKEN to a bearer token for the API", file=sys.stderr)
        return 2
    return Verifier(os.environ.get("VERIFY_API_URL", "http://localhost:8000"), token).run()


if __name__ == "__main__":
    raise SystemExit(main())
