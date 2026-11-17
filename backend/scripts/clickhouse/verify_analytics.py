"""Check the Analytics API against the DXBI listed tables, independently.

The Analytics pages read Holocron's DXBI-only listed tables (``dxbi_sales_listed`` /
``dxbi_leases_listed``, since 2026-10-14), one row per record the Transactions pages list. This
script reads the last two years of those rows into pandas, re-implements each endpoint's documented
rules here rather than importing the API's queries, and compares the live API with them:

- /analytics/sales: every period (30-365 days), usage, market type, the busiest masters,
  property types, bedroom counts, registration types, and price and area buckets; per period and
  usage also its trend points (and their partial flags), every breakdown and the change on the
  equal period before;
- /analytics/rentals: every period, usage, the busiest masters, property types, and rent and area
  buckets; per period and usage also its trend, breakdowns and changes;
- POST /analytics/market-metrics: count, mean and total per period and usage, equal both to the
  listed rows and to /analytics/sales and /rentals for the same days, with coverage dates that
  are real record dates;
- /analytics/market-trend: every period and market type, point by point, with the change on the
  previous period (average price and median price per sq ft);
- /analytics/project/summary for the whole Dubai market;
- the parts add up: every listed record is Residential, Commercial, land or untyped, so the
  usages, the land market type and the untyped count reconcile with every listed record.

Rules re-implemented from the API's documentation:

- DXBI names a property type but no usage: Residential is Apartment, Villa, Townhouse and Hotel
  Apartment; Commercial is Office, Shop, Show Rooms, Warehouse, Workshop, Clinic, Gymnasium, Hotel,
  Sized Partition, Building and Commercial. A Plot or an untyped record is in neither (a Plot is the
  ``land`` market type).
- A period is every whole day from today minus N days to today, inclusive (the API's own date).
- A bucket is a half-open range ('1M-2M' is 1,000,000 up to, not including, 2,000,000; areas in
  sq ft).
- A market type is a transaction group and property types: residential_units, villas,
  commercial_units, bulk_building and land. Mortgages and gifts are DLD registrations, not DXBI
  records: the API answers 422 to them and this script checks that it does.
- Price floors: a sale under AED 50,000 and a lease under AED 1,000 a year (or ending before it
  starts) is not an Analytics record.
- Trend points: daily up to 30 days, Sunday weeks up to 180, months beyond; a point the period
  cuts is ``partial``. Breakdown groups without a value are "Not recorded"; masters are the 20
  busiest; shares are of the whole period.
- DXBI's own values first, the profile's sourced fill where DXBI left one empty (area, bedrooms,
  status); a master is DLD's, else DXBI's community; 'any spelling of the master' resolves through
  ``analytics_master_keys``.

Read-only: one SELECT-only ClickHouse connection and GET requests. Run it from ``backend`` on the
machine whose date the API uses (the API's "today" is that machine's date):

    VERIFY_API_TOKEN=<bearer token> VERIFY_API_URL=http://localhost:8000 \\
        python -m scripts.clickhouse.verify_analytics
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

import numpy as np
import pandas as pd

SQFT_PER_SQM = 10.7639
PERIODS = (30, 90, 180, 365)
RESIDENTIAL_TYPES = ("Apartment", "Villa", "Townhouse", "Hotel Apartment")
COMMERCIAL_TYPES = (
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
)
# A market type: the rows it holds. Every listed sale is a Sales-group record.
MARKET_TYPES = {
    "residential_units": lambda f: (f.usage == "Residential")
    & f.property_type.isin(["Apartment", "Hotel Apartment"]),
    "villas": lambda f: f.property_type.isin(["Villa", "Townhouse"]),
    "commercial_units": lambda f: f.usage.isin(["Commercial", "Hospitality"])
    & ~f.property_type.isin(["Villa", "Townhouse", "Plot", "Building", ""]),
    "bulk_building": lambda f: f.property_type == "Building",
    "land": lambda f: f.property_type == "Plot",
}
# DLD registrations that were once market types and are not DXBI records.
REJECTED_MARKET_TYPES = ("mortgages", "gifts")
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

# The API's price floors (app.analytics.dxbi, decision 2026-11-15), restated here.
SALE_FLOOR_AED = 50_000
RENT_FLOOR_AED = 1_000
_LEASE_FLOOR = f"annual_rent_aed >= {RENT_FLOOR_AED} AND lease_end > lease_start"
NOT_RECORDED = "Not recorded"
MASTER_BREAKDOWN_LIMIT = 20
_RES = "(" + ", ".join(f"'{kind}'" for kind in RESIDENTIAL_TYPES) + ")"
SALES_SQL = (
    "SELECT transaction_date, property_type, bedrooms, profile_bedrooms, market_status, "
    "profile_status, size_sqft, profile_size, sale_amount_aed, price_per_sqft_aed, "
    "master_key, master_name, area_name FROM dxbi_sales_listed "
    f"WHERE sale_amount_aed >= {SALE_FLOOR_AED} AND transaction_date >= '{{start}}'"
)
LEASES_SQL = (
    "SELECT lease_start, property_type, bedrooms, profile_bedrooms, size_sqft, profile_size, "
    "annual_rent_aed, master_key, master_name, area_name FROM dxbi_leases_listed "
    f"WHERE {_LEASE_FLOOR} AND lease_start >= '{{start}}'"
)
ALIASES_SQL = "SELECT raw_key, master_key FROM analytics_master_keys"
# The whole market, over all listed history: a residential sale priced above zero.
_READY = "(market_status = 'Ready' OR (market_status = '' AND profile_status = 'Ready'))"
DUBAI_SALES_SQL = (
    "SELECT count(), avg(sale_amount_aed), medianExact(sale_amount_aed), "
    f"medianExactIf(sale_amount_aed, {_READY}), "
    "avg(multiIf(price_per_sqft_aed > 0, round(price_per_sqft_aed), size_sqft > 0, "
    "round(sale_amount_aed / size_sqft), NULL)) "
    f"FROM dxbi_sales_listed WHERE property_type IN {_RES} AND sale_amount_aed >= {SALE_FLOOR_AED}"
)
DUBAI_LEASES_SQL = (
    "SELECT count(), sum(annual_rent_aed), medianExact(annual_rent_aed), "
    "medianExact(annual_rent_aed / nullIf(multiIf(size_sqft > 0, size_sqft, profile_size > 0, "
    "profile_size, 0), 0)) "
    f"FROM dxbi_leases_listed WHERE property_type IN {_RES} AND {_LEASE_FLOOR}"
)


class Failed(Exception):
    """An API call that did not answer: recorded as a failed check."""


# -- the rules, as functions of the rows -------------------------------------------------------
def name_key(text: str) -> str:
    """A name's letters and digits, lower case: how the hierarchy matches spellings."""
    return re.sub(r"[^A-Za-z0-9]", "", text or "").lower()


def usage_of(property_type: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [property_type.isin(RESIDENTIAL_TYPES), property_type.isin(COMMERCIAL_TYPES)],
            ["Residential", "Commercial"],
            default="",
        ),
        index=property_type.index,
    )


def ch_round(values: pd.Series) -> pd.Series:
    """ClickHouse ``round``: halves go away from zero (numpy rounds them to even)."""
    return np.sign(values) * np.floor(np.abs(values) + 0.5)


def ch_median(values: pd.Series) -> float | None:
    """ClickHouse ``medianExact``: the n/2-th sorted value, not the mean of the middle two."""
    ordered = np.sort(values.dropna().to_numpy(dtype=float))
    return float(ordered[len(ordered) // 2]) if len(ordered) else None


def _bedroom_label(text: str) -> str:
    if text == "Studio":
        return "Studio"
    found = re.fullmatch(r"([0-9]+) Beds?", text)
    return f"{found.group(1)} B/R" if found else ""


def _rooms(kind: str, usage: str, bedrooms: str, profile_bedrooms: str) -> str:
    """Homes by bedroom count; an office or shop has none, so its type is its configuration."""
    if usage == "Commercial":
        return "Commercial (type not recorded)" if kind == "Commercial" else kind
    return _bedroom_label(bedrooms if bedrooms else profile_bedrooms)


def _area_sqft(size: pd.Series, profile: pd.Series) -> pd.Series:
    """DXBI's own area, else the profile's sourced one."""
    return pd.Series(
        np.select([size > 0, profile > 0], [size, profile], default=np.nan), index=size.index
    )


def _master_key(raw: pd.DataFrame) -> pd.Series:
    """DLD's master; where DLD defines none, DXBI's community."""
    return pd.Series(
        [key or name_key(area) for key, area in zip(raw.master_key, raw.area_name)],
        index=raw.index,
    )


def _dates(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values).dt.date


def derive_sales(raw: pd.DataFrame) -> pd.DataFrame:
    """The listed sales as the Analytics pages value them."""
    price = raw.sale_amount_aed.astype(float)
    ppsf = pd.Series(
        np.select(
            [raw.price_per_sqft_aed > 0, raw.size_sqft > 0],
            [ch_round(raw.price_per_sqft_aed), ch_round(price / raw.size_sqft)],
            default=np.nan,
        ),
        index=raw.index,
    )
    usage = usage_of(raw.property_type)
    status = np.select(
        [
            (raw.market_status == "Offplan")
            | ((raw.market_status == "") & (raw.profile_status == "Off-Plan")),
            (raw.market_status == "Ready")
            | ((raw.market_status == "") & (raw.profile_status == "Ready")),
        ],
        ["Off-Plan Properties", "Existing Properties"],
        default="",
    )
    return pd.DataFrame(
        {
            "d": _dates(raw.transaction_date),
            "property_type": raw.property_type,
            "usage": usage,
            "price": price,
            "sqft": _area_sqft(raw.size_sqft, raw.profile_size),
            "ppsf": ppsf,
            "rooms": [
                _rooms(*row)
                for row in zip(raw.property_type, usage, raw.bedrooms, raw.profile_bedrooms)
            ],
            "reg_type": status,
            "master_key": _master_key(raw),
            "master_name": raw.master_name,
        }
    )


def derive_leases(raw: pd.DataFrame) -> pd.DataFrame:
    """The listed leases as the Analytics pages value them."""
    return pd.DataFrame(
        {
            "d": _dates(raw.lease_start),
            "property_type": raw.property_type,
            "usage": usage_of(raw.property_type),
            "rent": raw.annual_rent_aed.astype(float),
            "sqft": _area_sqft(raw.size_sqft, raw.profile_size),
            "master_key": _master_key(raw),
            "master_name": raw.master_name,
        }
    )


def period_start(day: date, days: int) -> date:
    """The trend point a day falls in: a day, a week from Sunday, or a month."""
    if days <= 30:
        return day
    if days <= 180:
        return day - timedelta(days=(day.weekday() + 1) % 7)
    return day.replace(day=1)


def period_end(start: date, days: int) -> date:
    """The last day of the trend point that starts on ``start``."""
    if days <= 30:
        return start
    if days <= 180:
        return start + timedelta(days=6)
    following = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return following - timedelta(days=1)


def area_sqft_as_stored(sqft: pd.Series) -> pd.Series:
    """The API stores the area in sq m and multiplies back, so a bucket edge sees that float."""
    return (sqft / SQFT_PER_SQM) * SQFT_PER_SQM


class Verifier:
    def __init__(self, api_url: str, token: str, today: date | None = None) -> None:
        self.api_url = api_url.rstrip("/") + "/api/v1"
        self.token = token
        self.today = today or date.today()
        self.checks = 0
        self.failures: list[str] = []
        self.notes: dict[str, int] = {}
        self.aliases: dict[str, list[str]] = {}
        self.sales = pd.DataFrame()
        self.rents = pd.DataFrame()
        self.ch = None

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

    def api_post(self, path: str, **body) -> dict:
        request = urllib.request.Request(
            f"{self.api_url}/{path}",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise Failed(f"POST {path} {body}: HTTP {error.code}") from error

    # -- listed rows -------------------------------------------------------------------------
    def connect(self) -> None:
        import clickhouse_connect

        from app.config import settings

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

    def load(self) -> None:
        self.connect()
        # The trend compares a period with the equal one before it: two years back, plus a day.
        start = self.today - timedelta(days=2 * max(PERIODS) + 2)
        self.sales = derive_sales(self.ch.query_df(SALES_SQL.format(start=start)))
        self.rents = derive_leases(self.ch.query_df(LEASES_SQL.format(start=start)))
        for raw_key, master_key in self.ch.query(ALIASES_SQL).result_rows:
            self.aliases.setdefault(raw_key, []).append(master_key)
        print(f"listed rows: {len(self.sales)} sales, {len(self.rents)} leases", flush=True)

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

    def of_master(self, frame: pd.DataFrame, name: str) -> pd.DataFrame:
        """Records of a master under any spelling the hierarchy resolves to it."""
        key = name_key(name)
        return frame[frame.master_key.isin([key, *self.aliases.get(key, [])])]

    # -- expectations ------------------------------------------------------------------------
    def expected_sales(
        self, days: int, usage: str = "Residential", end: date | None = None, **f
    ) -> pd.DataFrame:
        frame = self.period(self.sales, days, end)
        if f.get("market_type"):  # a market type replaces the usage and property type
            frame = frame[MARKET_TYPES[f["market_type"]](frame)]
        else:
            if usage:
                frame = frame[frame.usage == usage]
            if f.get("property_type"):
                frame = frame[frame.property_type == f["property_type"]]
        if f.get("master_project"):
            frame = self.of_master(frame, f["master_project"])
        for column, key in (("rooms", "rooms"), ("reg_type", "reg_type")):
            if f.get(key):
                frame = frame[frame[column] == f[key]]
        if f.get("price_bucket"):
            frame = frame[self.within(frame.price, PRICE_BUCKETS[f["price_bucket"]])]
        if f.get("area_bucket"):
            frame = frame[
                self.within(area_sqft_as_stored(frame.sqft), AREA_BUCKETS[f["area_bucket"]])
            ]
        return frame

    def expected_leases(
        self, days: int, usage: str = "Residential", end: date | None = None, **f
    ) -> pd.DataFrame:
        frame = self.period(self.rents, days, end)
        frame = frame[frame.usage == usage]
        if f.get("property_type"):
            frame = frame[frame.property_type == f["property_type"]]
        if f.get("master_project"):
            frame = self.of_master(frame, f["master_project"])
        if f.get("rent_bucket"):
            frame = frame[self.within(frame.rent, RENT_BUCKETS[f["rent_bucket"]])]
        if f.get("area_bucket"):
            frame = frame[
                self.within(area_sqft_as_stored(frame.sqft), AREA_BUCKETS[f["area_bucket"]])
            ]
        return frame

    @staticmethod
    def per_sqft(amount: pd.Series, sqft: pd.Series) -> float:
        """The mean amount per sq ft over the records that have an area, 0 when none do."""
        sized = sqft > 0
        return round(float((amount[sized] / sqft[sized]).mean()), 2) if sized.any() else 0.0

    def compare_sales(self, days: int, usage: str = "Residential", **f) -> None:
        frame = self.expected_sales(days, usage, **f)
        label = f"sales {days}d {usage} {f}"
        body = self.api("analytics/sales", timeframe_days=days, property_usage=usage, **f)
        body = body["summary"]
        self.close(f"{label} count", body["transaction_count"], len(frame))
        if frame.empty:
            return
        self.close(f"{label} volume", body["total_volume"], round(frame.price.sum(), 2))
        self.close(f"{label} avg", body["avg_price"], round(frame.price.mean(), 2))
        self.close(f"{label} min", body["min_price"], round(frame.price.min(), 2))
        self.close(f"{label} max", body["max_price"], round(frame.price.max(), 2))
        self.close(
            f"{label} avg/sqft", body["avg_price_sqft"], self.per_sqft(frame.price, frame.sqft)
        )

    def compare_leases(self, days: int, usage: str = "Residential", **f) -> None:
        frame = self.expected_leases(days, usage, **f)
        label = f"rentals {days}d {usage} {f}"
        body = self.api("analytics/rentals", timeframe_days=days, property_usage=usage, **f)
        body = body["summary"]
        self.close(f"{label} count", body["contract_count"], len(frame))
        if frame.empty:
            return
        self.close(f"{label} value", body["total_annual_value"], round(frame.rent.sum(), 2))
        self.close(f"{label} avg", body["avg_annual_rent"], round(frame.rent.mean(), 2))
        self.close(f"{label} min", body["min_annual_rent"], round(frame.rent.min(), 2))
        self.close(f"{label} max", body["max_annual_rent"], round(frame.rent.max(), 2))
        self.close(
            f"{label} avg/sqft", body["avg_rent_sqft"], self.per_sqft(frame.rent, frame.sqft)
        )

    # -- trends, breakdowns and changes ----------------------------------------------------
    def previous_end(self, days: int) -> date:
        """The equal period just before ``days`` up to today ends the day before it starts."""
        return self.today - timedelta(days=days + 1)

    @staticmethod
    def change(now: float, before: float) -> float | None:
        return round((now - before) / before * 100, 1) if before else None

    def compare_trend_points(
        self, label: str, points: list, frame: pd.DataFrame, amount: str, days: int
    ) -> None:
        start = self.today - timedelta(days=days)
        frame = frame.assign(p=[period_start(d, days) for d in frame.d])
        groups = frame.groupby("p")
        got = {date.fromisoformat(point["date"]): point for point in points}
        self.close(f"{label} trend points", len(got), groups.ngroups)
        for period, group in groups:
            point = got.get(period)
            if point is None:
                self.check(False, f"{label} trend {period}: missing")
                continue
            self.close(f"{label} trend {period} count", point["count"], len(group))
            self.close(f"{label} trend {period} value", point["total_value"],
                       round(group[amount].sum(), 2))  # fmt: skip
            self.close(f"{label} trend {period} avg", point["avg_value"],
                       round(group[amount].mean(), 2))  # fmt: skip
            self.close(f"{label} trend {period} avg/sqft", point["avg_sqft"],
                       self.per_sqft(group[amount], group.sqft))  # fmt: skip
            last = period_end(period, days)
            self.check(
                bool(point.get("partial")) == (period < start or last > self.today),
                f"{label} trend {period}: partial {point.get('partial')}",
            )

    def compare_breakdown(
        self,
        label: str,
        rows: list,
        frame: pd.DataFrame,
        column: str,
        amount: str,
        count_field: str,
        total_field: str,
        sqft_field: str,
    ) -> None:
        values = frame[column].replace("", NOT_RECORDED)
        groups = frame.assign(g=values).groupby("g")
        if column == "master_key":
            # The busiest masters only: compare their counts, busiest first.
            want = sorted(groups.size().tolist(), reverse=True)[:MASTER_BREAKDOWN_LIMIT]
            got = [row[count_field] for row in rows]
            self.check(got == want, f"{label} counts {got[:5]}... != {want[:5]}...")
            for row in rows:
                self.close(f"{label} {row['dimension_value']} share", row["pct_of_total"],
                           round(row[count_field] / len(frame) * 100, 1), places=1)  # fmt: skip
            return
        got = {row["dimension_value"]: row for row in rows}
        self.close(f"{label} groups", len(got), groups.ngroups)
        for value, group in groups:
            row = got.get(value)
            if row is None:
                self.check(False, f"{label} {value}: missing")
                continue
            self.close(f"{label} {value} count", row[count_field], len(group))
            self.close(f"{label} {value} total", row[total_field], round(group[amount].sum(), 2))
            self.close(f"{label} {value} avg/sqft", row[sqft_field],
                       self.per_sqft(group[amount], group.sqft))  # fmt: skip
            self.close(f"{label} {value} share", row["pct_of_total"],
                       round(len(group) / len(frame) * 100, 1), places=1)  # fmt: skip

    def compare_sales_breakdowns(self, days: int, usage: str = "Residential", **f) -> None:
        frame = self.expected_sales(days, usage, **f)
        before = self.expected_sales(days, usage, end=self.previous_end(days), **f)
        label = f"sales {days}d {usage} {f}"
        body = self.api("analytics/sales", timeframe_days=days, property_usage=usage, **f)
        if frame.empty:
            self.check(body["trends"] == [], f"{label}: trend without sales")
            return
        self.compare_trend_points(label, body["trends"], frame, "price", days)
        for name, column in (("property_type", "property_type"), ("rooms", "rooms"),
                             ("reg_type", "reg_type"), ("master_project", "master_key")):  # fmt: skip
            self.compare_breakdown(f"{label} by_{name}", body[f"by_{name}"], frame, column,
                                   "price", "transaction_count", "total_volume",
                                   "avg_price_sqft")  # fmt: skip
        summary = body["summary"]
        self.close(f"{label} count change", summary["count_change_pct"],
                   self.change(len(frame), len(before)), places=1)  # fmt: skip
        self.close(f"{label} volume change", summary["volume_change_pct"],
                   self.change(frame.price.sum(), before.price.sum()), places=1)  # fmt: skip

    def compare_leases_breakdowns(self, days: int, usage: str = "Residential", **f) -> None:
        frame = self.expected_leases(days, usage, **f)
        before = self.expected_leases(days, usage, end=self.previous_end(days), **f)
        label = f"rentals {days}d {usage} {f}"
        body = self.api("analytics/rentals", timeframe_days=days, property_usage=usage, **f)
        if frame.empty:
            self.check(body["trends"] == [], f"{label}: trend without leases")
            return
        self.compare_trend_points(label, body["trends"], frame, "rent", days)
        for name, column in (("property_type", "property_type"), ("master_project", "master_key")):
            self.compare_breakdown(f"{label} by_{name}", body[f"by_{name}"], frame, column,
                                   "rent", "contract_count", "total_annual_value",
                                   "avg_rent_sqft")  # fmt: skip
        summary = body["summary"]
        self.close(f"{label} count change", summary["count_change_pct"],
                   self.change(len(frame), len(before)), places=1)  # fmt: skip
        self.close(f"{label} value change", summary["value_change_pct"],
                   self.change(frame.rent.sum(), before.rent.sum()), places=1)  # fmt: skip

    def compare_market_metrics(self, dataset: str, days: int, usage: str = "Residential") -> None:
        """market-metrics counts the rows /sales and /rentals count, over the same days."""
        start, end = self.today - timedelta(days=days), self.today
        frame = (
            self.expected_sales(days, usage) if dataset == "sales"
            else self.expected_leases(days, usage)
        )  # fmt: skip
        amount = frame.price if dataset == "sales" else frame.rent
        label = f"market-metrics {dataset} {days}d {usage}"
        body = self.api_post(
            "analytics/market-metrics",
            dataset=dataset,
            usage=usage.lower(),
            metrics=["mean_aed", "total_aed"],
            period={"type": "range", "start": start.isoformat(), "end": end.isoformat()},
            reference_date=self.today.isoformat(),
        )
        total = body["total"]
        self.close(f"{label} count", total["count"], len(frame))
        if not frame.empty:
            self.close(f"{label} mean", total["values"]["mean_aed"], round(amount.mean(), 2))
            self.close(f"{label} total", total["values"]["total_aed"], round(amount.sum(), 2))
        page = (
            self.api("analytics/sales", timeframe_days=days, property_usage=usage)["summary"]
            if dataset == "sales"
            else self.api("analytics/rentals", timeframe_days=days, property_usage=usage)["summary"]
        )
        page_count = page["transaction_count"] if dataset == "sales" else page["contract_count"]
        self.close(f"{label} count = page count", total["count"], page_count)
        coverage = body["coverage"]
        self.check(
            coverage.get("data_from") is None or coverage["data_from"] >= "2000-01-01",
            f"{label}: coverage starts {coverage.get('data_from')}",
        )
        self.check(
            str(body.get("release_id") or "").startswith("dxbi-"),
            f"{label}: release {body.get('release_id')} is not the DXBI listed build",
        )

    def reconcile_sales(self, days: int) -> None:
        """Every listed sale is Residential, Commercial, land or untyped: nothing else."""
        listed = self.period(self.sales, days)
        untyped = int((listed.property_type == "").sum())
        self.notes[f"sales {days}d without a type"] = untyped
        parts = {
            "Residential": self.api(
                "analytics/sales", timeframe_days=days, property_usage="Residential"
            ),
            "Commercial": self.api(
                "analytics/sales", timeframe_days=days, property_usage="Commercial"
            ),
            "land": self.api("analytics/sales", timeframe_days=days, market_type="land"),
        }
        counted = sum(body["summary"]["transaction_count"] for body in parts.values())
        self.check(
            counted + untyped == len(listed),
            f"sales {days}d: Residential + Commercial + land + untyped = {counted} + {untyped}"
            f" != {len(listed)} listed",
        )

    def reconcile_leases(self, days: int) -> None:
        """Every listed lease is Residential, Commercial or untyped: nothing else."""
        listed = self.period(self.rents, days)
        untyped = int((listed.property_type == "").sum())
        self.notes[f"leases {days}d without a type"] = untyped
        counted = sum(
            self.api("analytics/rentals", timeframe_days=days, property_usage=usage)["summary"][
                "contract_count"
            ]
            for usage in ("Residential", "Commercial")
        )
        self.check(
            counted + untyped == len(listed),
            f"leases {days}d: Residential + Commercial + untyped = {counted} + {untyped}"
            f" != {len(listed)} listed",
        )

    def check_rejected_market_types(self) -> None:
        for market in REJECTED_MARKET_TYPES:
            try:
                self.api("analytics/sales", timeframe_days=30, market_type=market)
            except Failed as failure:
                self.check("HTTP 422" in str(failure), f"market_type={market}: {failure}")
            else:
                self.check(False, f"market_type={market}: API answered; expected 422")

    def compare_trend(self, days: int, market: str | None = None) -> None:
        def rows(end: date) -> pd.DataFrame:
            frame = self.period(self.sales, days, end)
            return (
                frame[MARKET_TYPES[market](frame)]
                if market
                else frame[frame.usage == "Residential"]
            )

        current = rows(self.today)
        previous = rows(self.today - timedelta(days=days + 1))
        current = current.assign(p=[period_start(d, days) for d in current.d])
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
            ppsf = group.ppsf.dropna()
            self.close(
                f"{label} {period} avg/sqft",
                point["avg_price_sqft"],
                round(ppsf.mean(), 2) if len(ppsf) else None,
            )

        def change(now: float | None, before: float | None) -> float | None:
            if now is None or not before:
                return None
            return round((now - before) / before * 100, 1)

        def average(frame: pd.DataFrame) -> float | None:
            return round(frame.price.mean(), 2) if len(frame) else None

        def median_sqft(frame: pd.DataFrame) -> float | None:
            middle = ch_median(frame.ppsf)
            return round(middle, 2) if middle is not None else None

        self.close(
            f"{label} change",
            body["avg_price_change_pct"],
            change(average(current), average(previous)),
            places=1,
        )
        self.close(
            f"{label} change/sqft",
            body["avg_price_sqft_change_pct"],
            change(median_sqft(current), median_sqft(previous)),
            places=1,
        )

    def compare_dubai_summary(self) -> None:
        """The whole market by the project summary's definitions, over all listed history."""
        sales = self.ch.query(DUBAI_SALES_SQL).result_rows[0]
        leases = self.ch.query(DUBAI_LEASES_SQL).result_rows[0]
        body = self.api("analytics/project/summary")  # no project or master: all of Dubai
        self.close("dubai sales count", body["sales"]["transaction_count"], int(sales[0]))
        self.close("dubai avg price", body["sales"]["avg_price"], round(sales[1], 2))
        self.close("dubai median price", body["sales"]["median_price"], round(sales[2], 2))
        self.close("dubai avg/sqft", body["sales"]["avg_price_sqft"], round(sales[4], 2))
        self.close("dubai leases", body["rentals"]["contract_count"], int(leases[0]))
        self.close("dubai lease value", body["rentals"]["total_annual_value"], round(leases[1], 2))
        self.close("dubai median rent", body["rentals"]["median_annual_rent"], round(leases[2], 2))
        self.close(
            "dubai median rent/sqft", body["rentals"]["median_rent_sqft"], round(leases[3], 2)
        )
        self.close(
            "dubai yield", body["overall_gross_yield_pct"], round(leases[2] / sales[3] * 100, 2)
        )

    # -- run ---------------------------------------------------------------------------------
    def attempt(self, compare, *args, **kwargs) -> None:
        try:
            compare(*args, **kwargs)
        except Failed as failure:
            self.check(False, str(failure))

    def run(self) -> int:
        self.load()
        year = self.expected_sales(365)
        named = year[year.master_name != ""]
        masters = named.master_name.value_counts().index[:5].tolist()
        self.attempt(self.check_rejected_market_types)
        for days in PERIODS:
            for usage in ("Residential", "Commercial"):
                self.attempt(self.compare_sales, days, usage=usage)
                self.attempt(self.compare_leases, days, usage=usage)
                self.attempt(self.compare_sales_breakdowns, days, usage=usage)
                self.attempt(self.compare_leases_breakdowns, days, usage=usage)
                self.attempt(self.compare_market_metrics, "sales", days, usage)
                self.attempt(self.compare_market_metrics, "rentals", days, usage)
            self.attempt(self.reconcile_sales, days)
            self.attempt(self.reconcile_leases, days)
            for market in MARKET_TYPES:
                self.attempt(self.compare_sales, days, market_type=market)
                self.attempt(self.compare_trend, days, market)
            self.attempt(self.compare_trend, days)
        for master in masters:
            self.attempt(self.compare_sales, 365, master_project=master)
            self.attempt(self.compare_leases, 365, master_project=master)
            self.attempt(self.compare_sales_breakdowns, 365, master_project=master)
            self.attempt(self.compare_leases_breakdowns, 365, master_project=master)
        for kind in sorted(v for v in year.property_type.unique() if v):
            self.attempt(self.compare_sales, 365, property_type=kind)
            self.attempt(self.compare_leases, 365, property_type=kind)
        for rooms in year.rooms.value_counts().index[:6]:
            if rooms:
                self.attempt(self.compare_sales, 365, rooms=rooms)
        for reg_type in sorted(v for v in year.reg_type.unique() if v):
            self.attempt(self.compare_sales, 365, reg_type=reg_type)
        for bucket in PRICE_BUCKETS:
            self.attempt(self.compare_sales, 365, price_bucket=bucket)
        for bucket in AREA_BUCKETS:
            self.attempt(self.compare_sales, 365, area_bucket=bucket)
            self.attempt(self.compare_leases, 365, area_bucket=bucket)
        for bucket in RENT_BUCKETS:
            self.attempt(self.compare_leases, 365, rent_bucket=bucket)
        self.attempt(self.compare_dubai_summary)

        print(f"{self.checks} checks, {len(self.failures)} failed")
        for name, count in self.notes.items():
            print(f"  note: {name}: {count}")
        for failure in self.failures[:60]:
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
