"""ETL configuration - table definitions and processing order."""

from dataclasses import dataclass, field

from app.db.models.geography import Area, MasterProject
from app.db.models.lookups import PropertyType, PropertySubType
from app.db.models.properties import Developer, Project, LandRegistry, Building, Unit
from app.db.models.transactions import (
    Transaction,
    RentContract,
    TransactionGroup,
    TransactionProcedure,
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


def get_table_configs() -> dict[str, TableConfig]:
    """Build table configuration dictionary."""
    configs: dict[str, TableConfig] = {}

    # Lookup tables
    configs["property_types"] = TableConfig(
        name="property_types",
        model_class=PropertyType,
        csv_file="Lkp_PropertyTypes.csv",
        primary_keys=["property_type_id"],
        is_lookup=True,
        extract_from_files=["Land_Registry.csv", "Units.csv", "Buildings.csv", "Transactions.csv"],
        extract_columns=["property_type_id", "property_type_ar", "property_type_en"],
    )

    configs["property_sub_types"] = TableConfig(
        name="property_sub_types",
        model_class=PropertySubType,
        csv_file="Lkp_PropertySubTypes.csv",
        primary_keys=["property_sub_type_id"],
        is_lookup=True,
        extract_from_files=["Land_Registry.csv", "Units.csv", "Buildings.csv", "Transactions.csv"],
        extract_columns=["property_sub_type_id", "property_type_id", "property_sub_type_ar", "property_sub_type_en"],
    )

    configs["transaction_groups"] = TableConfig(
        name="transaction_groups",
        model_class=TransactionGroup,
        csv_file="Lkp_Transaction_Groups.csv",
        primary_keys=["group_id"],
    )

    configs["areas"] = TableConfig(
        name="areas",
        model_class=Area,
        csv_file="Lkp_Areas.csv",
        primary_keys=["area_id"],
    )

    configs["transaction_procedures"] = TableConfig(
        name="transaction_procedures",
        model_class=TransactionProcedure,
        csv_file="Lkp_Transaction_Procedures.csv",
        primary_keys=["procedure_id"],
    )

    configs["master_projects"] = TableConfig(
        name="master_projects",
        model_class=MasterProject,
        csv_file="Lkp_Master_Projects.csv",
        primary_keys=["master_project_id"],
        is_lookup=True,
        extract_from_files=["Land_Registry.csv", "Buildings.csv", "Units.csv"],
        extract_columns=["master_project_id", "master_project_ar", "master_project_en"],
    )

    # Developer & project tables
    configs["developers"] = TableConfig(
        name="developers",
        model_class=Developer,
        csv_file="Developers.csv",
        primary_keys=["developer_id"],
    )

    configs["projects"] = TableConfig(
        name="projects",
        model_class=Project,
        csv_file="Projects.csv",
        primary_keys=["project_id"],
        column_renames={"project_name": "project_name_ar"},
    )

    # Property hierarchy tables
    configs["land_registry"] = TableConfig(
        name="land_registry",
        model_class=LandRegistry,
        csv_file="Land_Registry.csv",
        primary_keys=["property_id"],
    )

    configs["buildings"] = TableConfig(
        name="buildings",
        model_class=Building,
        csv_file="Buildings.csv",
        primary_keys=["property_id"],
    )

    configs["units"] = TableConfig(
        name="units",
        model_class=Unit,
        csv_file="Units.csv",
        primary_keys=["property_id"],
    )

    # Transaction tables
    configs["transactions"] = TableConfig(
        name="transactions",
        model_class=Transaction,
        csv_file="Transactions.csv",
        primary_keys=["transaction_id"],
    )

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
