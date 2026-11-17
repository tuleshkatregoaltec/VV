"""Land-sale evidence and the DDA plot valuation read DXBI's current plot sales.

They read DLD's register through ch_transactions, which holds no DLD plot sale after
2026-10-14 (DXBI's plot sales there carry no DLD procedure, so the procedure filter dropped
them): the evidence stopped a month before the pilot's questions.
"""

from app.analytics import dxbi
from app.plots import queries


def _capture(monkeypatch):
    seen: list[tuple[str, dict]] = []

    async def fake_query(sql, params):
        seen.append((sql, params))
        return []

    monkeypatch.setattr(queries, "query", fake_query)
    return seen


async def test_land_sale_evidence_reads_dxbi_plot_sales(monkeypatch):
    seen = _capture(monkeypatch)

    rows = await queries.fetch_land_sale_evidence(
        area_name="Al Barsha South Fourth", days=365, limit=10, plot_area_sqm=1000, usage=None
    )

    assert rows == []
    sql, params = seen[0]
    assert dxbi.SALES_SOURCE in sql and "ch_transactions" not in sql
    assert "property_type = 'Plot'" in sql
    # DLD's area (the profile's) or DXBI's community name the plot's community.
    assert "lower(area_name_en) = lower({area_name:String})" in sql
    assert "lower(location_name) = lower({area_name:String})" in sql
    assert (params["min_area"], params["max_area"]) == (500.0, 1750.0)


async def test_dda_valuation_reads_dxbi_plot_sales_without_dld_procedures(monkeypatch):
    seen = _capture(monkeypatch)

    await queries._dda_land_transaction_rows({"al barsha south fourth"})

    sql, params = seen[0]
    assert dxbi.SALES_SOURCE in sql and "ch_transactions" not in sql
    assert "procedure_name_en IN" not in sql and "procedures" not in params
