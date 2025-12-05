from typing import Optional, LiteralString, List, TYPE_CHECKING
from decimal import Decimal
from sqlmodel import SQLModel, Field, Relationship, Index, text
from datetime import date

if TYPE_CHECKING:
    from .geography import Area


class Transaction(SQLModel, table=True):
    """Market transaction records - independent analytics data"""

    __tablename__: LiteralString = "transactions"

    __table_args__ = (
        Index(
            "idx_transactions_date_usage",
            "property_usage_en",
            text("instance_date DESC"),
        ),
    )

    # Primary key
    transaction_id: str = Field(primary_key=True, max_length=50)

    # Transaction classification
    procedure_id: Optional[int] = Field(
        default=None, foreign_key="transaction_procedures.procedure_id"
    )
    trans_group_id: Optional[int] = None
    trans_group_ar: Optional[str] = Field(default=None, max_length=255)
    trans_group_en: Optional[str] = Field(default=None, max_length=255)
    procedure_name_ar: Optional[str] = Field(default=None, max_length=255)
    procedure_name_en: Optional[str] = Field(default=None, max_length=255)
    instance_date: Optional[date] = None

    # Property classification
    property_type_id: Optional[int] = None
    property_type_ar: Optional[str] = Field(default=None, max_length=255)
    property_type_en: Optional[str] = Field(default=None, max_length=255)
    property_sub_type_id: Optional[int] = None
    property_sub_type_ar: Optional[str] = Field(default=None, max_length=255)
    property_sub_type_en: Optional[str] = Field(default=None, max_length=255)
    property_usage_ar: Optional[str] = Field(default=None, max_length=255)
    property_usage_en: Optional[str] = Field(default=None, max_length=255)

    # Registration details
    reg_type_id: Optional[int] = None
    reg_type_ar: Optional[str] = Field(default=None, max_length=255)
    reg_type_en: Optional[str] = Field(default=None, max_length=255)

    # Location
    area_id: Optional[int] = Field(default=None, foreign_key="areas.area_id")
    area_name_ar: Optional[str] = Field(default=None, max_length=255)
    area_name_en: Optional[str] = Field(default=None, max_length=255)
    building_name_ar: Optional[str] = Field(default=None, max_length=255)
    building_name_en: Optional[str] = Field(default=None, max_length=255)

    # Project details
    project_number: Optional[str] = Field(default=None, max_length=50, index=True)
    project_name_ar: Optional[str] = Field(default=None, max_length=255)
    project_name_en: Optional[str] = Field(default=None, max_length=255)
    master_project_ar: Optional[str] = Field(default=None, max_length=255)
    master_project_en: Optional[str] = Field(default=None, max_length=255)

    # Nearby amenities
    nearest_landmark_ar: Optional[str] = Field(default=None, max_length=255)
    nearest_landmark_en: Optional[str] = Field(default=None, max_length=255)
    nearest_metro_ar: Optional[str] = Field(default=None, max_length=255)
    nearest_metro_en: Optional[str] = Field(default=None, max_length=255)
    nearest_mall_ar: Optional[str] = Field(default=None, max_length=255)
    nearest_mall_en: Optional[str] = Field(default=None, max_length=255)

    # Property characteristics
    rooms_ar: Optional[str] = Field(default=None, max_length=100)
    rooms_en: Optional[str] = Field(default=None, max_length=100)
    has_parking: Optional[bool] = None
    procedure_area: Optional[Decimal] = Field(
        default=None, max_digits=12, decimal_places=2
    )

    # Financial details
    actual_worth: Optional[Decimal] = Field(
        default=None, max_digits=15, decimal_places=2
    )
    meter_sale_price: Optional[Decimal] = Field(
        default=None, max_digits=12, decimal_places=2
    )
    rent_value: Optional[Decimal] = Field(default=None, max_digits=15, decimal_places=2)
    meter_rent_price: Optional[Decimal] = Field(
        default=None, max_digits=12, decimal_places=2
    )

    # Parties involved
    no_of_parties_role_1: Optional[int] = None
    no_of_parties_role_2: Optional[int] = None
    no_of_parties_role_3: Optional[int] = None

    # Relationships
    area: Optional["Area"] = Relationship(back_populates="transactions")
    procedure: Optional["TransactionProcedure"] = Relationship(
        back_populates="transactions"
    )


class RentContract(SQLModel, table=True):
    """Rental contract records from Ejari system (Dubai's official rental registration)

    Note: A single contract can cover multiple properties, each identified by line_number.
    The composite primary key (contract_id, line_number) ensures uniqueness.
    """

    __tablename__: LiteralString = "rent_contracts"

    __table_args__ = (
        Index(
            "idx_rent_contracts_date_usage",
            "property_usage_en",
            text("contract_start_date DESC"),
        ),
    )

    # Primary key (composite key)
    contract_id: str = Field(primary_key=True, max_length=50)
    line_number: int = Field(primary_key=True)

    # Contract details
    contract_reg_type_id: Optional[int] = None
    contract_reg_type_ar: Optional[str] = Field(default=None, max_length=100)
    contract_reg_type_en: Optional[str] = Field(default=None, max_length=100)
    contract_start_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    contract_amount: Optional[Decimal] = Field(
        default=None, max_digits=15, decimal_places=2
    )
    annual_amount: Optional[Decimal] = Field(
        default=None, max_digits=15, decimal_places=2
    )
    no_of_prop: Optional[int] = None
    is_free_hold: Optional[bool] = None

    # Property classification (Ejari specific)
    ejari_bus_property_type_id: Optional[int] = None
    ejari_bus_property_type_ar: Optional[str] = Field(default=None, max_length=100)
    ejari_bus_property_type_en: Optional[str] = Field(default=None, max_length=100)

    ejari_property_type_id: Optional[int] = None
    ejari_property_type_en: Optional[str] = Field(default=None, max_length=100)
    ejari_property_type_ar: Optional[str] = Field(default=None, max_length=100)

    ejari_property_sub_type_id: Optional[int] = None
    ejari_property_sub_type_en: Optional[str] = Field(default=None, max_length=100)
    ejari_property_sub_type_ar: Optional[str] = Field(default=None, max_length=100)

    property_usage_en: Optional[str] = Field(default=None, max_length=100)
    property_usage_ar: Optional[str] = Field(default=None, max_length=100)

    # Project details
    project_number: Optional[str] = Field(default=None, max_length=50)
    project_name_ar: Optional[str] = Field(default=None, max_length=255)
    project_name_en: Optional[str] = Field(default=None, max_length=255)
    master_project_ar: Optional[str] = Field(default=None, max_length=255)
    master_project_en: Optional[str] = Field(default=None, max_length=255)

    # Location
    area_id: Optional[int] = Field(default=None, foreign_key="areas.area_id")
    area_name_ar: Optional[str] = Field(default=None, max_length=255)
    area_name_en: Optional[str] = Field(default=None, max_length=255)
    actual_area: Optional[Decimal] = Field(
        default=None, max_digits=15, decimal_places=2
    )

    # Nearby amenities
    nearest_landmark_ar: Optional[str] = Field(default=None, max_length=255)
    nearest_landmark_en: Optional[str] = Field(default=None, max_length=255)
    nearest_metro_ar: Optional[str] = Field(default=None, max_length=255)
    nearest_metro_en: Optional[str] = Field(default=None, max_length=255)
    nearest_mall_ar: Optional[str] = Field(default=None, max_length=255)
    nearest_mall_en: Optional[str] = Field(default=None, max_length=255)

    # Tenant information
    tenant_type_id: Optional[int] = None
    tenant_type_ar: Optional[str] = Field(default=None, max_length=100)
    tenant_type_en: Optional[str] = Field(default=None, max_length=100)

    # Relationships
    area: Optional["Area"] = Relationship(back_populates="rent_contracts")


class TransactionGroup(SQLModel, table=True):
    """Transaction type groups (Sales, Mortgages, Gifts, etc.)"""

    __tablename__: LiteralString = "transaction_groups"

    # Primary key
    group_id: int = Field(primary_key=True)
    name_ar: Optional[str] = Field(default=None, max_length=255)
    name_en: Optional[str] = Field(default=None, max_length=255)

    # Relationships
    procedures: List["TransactionProcedure"] = Relationship(back_populates="group")


class TransactionProcedure(SQLModel, table=True):
    """Specific transaction procedures (Registration, Transfer, Initial Sale, etc.)"""

    __tablename__: LiteralString = "transaction_procedures"

    # Primary key
    procedure_id: int = Field(primary_key=True)
    group_id: Optional[int] = Field(default=None, foreign_key="transaction_groups.group_id")
    is_pre_registration: Optional[bool] = Field(default=None)
    name_ar: Optional[str] = Field(default=None, max_length=255)
    name_en: Optional[str] = Field(default=None, max_length=255)

    # Relationships
    group: "TransactionGroup" = Relationship(back_populates="procedures")
    transactions: List["Transaction"] = Relationship(back_populates="procedure")
