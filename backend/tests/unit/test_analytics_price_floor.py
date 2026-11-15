"""Analytics leaves out records whose price is not a market price, on every page alike.

DXBI lists sales of a few hundred to a few thousand AED (1-17 AED/sq ft, 2025-11 to 2026-11)
and from AED 10,000 to 50,000 at a median 41 AED/sq ft, against ~1,700 AED/sq ft for the
market; and leases with an annual rent of AED 0 to 999 (contract amounts of AED 0-3 over 1-10
years). They dragged the minimums to AED 163 and AED 0 and the averages down.
"""

import re

from app.analytics import dxbi


def test_sales_below_the_floor_are_not_analytics_sales():
    assert dxbi.SALE_FLOOR_AED == 50_000
    assert re.search(r"WHERE sale_amount_aed >= 50000\b", dxbi.SALES_SOURCE)


def test_leases_below_the_floor_are_not_analytics_leases():
    assert dxbi.RENT_FLOOR_AED == 1_000
    assert re.search(r"WHERE annual_rent_aed >= 1000 AND lease_end > lease_start\b", dxbi.RENTALS_SOURCE)


def test_every_analytics_query_reads_the_floored_sources():
    from app.analytics import queries

    assert queries.SALES_SOURCE is dxbi.SALES_SOURCE
    assert queries.RENTALS_SOURCE is dxbi.RENTALS_SOURCE
