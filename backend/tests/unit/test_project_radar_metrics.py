from app.project import service as project_service


def test_radar_yield_uses_existing_sale_median_denominator():
    row = {
        "yield_existing_sale_count": 12,
        "yield_rental_contract_count": 18,
        "yield_existing_median_sale_price": 1_000_000,
        "yield_median_annual_rent": 75_000,
    }

    assert project_service._radar_gross_yield_pct(row) == 7.5


def test_radar_yield_blanks_implausible_or_thin_samples():
    assert (
        project_service._radar_gross_yield_pct(
            {
                "yield_existing_sale_count": 50,
                "yield_rental_contract_count": 50,
                "yield_existing_median_sale_price": 200_000,
                "yield_median_annual_rent": 100_000,
            }
        )
        is None
    )
    assert (
        project_service._radar_gross_yield_pct(
            {
                "yield_existing_sale_count": 4,
                "yield_rental_contract_count": 50,
                "yield_existing_median_sale_price": 1_000_000,
                "yield_median_annual_rent": 80_000,
            }
        )
        is None
    )


def test_radar_developer_display_prefers_english_and_drops_unmapped_arabic():
    lookup = project_service._developer_lookup(
        [
            {
                "developer_name_ar": "شركة نخيل (ش.م.خ)",
                "developer_name_en": "Nakheel",
            }
        ]
    )

    assert project_service._developer_display_name("شركة نخيل (ش.م.خ)", lookup) == "Nakheel"
    assert project_service._developer_display_name("Meraas", lookup) == "Meraas"
    assert project_service._developer_display_name("مطور غير معروف", lookup) is None
    assert project_service._developer_display_list(
        ["شركة نخيل (ش.م.خ)", "Nakheel", "مطور غير معروف", "Meraas"],
        lookup,
    ) == ["Nakheel", "Meraas"]
