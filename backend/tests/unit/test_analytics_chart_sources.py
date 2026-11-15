"""Chat's charts and market tools read the Analytics records, in their vocabulary.

They read the combined DXBI + DLD layer and asked for DLD's property types ("Unit" sales,
"Flat" leases), which DXBI's records do not use: the area yield chart answered no rows.
"""

import inspect

from app.analytics import chart_queries, dxbi, queries
from app.analytics.metrics import _rental_property_type, _sales_property_type


def test_apartments_are_dxbi_apartments_for_sales_and_leases():
    for word in ("Flat", "apartment", "unit"):
        assert _sales_property_type(word) == "Apartment"
        assert _rental_property_type(word) == "Apartment"
    assert _sales_property_type("villas") == _rental_property_type("Villa") == "Villa"


def test_chart_and_market_tool_sql_reads_no_combined_layer_table():
    source = inspect.getsource(chart_queries)
    assert "ch_transactions" not in source and "ch_rent_contracts" not in source
    for name in ("GET_MARKET_PULSE_SQL", "RANK_AREAS_VOLUME_SQL", "RANK_AREAS_GROWTH_SQL"):
        statement = getattr(queries, name)
        assert "ch_transactions" not in statement and dxbi.SALES_SOURCE in statement
