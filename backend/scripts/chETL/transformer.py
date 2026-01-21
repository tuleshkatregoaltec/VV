"""Type transformations and data enrichment."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


def parse_date(val: Any) -> Optional[datetime]:
    """Parse date with multiple format support."""
    if not val or str(val).strip().lower() in ("null", "none", ""):
        return None

    val_str = str(val).strip()

    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(val_str, fmt)
        except ValueError:
            continue

    logger.warning(f"Could not parse date: {val}")
    return None


def parse_decimal(val: Any) -> Optional[Decimal]:
    """Parse decimal, handling empty/null."""
    if not val or str(val).strip().lower() in ("null", "none", ""):
        return None

    try:
        return Decimal(str(val).strip())
    except (InvalidOperation, ValueError):
        logger.warning(f"Could not parse decimal: {val}")
        return None


def parse_int(val: Any) -> Optional[int]:
    """Parse integer, handling empty/null."""
    if not val or str(val).strip().lower() in ("null", "none", ""):
        return None

    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        logger.warning(f"Could not parse int: {val}")
        return None


def parse_float(val: Any) -> Optional[float]:
    """Parse float, handling empty/null."""
    if not val or str(val).strip().lower() in ("null", "none", ""):
        return None

    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        logger.warning(f"Could not parse float: {val}")
        return None


def parse_boolean(val: Any) -> Optional[int]:
    """Parse boolean as UInt8 (0 or 1)."""
    if not val:
        return None

    val_str = str(val).lower().strip()

    if val_str in ("true", "yes", "1", "t", "y"):
        return 1
    elif val_str in ("false", "no", "0", "f", "n"):
        return 0
    else:
        return None


def compute_price_bucket(actual_worth: Optional[Decimal]) -> Optional[str]:
    """Compute price bucket for analytics UI."""
    if actual_worth is None:
        return None

    worth = float(actual_worth)

    if worth < 500_000:
        return "<500K"
    elif worth < 1_000_000:
        return "500K-1M"
    elif worth < 2_000_000:
        return "1M-2M"
    elif worth < 5_000_000:
        return "2M-5M"
    elif worth < 10_000_000:
        return "5M-10M"
    elif worth < 25_000_000:
        return "10M-25M"
    else:
        return ">25M"


def compute_area_bucket(area_sqm: Optional[Decimal]) -> Optional[str]:
    """Compute area bucket (sq.m)."""
    if area_sqm is None:
        return None

    area = float(area_sqm)

    if area < 50:
        return "<50"
    elif area < 100:
        return "50-100"
    elif area < 200:
        return "100-200"
    elif area < 500:
        return "200-500"
    elif area < 1000:
        return "500-1K"
    else:
        return ">1K"


def compute_price_sqft_bucket(price_sqm: Optional[Decimal]) -> Optional[str]:
    """Compute price per sq.m bucket (AED/sq.m)."""
    if price_sqm is None:
        return None

    price = float(price_sqm)

    if price < 10_000:
        return "<10K"
    elif price < 15_000:
        return "10K-15K"
    elif price < 20_000:
        return "15K-20K"
    elif price < 25_000:
        return "20K-25K"
    elif price < 30_000:
        return "25K-30K"
    else:
        return ">30K"


def transform_transactions_row(
    row: Dict[str, Any],
    project_name_cache: Dict[str, str],
) -> Dict[str, Any]:
    """
    Transform a transaction row.

    Steps:
    1. Type conversions
    2. Enrich project name from cache
    3. Compute buckets
    """
    transformed = row.copy()

    # Type conversions
    transformed["instance_date"] = parse_date(row.get("instance_date"))
    transformed["actual_worth"] = parse_decimal(row.get("actual_worth"))
    transformed["procedure_area"] = parse_decimal(row.get("procedure_area"))
    transformed["meter_sale_price"] = parse_decimal(row.get("meter_sale_price"))
    transformed["has_parking"] = parse_boolean(row.get("has_parking"))
    transformed["area_id"] = parse_int(row.get("area_id"))

    # Enrich project name
    project_number = row.get("project_number")
    if project_number and project_number in project_name_cache:
        transformed["project_name_en"] = project_name_cache[project_number]

    # Compute buckets
    transformed["price_bucket"] = compute_price_bucket(transformed["actual_worth"])
    transformed["area_bucket"] = compute_area_bucket(transformed["procedure_area"])
    transformed["price_sqft_bucket"] = compute_price_sqft_bucket(
        transformed["meter_sale_price"]
    )

    return transformed


def transform_rent_contracts_row(
    row: Dict[str, Any],
    project_name_cache: Dict[str, str],
) -> Dict[str, Any]:
    """Transform a rent contract row."""
    transformed = row.copy()

    # Type conversions
    transformed["contract_start_date"] = parse_date(row.get("contract_start_date"))
    transformed["contract_end_date"] = parse_date(row.get("contract_end_date"))
    transformed["annual_amount"] = parse_decimal(row.get("annual_amount"))
    transformed["actual_area"] = parse_decimal(row.get("actual_area"))
    transformed["rent_per_sqm"] = parse_decimal(row.get("rent_per_sqm"))
    transformed["line_number"] = parse_int(row.get("line_number")) or 0
    transformed["area_id"] = parse_int(row.get("area_id"))

    # Enrich project name
    project_number = row.get("project_number")
    if project_number and project_number in project_name_cache:
        transformed["project_name_en"] = project_name_cache[project_number]

    # Compute buckets
    transformed["rent_bucket"] = compute_price_bucket(transformed["annual_amount"])
    transformed["area_bucket"] = compute_area_bucket(transformed["actual_area"])
    transformed["rent_sqft_bucket"] = compute_price_sqft_bucket(
        transformed["rent_per_sqm"]
    )

    return transformed


def transform_projects_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a projects row."""
    transformed = row.copy()

    # Type conversions
    transformed["project_id"] = parse_int(row.get("project_id"))
    transformed["master_project_id"] = parse_int(row.get("master_project_id"))
    transformed["developer_id"] = parse_int(row.get("developer_id"))
    transformed["master_developer_id"] = parse_int(row.get("master_developer_id"))
    transformed["area_id"] = parse_int(row.get("area_id"))
    transformed["is_free_hold"] = parse_boolean(row.get("is_free_hold"))
    transformed["percent_completed"] = parse_float(row.get("percent_completed"))

    # Dates
    transformed["project_start_date"] = parse_date(row.get("project_start_date"))
    transformed["completion_date"] = parse_date(row.get("completion_date"))
    transformed["project_end_date"] = parse_date(row.get("project_end_date"))
    transformed["cancellation_date"] = parse_date(row.get("cancellation_date"))

    # Counts (already mapped via column_mappings)
    transformed["total_units"] = parse_int(row.get("total_units"))
    transformed["total_buildings"] = parse_int(row.get("total_buildings"))
    transformed["total_villas"] = parse_int(row.get("total_villas"))

    return transformed


def transform_buildings_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a buildings row."""
    transformed = row.copy()

    # Type conversions
    transformed["building_id"] = parse_int(row.get("building_id"))
    transformed["project_id"] = parse_int(row.get("project_id"))
    transformed["master_project_id"] = parse_int(row.get("master_project_id"))
    transformed["land_registry_id"] = parse_int(row.get("land_registry_id"))
    transformed["area_id"] = parse_int(row.get("area_id"))
    transformed["is_free_hold"] = parse_boolean(row.get("is_free_hold"))

    # Building specs
    transformed["bld_levels"] = parse_int(row.get("bld_levels"))
    transformed["floors"] = parse_int(row.get("floors"))
    transformed["units"] = parse_int(row.get("units"))
    transformed["flats"] = parse_int(row.get("flats"))
    transformed["offices"] = parse_int(row.get("offices"))
    transformed["car_parks"] = parse_int(row.get("car_parks"))
    transformed["shops"] = parse_int(row.get("shops"))
    transformed["elevators"] = parse_int(row.get("elevators"))
    transformed["swimming_pools"] = parse_int(row.get("swimming_pools"))

    return transformed


def transform_units_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a units row."""
    transformed = row.copy()

    # Type conversions
    transformed["unit_id"] = parse_int(row.get("unit_id"))
    transformed["building_id"] = parse_int(row.get("building_id"))
    transformed["project_id"] = parse_int(row.get("project_id"))
    transformed["master_project_id"] = parse_int(row.get("master_project_id"))
    transformed["area_id"] = parse_int(row.get("area_id"))
    transformed["is_free_hold"] = parse_boolean(row.get("is_free_hold"))

    # Unit specs
    transformed["actual_area"] = parse_decimal(row.get("actual_area"))
    transformed["common_area"] = parse_decimal(row.get("common_area"))
    transformed["unit_balcony_area"] = parse_decimal(row.get("unit_balcony_area"))

    return transformed


def transform_land_registry_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a land registry row."""
    transformed = row.copy()

    # Type conversions
    transformed["land_registry_id"] = parse_int(row.get("land_registry_id"))
    transformed["master_project_id"] = parse_int(row.get("master_project_id"))
    transformed["area_id"] = parse_int(row.get("area_id"))
    transformed["parcel_area"] = parse_decimal(row.get("parcel_area"))
    transformed["is_free_hold"] = parse_boolean(row.get("is_free_hold"))
    transformed["separated_from"] = parse_int(row.get("separated_from"))

    return transformed


def transform_developers_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a developers row."""
    transformed = row.copy()
    transformed["developer_id"] = parse_int(row.get("developer_id"))
    return transformed


def transform_areas_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Transform an areas row."""
    transformed = row.copy()
    transformed["area_id"] = parse_int(row.get("area_id"))
    return transformed
