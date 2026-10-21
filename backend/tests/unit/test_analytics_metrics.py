from app.analytics.metrics import _sampled_count_pct_change, build_configuration_rows


def test_low_sample_counts_remain_visible_and_yield_uses_median():
    stock = {"Studio": {"unit_count": 10}, "1 B/R": {"unit_count": 200}}
    rent = {"1 B/R": {"median_annual_rent": 60000, "rental_count": 4}}
    sales = [
        {"rooms_en": "Studio", "sales_last_12m": 2, "sale_count": 2},
        {
            "rooms_en": "1 B/R",
            "sales_last_12m": 3,
            "sale_count": 3,
            "median_sale_price": 1000000,
            "avg_sale_price": 2000000,
        },
    ]
    rows = build_configuration_rows("all", sales, stock, rent)
    assert len(rows) == 2
    assert rows[0].rooms == "Studio"
    assert rows[0].sale_count == 2
    assert rows[0].price_change_yoy_pct is None
    assert rows[0].sales_momentum_pct is None
    assert rows[1].rooms == "1 B/R"
    assert rows[1].gross_yield_pct == 6.0
    off_plan = build_configuration_rows("off_plan", sales, stock, rent)[0]
    assert off_plan.gross_yield_pct is None
    assert off_plan.rental_count == 0


def test_momentum_requires_twenty_in_both_periods_and_uses_mean_denominator():
    assert _sampled_count_pct_change(40, 19) is None
    assert _sampled_count_pct_change(19, 40) is None
    assert _sampled_count_pct_change(40, 20) == 66.7
