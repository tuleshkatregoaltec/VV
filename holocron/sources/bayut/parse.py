"""Bayut transaction parsing helpers kept local to the source package."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class SaleTransactionRow:
    release_id: str
    scraped_at: str
    window_start_date: str
    window_end_date: str
    purpose: str
    page: int
    transaction_hash_id: str
    transaction_date: str
    transaction_amount: str
    transaction_per_sqm_amount: str
    builtup_area_sqm: str
    plot_area_sqm: str
    balcony_area_sqm: str
    beds: str
    floor: str
    latitude: str
    longitude: str
    bayut_latitude: str
    bayut_longitude: str
    bayut_property_type_id: str
    bayut_leaf_location_id: str
    bayut_leaf_location_name_en: str
    bayut_leaf_location_name_ar: str
    bayut_location_l3_name_en: str
    bayut_location_l3_name_ar: str
    bayut_location_l4_name_en: str
    bayut_location_l4_name_ar: str
    bayut_location_l5_name_en: str
    bayut_location_l5_name_ar: str
    bayut_location_l6_name_en: str
    bayut_location_l6_name_ar: str
    occupancy_status_name: str
    claimed_transaction_status: str
    property_completion_status_sk: str
    sale_market_name: str
    seller_type: str
    transaction_payment_method: str
    unit_number: str
    has_kpi_value: int
    previous_sale_transaction_date: str


@dataclass(frozen=True)
class RentalTransactionRow:
    release_id: str
    scraped_at: str
    window_start_date: str
    window_end_date: str
    purpose: str
    page: int
    transaction_hash_id: str
    transaction_date: str
    contract_start_date: str
    contract_end_date: str
    transaction_amount: str
    contract_monthly_amount: str
    transaction_per_sqm_amount: str
    builtup_area_sqm: str
    plot_area_sqm: str
    balcony_area_sqm: str
    beds: str
    floor: str
    latitude: str
    longitude: str
    bayut_latitude: str
    bayut_longitude: str
    bayut_property_type_id: str
    bayut_leaf_location_id: str
    bayut_leaf_location_name_en: str
    bayut_leaf_location_name_ar: str
    bayut_location_l3_name_en: str
    bayut_location_l3_name_ar: str
    bayut_location_l4_name_en: str
    bayut_location_l4_name_ar: str
    bayut_location_l5_name_en: str
    bayut_location_l5_name_ar: str
    bayut_location_l6_name_en: str
    bayut_location_l6_name_ar: str
    occupancy_status_name: str
    claimed_transaction_status: str
    property_completion_status_sk: str
    rent_contract_duration_months: str
    rent_contract_renewal_status_name: str
    has_kpi_value: int
    previous_sale_transaction_date: str


def parse_date(raw: str) -> date:
    return date.fromisoformat(raw)


def format_bayut_range(start_date: date, end_date: date) -> str:
    return f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"


def string(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def bool_int(value: Any) -> int:
    return 1 if bool(value) else 0


def sale_row(
    *,
    release_id: str,
    scraped_at: str,
    start_date: date,
    end_date: date,
    page: int,
    hit: dict[str, Any],
) -> SaleTransactionRow:
    return SaleTransactionRow(
        release_id=release_id,
        scraped_at=scraped_at,
        window_start_date=start_date.isoformat(),
        window_end_date=end_date.isoformat(),
        purpose="for-sale",
        page=page,
        transaction_hash_id=string(hit.get("transaction_hash_id")),
        transaction_date=string(hit.get("date_transaction_nk")),
        transaction_amount=string(hit.get("transaction_amount")),
        transaction_per_sqm_amount=string(hit.get("transaction_per_sqm_amount")),
        builtup_area_sqm=string(hit.get("builtup_area_sqm")),
        plot_area_sqm=string(hit.get("plot_area_sqm")),
        balcony_area_sqm=string(hit.get("balcony_area_sqm")),
        beds=string(hit.get("beds")),
        floor=string(hit.get("floor")),
        latitude=string(hit.get("latitude")),
        longitude=string(hit.get("longitude")),
        bayut_latitude=string(hit.get("bayut_latitude")),
        bayut_longitude=string(hit.get("bayut_longitude")),
        bayut_property_type_id=string(hit.get("bayut_property_type_id")),
        bayut_leaf_location_id=string(hit.get("bayut_leaf_location_id")),
        bayut_leaf_location_name_en=string(hit.get("bayut_leaf_location_name_en")),
        bayut_leaf_location_name_ar=string(hit.get("bayut_leaf_location_name_ar")),
        bayut_location_l3_name_en=string(hit.get("bayut_location_l3_name_en")),
        bayut_location_l3_name_ar=string(hit.get("bayut_location_l3_name_ar")),
        bayut_location_l4_name_en=string(hit.get("bayut_location_l4_name_en")),
        bayut_location_l4_name_ar=string(hit.get("bayut_location_l4_name_ar")),
        bayut_location_l5_name_en=string(hit.get("bayut_location_l5_name_en")),
        bayut_location_l5_name_ar=string(hit.get("bayut_location_l5_name_ar")),
        bayut_location_l6_name_en=string(hit.get("bayut_location_l6_name_en")),
        bayut_location_l6_name_ar=string(hit.get("bayut_location_l6_name_ar")),
        occupancy_status_name=string(hit.get("occupancy_status_name")),
        claimed_transaction_status=string(hit.get("claimed_transaction_status")),
        property_completion_status_sk=string(hit.get("property_completion_status_sk")),
        sale_market_name=string(hit.get("sale_market_name")),
        seller_type=string(hit.get("seller_type")),
        transaction_payment_method=string(hit.get("transaction_payment_method")),
        unit_number=string(hit.get("unit_number")),
        has_kpi_value=bool_int(hit.get("has_kpi_value")),
        previous_sale_transaction_date=string(hit.get("date_previous_sale_transaction_nk")),
    )


def rental_row(
    *,
    release_id: str,
    scraped_at: str,
    start_date: date,
    end_date: date,
    page: int,
    hit: dict[str, Any],
) -> RentalTransactionRow:
    return RentalTransactionRow(
        release_id=release_id,
        scraped_at=scraped_at,
        window_start_date=start_date.isoformat(),
        window_end_date=end_date.isoformat(),
        purpose="for-rent",
        page=page,
        transaction_hash_id=string(hit.get("transaction_hash_id")),
        transaction_date=string(hit.get("date_transaction_nk")),
        contract_start_date=string(hit.get("date_start_nk")),
        contract_end_date=string(hit.get("date_end_nk")),
        transaction_amount=string(hit.get("transaction_amount")),
        contract_monthly_amount=string(hit.get("contract_monthly_amount")),
        transaction_per_sqm_amount=string(hit.get("transaction_per_sqm_amount")),
        builtup_area_sqm=string(hit.get("builtup_area_sqm")),
        plot_area_sqm=string(hit.get("plot_area_sqm")),
        balcony_area_sqm=string(hit.get("balcony_area_sqm")),
        beds=string(hit.get("beds")),
        floor=string(hit.get("floor")),
        latitude=string(hit.get("latitude")),
        longitude=string(hit.get("longitude")),
        bayut_latitude=string(hit.get("bayut_latitude")),
        bayut_longitude=string(hit.get("bayut_longitude")),
        bayut_property_type_id=string(hit.get("bayut_property_type_id")),
        bayut_leaf_location_id=string(hit.get("bayut_leaf_location_id")),
        bayut_leaf_location_name_en=string(hit.get("bayut_leaf_location_name_en")),
        bayut_leaf_location_name_ar=string(hit.get("bayut_leaf_location_name_ar")),
        bayut_location_l3_name_en=string(hit.get("bayut_location_l3_name_en")),
        bayut_location_l3_name_ar=string(hit.get("bayut_location_l3_name_ar")),
        bayut_location_l4_name_en=string(hit.get("bayut_location_l4_name_en")),
        bayut_location_l4_name_ar=string(hit.get("bayut_location_l4_name_ar")),
        bayut_location_l5_name_en=string(hit.get("bayut_location_l5_name_en")),
        bayut_location_l5_name_ar=string(hit.get("bayut_location_l5_name_ar")),
        bayut_location_l6_name_en=string(hit.get("bayut_location_l6_name_en")),
        bayut_location_l6_name_ar=string(hit.get("bayut_location_l6_name_ar")),
        occupancy_status_name=string(hit.get("occupancy_status_name")),
        claimed_transaction_status=string(hit.get("claimed_transaction_status")),
        property_completion_status_sk=string(hit.get("property_completion_status_sk")),
        rent_contract_duration_months=string(hit.get("rent_contract_duration_months")),
        rent_contract_renewal_status_name=string(hit.get("rent_contract_renewal_status_name")),
        has_kpi_value=bool_int(hit.get("has_kpi_value")),
        previous_sale_transaction_date=string(hit.get("date_previous_sale_transaction_nk")),
    )

