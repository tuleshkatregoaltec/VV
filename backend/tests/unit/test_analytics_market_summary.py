"""The Dubai market view summarises the whole market by a project summary's own definitions."""

from app.analytics import queries, service


async def test_dubai_market_medians_are_the_markets_not_a_median_of_project_medians(monkeypatch):
    """The view used to take the median of about 3,000 projects' medians, most of them 0, so it
    showed a median price and rent of 0. It now reads the served rows over the whole market."""
    seen: list[tuple] = []

    async def sales_summary(parameters, filter_type="project", reg_type=None):
        seen.append(("sales", filter_type, reg_type))
        median = 1_200_000 if reg_type == "Existing Properties" else 1_275_000
        return [{"transaction_count": 1_180_042, "total_volume": 2.37e12, "avg_price": 2_009_169,
                 "avg_price_sqft": 1_445.67, "median_price": median}]  # fmt: skip

    async def rentals_summary(parameters, filter_type="project"):
        seen.append(("rentals", filter_type, None))
        return [{"contract_count": 7_365_273, "total_annual_value": 5.23e11,
                 "median_annual_rent": 51_000, "median_rent_sqft": 61.94}]  # fmt: skip

    async def unit_count(parameters):
        return [{"unit_count": 863_462}]

    monkeypatch.setattr(queries, "fetch_project_sales_summary", sales_summary)
    monkeypatch.setattr(queries, "fetch_project_rentals_summary", rentals_summary)
    monkeypatch.setattr(queries, "fetch_get_market_summary_rows", unit_count)

    response = await service.get_project_summary("Dubai market", filter_type="market")

    assert {scope for _, scope, _ in seen} == {"market"}
    assert (response.sales.median_price, response.rentals.median_annual_rent) == (1_275_000, 51_000)
    assert response.sales.transaction_count == 1_180_042
    assert response.rentals.median_rent_sqft == 61.94
    # As for a project: median rent over the median price of existing (not off-plan) homes.
    assert response.overall_gross_yield_pct == 4.25
    assert response.project.no_of_units == 863_462
