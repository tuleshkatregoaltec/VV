"""Filter builder for constructing WHERE clauses."""

from datetime import datetime, timedelta
from typing import List, Any, Optional
from sqlmodel import Column, col

from backend.app.db.models import Transaction, RentContract


class FilterBuilder:
    """Builder for constructing database filter WHERE clauses."""

    @staticmethod
    def _normalize_datetime(days: int) -> datetime:
        """Normalize datetime to start of day for better cache consistency."""
        return datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=days)

    @staticmethod
    def build_sales_filters(
        base_where: List[Any],
        trans_group: Optional[str] = None,
        property_usage: Optional[str] = None,
        master_project: Optional[str] = None,
        timeframe_days: Optional[int] = None,
        project: Optional[str] = None,
        building: Optional[str] = None,
        property_type: Optional[str] = None,
        rooms: Optional[str] = None,
        property_sub_type: Optional[str] = None,
        registration_type: Optional[str] = None,
        area_min: Optional[float] = None,
        area_max: Optional[float] = None,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        price_sqft_min: Optional[float] = None,
        price_sqft_max: Optional[float] = None,
    ) -> List[Any]:
        """Build WHERE clauses for sales transaction filters."""

        # Exact match filters (excluding master_project)
        exact_filters = {
            trans_group: Transaction.trans_group_en,
            property_usage: Transaction.property_usage_en,
            project: Transaction.project_name_en,
            building: Transaction.building_name_en,
            property_type: Transaction.property_type_en,
            rooms: Transaction.rooms_en,
            property_sub_type: Transaction.property_sub_type_en,
            registration_type: Transaction.reg_type_en,
        }

        for value, column in exact_filters.items():
            if value is not None:
                base_where.append(column == value)  # type: ignore[arg-type]

        # Master project filter - uses ILIKE for flexible matching
        if master_project is not None:
            base_where.append(
                col(Transaction.master_project_en).ilike(f"%{master_project}%")  # type: ignore[arg-type]
            )

        # Timeframe filter
        if timeframe_days is not None:
            cutoff_date = FilterBuilder._normalize_datetime(timeframe_days)
            base_where.append(Transaction.instance_date >= cutoff_date)  # type: ignore[arg-type]

        # Range filters
        if area_min is not None:
            base_where.append(Transaction.procedure_area >= area_min)  # type: ignore[arg-type]
        if area_max is not None:
            base_where.append(Transaction.procedure_area <= area_max)  # type: ignore[arg-type]
        if price_min is not None:
            base_where.append(Transaction.actual_worth >= price_min)  # type: ignore[arg-type]
        if price_max is not None:
            base_where.append(Transaction.actual_worth <= price_max)  # type: ignore[arg-type]
        if price_sqft_min is not None:
            base_where.append(Transaction.meter_sale_price >= price_sqft_min)  # type: ignore[arg-type]
        if price_sqft_max is not None:
            base_where.append(Transaction.meter_sale_price <= price_sqft_max)  # type: ignore[arg-type]

        return base_where

    @staticmethod
    def build_rental_filters(
        base_where: List[Any],
        property_usage: Optional[str] = None,
        master_project: Optional[str] = None,
        timeframe_days: Optional[int] = None,
        project: Optional[str] = None,
        property_type: Optional[str] = None,
        property_sub_type: Optional[str] = None,
        tenant_type: Optional[str] = None,
        contract_reg_type: Optional[str] = None,
        area_min: Optional[float] = None,
        area_max: Optional[float] = None,
        rent_min: Optional[float] = None,
        rent_max: Optional[float] = None,
    ) -> List[Any]:
        """Build WHERE clauses for rental contract filters."""

        # Exact match filters (excluding master_project)
        exact_filters = {
            property_usage: RentContract.property_usage_en,
            project: RentContract.project_name_en,
            property_type: RentContract.ejari_property_type_en,
            property_sub_type: RentContract.ejari_property_sub_type_en,
            tenant_type: RentContract.tenant_type_en,
            contract_reg_type: RentContract.contract_reg_type_en,
        }

        for value, column in exact_filters.items():
            if value is not None:
                base_where.append(column == value)  # type: ignore[arg-type]

        # Master project filter - uses ILIKE for flexible matching
        if master_project is not None:
            base_where.append(
                col(RentContract.master_project_en).ilike(f"%{master_project}%")  # type: ignore[arg-type]
            )

        # Timeframe filter
        if timeframe_days is not None:
            cutoff_date = FilterBuilder._normalize_datetime(timeframe_days)
            base_where.append(RentContract.contract_start_date >= cutoff_date)  # type: ignore[arg-type]

        # Range filters
        if area_min is not None:
            base_where.append(RentContract.actual_area >= area_min)  # type: ignore[arg-type]
        if area_max is not None:
            base_where.append(RentContract.actual_area <= area_max)  # type: ignore[arg-type]
        if rent_min is not None:
            base_where.append(RentContract.annual_amount >= rent_min)  # type: ignore[arg-type]
        if rent_max is not None:
            base_where.append(RentContract.annual_amount <= rent_max)  # type: ignore[arg-type]

        return base_where
