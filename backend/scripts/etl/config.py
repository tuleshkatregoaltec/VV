"""ETL configuration - table definitions and processing order."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.db.models import (
    Area,
    PropertyType,
    PropertySubType,
    MasterProject,
    Developer,
    TransactionGroup,
    TransactionProcedure,
    Project,
    LandRegistry,
    Building,
    Unit,
    Transaction,
    RentContract,
)


@dataclass
class TableConfig:
    """Configuration for a single table's ETL processing."""

    name: str
    model_class: type
    csv_file: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    column_renames: dict[str, str] = field(default_factory=dict)
    batch_size: int = 50_000
    is_lookup: bool = False
    extract_from_files: list[str] | None = None
    extract_columns: list[str] | None = None


def get_data_paths(data_dir: Path | None = None) -> tuple[Path, Path, Path, Path]:
    """Return current, previous, current_pks, and previous_pks data directories."""
    base = data_dir or Path(__file__).parent.parent.parent.parent / "data"
    current_dir = base / "current"
    previous_dir = base / "previous"
    current_pks_dir = current_dir / "pks"
    previous_pks_dir = previous_dir / "pks"
    current_dir.mkdir(parents=True, exist_ok=True)
    previous_dir.mkdir(parents=True, exist_ok=True)
    current_pks_dir.mkdir(parents=True, exist_ok=True)
    previous_pks_dir.mkdir(parents=True, exist_ok=True)
    return current_dir, previous_dir, current_pks_dir, previous_pks_dir


def get_table_configs() -> dict[str, TableConfig]:
    """Build table configuration dictionary."""
    configs: dict[str, TableConfig] = {}

    # ==========================================================================
    # LOOKUP TABLES - extracted from source files or standalone CSVs
    # ==========================================================================

    # PropertyType: property_type_id (PK), property_type_ar, property_type_en
    # CSV columns: property_type_id, property_type_ar, property_type_en
    configs["property_types"] = TableConfig(
        name="property_types",
        model_class=PropertyType,
        csv_file="Lkp_PropertyTypes.csv",  # Generated
        primary_keys=["property_type_id"],
        is_lookup=True,
        extract_from_files=[
            "Land_Registry.csv",
            "Units.csv",
            "Buildings.csv",
            "Transactions.csv",
        ],
        extract_columns=["property_type_id", "property_type_ar", "property_type_en"],
    )

    # PropertySubType: property_sub_type_id (PK), property_type_id, property_sub_type_ar, property_sub_type_en
    # CSV columns: property_sub_type_id, property_type_id, property_sub_type_ar, property_sub_type_en
    configs["property_sub_types"] = TableConfig(
        name="property_sub_types",
        model_class=PropertySubType,
        csv_file="Lkp_PropertySubTypes.csv",  # Generated
        primary_keys=["property_sub_type_id"],
        is_lookup=True,
        extract_from_files=[
            "Land_Registry.csv",
            "Units.csv",
            "Buildings.csv",
            "Transactions.csv",
        ],
        extract_columns=[
            "property_sub_type_id",
            "property_type_id",
            "property_sub_type_ar",
            "property_sub_type_en",
        ],
    )

    # TransactionGroup: group_id (PK), name_ar, name_en
    # CSV columns: group_id, name_ar, name_en
    configs["transaction_groups"] = TableConfig(
        name="transaction_groups",
        model_class=TransactionGroup,
        csv_file="Lkp_Transaction_Groups.csv",
        primary_keys=["group_id"],
    )

    # Area: area_id (PK), name_ar, name_en, municipality_number
    # CSV columns: area_id, name_en, name_ar, municipality_number
    configs["areas"] = TableConfig(
        name="areas",
        model_class=Area,
        csv_file="Lkp_Areas.csv",
        primary_keys=["area_id"],
    )

    # TransactionProcedure: procedure_id (PK), group_id, is_pre_registration, name_ar, name_en
    # CSV columns: group_id, procedure_id, is_pre_registration, name_ar, name_en
    configs["transaction_procedures"] = TableConfig(
        name="transaction_procedures",
        model_class=TransactionProcedure,
        csv_file="Lkp_Transaction_Procedures.csv",
        primary_keys=["procedure_id"],
    )

    # MasterProject: master_project_id (PK), master_project_ar, master_project_en
    # CSV columns: master_project_id, master_project_ar, master_project_en
    configs["master_projects"] = TableConfig(
        name="master_projects",
        model_class=MasterProject,
        csv_file="Lkp_Master_Projects.csv",  # Generated
        primary_keys=["master_project_id"],
        is_lookup=True,
        extract_from_files=["Land_Registry.csv", "Buildings.csv", "Units.csv"],
        extract_columns=["master_project_id", "master_project_ar", "master_project_en"],
    )

    # ==========================================================================
    # DEVELOPER & PROJECT TABLES
    # ==========================================================================

    # Developer: developer_name_en, license_source_en, license_type_en, legal_status_en
    # CSV columns: developer_name_en, license_source_en, license_type_en, legal_status_en
    configs["developers"] = TableConfig(
        name="developers",
        model_class=Developer,
        csv_file="Developers.csv",
        primary_keys=["developer_id"],
    )

    # Project: project_name, project_description_en, zoning_authority_en
    # CSV columns: project_name, project_description_en, zoning_authority_en
    configs["projects"] = TableConfig(
        name="projects",
        model_class=Project,
        csv_file="Projects.csv",
        primary_keys=["project_id"],
    )

    # ==========================================================================
    # PROPERTY HIERARCHY TABLES
    # ==========================================================================

    # LandRegistry: land_type_en (columns now match)
    # CSV has: land_type_en (plus area_name_en etc. which we don't store - denormalized)
    configs["land_registry"] = TableConfig(
        name="land_registry",
        model_class=LandRegistry,
        csv_file="Land_Registry.csv",
        primary_keys=["property_id"],
    )

    # Building: rooms, rooms_ar, rooms_en, land_type_en (columns now match)
    # CSV has: rooms, rooms_ar, rooms_en, land_type_en
    configs["buildings"] = TableConfig(
        name="buildings",
        model_class=Building,
        csv_file="Buildings.csv",
        primary_keys=["property_id"],
    )

    # Unit: rooms, rooms_ar, rooms_en, parking_allocation_type_en, land_type_en (columns now match)
    # CSV has same columns
    configs["units"] = TableConfig(
        name="units",
        model_class=Unit,
        csv_file="Units.csv",
        primary_keys=["property_id"],
    )

    # ==========================================================================
    # TRANSACTION TABLES
    # ==========================================================================

    # Transaction: all _en suffix columns now match model
    # CSV has: trans_group_en, procedure_name_en, property_type_en, rooms_ar, rooms_en
    configs["transactions"] = TableConfig(
        name="transactions",
        model_class=Transaction,
        csv_file="Transactions.csv",
        primary_keys=["transaction_id"],
    )

    # RentContract: all _en suffix columns now match model
    # CSV has _en suffix versions
    configs["rent_contracts"] = TableConfig(
        name="rent_contracts",
        model_class=RentContract,
        csv_file="Rent_Contracts.csv",
        primary_keys=["contract_id", "line_number"],
    )

    return configs


# Processing order - parent tables before children for FK integrity
PROCESSING_ORDER: list[str] = [
    "property_types",
    "property_sub_types",
    "transaction_groups",
    "areas",
    "transaction_procedures",
    "master_projects",
    "developers",
    "projects",
    "land_registry",
    "buildings",
    "units",
    "transactions",
    "rent_contracts",
]
