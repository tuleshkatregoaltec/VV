import logging
from typing import Optional

from app.transaction import queries
from app.transaction.models import (
    RentalContractListResponse,
    RentalContractResponse,
    RentalFilters,
    SalesFilters,
    TransactionListResponse,
    TransactionResponse,
)

logger = logging.getLogger(__name__)


# How the Transactions pages show DXBI's labels, for domains that show the same records
# (Analytics): usage from the property type, one bedrooms label per count, and DXBI's commonest
# spelling of a place (LOCATION_SQL needs the LOCATION_SPELLING_SQL WITH clause).
USAGE_SQL = queries._USAGE
BEDROOMS_SQL = queries._BEDROOMS
LOCATION_SPELLING_SQL = queries._LOCATION_SPELLING
LOCATION_SQL = queries._LOCATION


def normalized_sales_source_sql() -> str:
    """Public DXBI sales projection for domain consumers sharing transaction identities."""
    return queries._sales_source("1=1")


def normalized_rentals_source_sql() -> str:
    """Public DXBI rental projection for domain consumers sharing transaction identities."""
    return queries._rentals_source("1=1")


def _text(value: object) -> Optional[str]:
    """DXBI leaves unknown text fields empty; the API reports them as missing."""
    return str(value) if value not in (None, "") else None


def _whole(value: float | int | None) -> Optional[int]:
    return int(value) if value is not None else None


def sale_response(row: dict) -> TransactionResponse:
    return TransactionResponse(
        transaction_id=row["transaction_id"],
        transaction_date=row["transaction_date"],
        unit_number=_text(row["unit_number"]),
        building_name=_text(row["building_name"]),
        project_name=_text(row["project_name"]),
        master_project=_text(row["master_project"]),
        dld_area=_text(row["dld_area"]),
        location=_text(row["location"]),
        map_url=_text(row["map_url"]),
        location_name=_text(row["location_name"]),
        property_type=_text(row["property_type"]),
        bedrooms=_text(row["bedrooms"]),
        status=_text(row["status"]),
        size_sqft=row["size_sqft"],
        price_aed=_whole(row["price_aed"]),
        price_per_sqft_aed=_whole(row["price_per_sqft"]),
    )


def rental_response(row: dict) -> RentalContractResponse:
    return RentalContractResponse(
        contract_id=row["contract_id"],
        lease_start=row["lease_start"],
        lease_end=row["lease_end"],
        unit_number=_text(row["unit_number"]),
        building_name=_text(row["building_name"]),
        project_name=_text(row["project_name"]),
        master_project=_text(row["master_project"]),
        dld_area=_text(row["dld_area"]),
        location=_text(row["location"]),
        map_url=_text(row["map_url"]),
        location_name=_text(row["location_name"]),
        property_type=_text(row["property_type"]),
        bedrooms=_text(row["bedrooms"]),
        size_sqft=row["size_sqft"],
        annual_rent_aed=_whole(row["annual_rent_aed"]),
        contract_amount_aed=_whole(row["contract_amount_aed"]),
        term_months=row["term_months"] or None,
        contract_type=_text(row["contract_type"]),
    )


async def fetch_sales_transactions(
    filters: SalesFilters, limit: int, offset: int
) -> TransactionListResponse:
    """One page of DXBI sales, newest first."""
    rows, total = await queries.fetch_sales_rows(filters, limit, offset)
    return TransactionListResponse(
        transactions=[sale_response(row) for row in rows], total=total, limit=limit, offset=offset
    )


async def fetch_rental_contracts(
    filters: RentalFilters, limit: int, offset: int
) -> RentalContractListResponse:
    """One page of DXBI leases, latest start first."""
    rows, total = await queries.fetch_rental_rows(filters, limit, offset)
    return RentalContractListResponse(
        contracts=[rental_response(row) for row in rows], total=total, limit=limit, offset=offset
    )
