from typing import Optional, List
from datetime import date
from decimal import Decimal

from sqlmodel import SQLModel, Field, Relationship


# ============================================================================
# LOOKUP & REFERENCE TABLES
# ============================================================================


class TransactionGroup(SQLModel, table=True):
    """Transaction type groups (Sales, Mortgages, Gifts, etc.)"""

    __tablename__ = "transaction_groups"

    # Primary key
    group_id: int = Field(primary_key=True)
    group_name_ar: str = Field(max_length=255)
    group_name: str = Field(max_length=255)

    # Relationships
    procedures: List["TransactionProcedure"] = Relationship(back_populates="group")


class TransactionProcedure(SQLModel, table=True):
    """Specific transaction procedures (Registration, Transfer, Initial Sale, etc.)"""

    __tablename__ = "transaction_procedures"

    # Primary key
    procedure_id: int = Field(primary_key=True)
    group_id: int = Field(foreign_key="transaction_groups.group_id")
    is_pre_registration: bool = Field(default=False)
    procedure_name_ar: str = Field(max_length=255)
    procedure_name: str = Field(max_length=255)

    # Relationships
    group: TransactionGroup = Relationship(back_populates="procedures")
    transactions: List["Transaction"] = Relationship(back_populates="procedure")


class Area(SQLModel, table=True):
    """Geographic areas and districts (Dubai Marina, Downtown Dubai, Jumeirah, etc.)"""

    __tablename__ = "areas"

    # Primary key
    area_id: int = Field(primary_key=True)
    name_ar: str = Field(max_length=255)
    name: str = Field(max_length=255)
    municipality_number: Optional[str] = Field(default=None, max_length=50)
    zone_id: Optional[int] = None

    # Relationships
    land_registries: List["LandRegistry"] = Relationship(back_populates="area")
    buildings: List["Building"] = Relationship(back_populates="area")
    units: List["Unit"] = Relationship(back_populates="area")
    transactions: List["Transaction"] = Relationship(back_populates="area")
    rent_contracts: List["RentContract"] = Relationship(back_populates="area")
    projects: List["Project"] = Relationship(back_populates="area")


class PropertyType(SQLModel, table=True):
    """Property type classifications (Land, Building, Unit, Villa, etc.)"""

    __tablename__ = "property_types"

    # Primary key
    property_type_id: int = Field(primary_key=True)
    property_type_ar: str = Field(max_length=255)
    property_type: str = Field(max_length=255)

    # Relationships
    sub_types: List["PropertySubType"] = Relationship(back_populates="property_type")


class PropertySubType(SQLModel, table=True):
    """Detailed property classifications (Apartment, Office, Retail, Warehouse, etc.)"""

    __tablename__ = "property_sub_types"

    # Primary key
    property_sub_type_id: int = Field(primary_key=True)
    property_type_id: int = Field(foreign_key="property_types.property_type_id")
    property_sub_type_ar: str = Field(max_length=255)
    property_sub_type: str = Field(max_length=255)

    # Relationships
    property_type: Optional[PropertyType] = Relationship(back_populates="sub_types")


class MasterProject(SQLModel, table=True):
    """Large development complexes (Dubai Marina, Business Bay, DAMAC Hills, etc.)"""

    __tablename__ = "master_projects"

    # Primary key
    master_project_id: int = Field(primary_key=True)
    master_project_name_ar: str = Field(max_length=255)
    master_project_name: str = Field(max_length=255)

    # Relationships
    land_registries: List["LandRegistry"] = Relationship(
        back_populates="master_project"
    )
    buildings: List["Building"] = Relationship(back_populates="master_project")
    units: List["Unit"] = Relationship(back_populates="master_project")


# ============================================================================
# CORE ENTITY TABLES
# ============================================================================


class Developer(SQLModel, table=True):
    """Real estate developers and companies (Emaar, DAMAC, Nakheel, etc.)"""

    __tablename__ = "developers"

    # Primary key
    developer_id: int = Field(primary_key=True)
    participant_id: Optional[int] = None
    developer_number: int = Field(unique=True)
    developer_name_ar: str = Field(max_length=255)
    developer_name: str = Field(max_length=255)
    registration_date: Optional[date] = None

    # License information
    license_source_id: Optional[int] = None
    license_source_ar: Optional[str] = Field(default=None, max_length=255)
    license_source: Optional[str] = Field(default=None, max_length=255)
    license_type_id: Optional[int] = None
    license_type_ar: Optional[str] = Field(default=None, max_length=255)
    license_type: Optional[str] = Field(default=None, max_length=255)
    license_number: Optional[str] = Field(default=None, max_length=50)
    license_issue_date: Optional[date] = None
    license_expiry_date: Optional[date] = None

    # Company details
    chamber_of_commerce_no: Optional[str] = Field(default=None, max_length=50)
    legal_status: Optional[str] = Field(default=None, max_length=10)
    legal_status_ar: Optional[str] = Field(default=None, max_length=255)
    legal_status_description: Optional[str] = Field(default=None, max_length=255)

    # Contact information
    webpage: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=50)
    fax: Optional[str] = Field(default=None, max_length=50)

    # Relationships
    projects_developed: List["Project"] = Relationship(
        back_populates="developer",
        sa_relationship_kwargs={"foreign_keys": "Project.developer_id"},
    )
    projects_master: List["Project"] = Relationship(
        back_populates="master_developer",
        sa_relationship_kwargs={"foreign_keys": "Project.master_developer_id"},
    )


class Project(SQLModel, table=True):
    """Real estate development projects (specific buildings and communities)"""

    __tablename__ = "projects"

    # Primary key
    project_id: int = Field(primary_key=True)
    project_number: Optional[int] = Field(default=None, unique=True)
    project_name: str = Field(max_length=255)

    # Developer relationships
    developer_id: Optional[int] = Field(
        default=None, foreign_key="developers.developer_id"
    )
    master_developer_id: Optional[int] = Field(
        default=None, foreign_key="developers.developer_id"
    )

    # Timeline
    project_start_date: Optional[date] = None
    project_end_date: Optional[date] = None
    completion_date: Optional[date] = None
    cancellation_date: Optional[date] = None

    # Project details
    project_type_id: Optional[int] = None
    project_type_ar: Optional[str] = Field(default=None, max_length=255)
    project_classification_id: Optional[int] = None
    project_classification_ar: Optional[str] = Field(default=None, max_length=255)
    project_status: Optional[str] = Field(default=None, max_length=50)
    project_status_ar: Optional[str] = Field(default=None, max_length=255)
    percent_completed: Optional[int] = None

    # Financial
    escrow_agent_id: Optional[int] = None
    escrow_agent_name: Optional[str] = Field(default=None, max_length=255)

    # Location
    property_id: Optional[int] = None
    area_id: Optional[int] = Field(default=None, foreign_key="areas.area_id")
    zoning_authority_id: Optional[int] = None
    zoning_authority_ar: Optional[str] = Field(default=None, max_length=255)
    zoning_authority: Optional[str] = Field(default=None, max_length=255)

    # Descriptions
    project_description_ar: Optional[str] = None
    project_description: Optional[str] = None

    # Counts
    no_of_lands: Optional[int] = None
    no_of_buildings: Optional[int] = None
    no_of_villas: Optional[int] = None
    no_of_units: Optional[int] = None

    # Relationships
    developer: Optional[Developer] = Relationship(
        back_populates="projects_developed",
        sa_relationship_kwargs={"foreign_keys": "Project.developer_id"},
    )
    master_developer: Optional[Developer] = Relationship(
        back_populates="projects_master",
        sa_relationship_kwargs={"foreign_keys": "Project.master_developer_id"},
    )
    area: Optional[Area] = Relationship(back_populates="projects")
    land_registries: List["LandRegistry"] = Relationship(back_populates="project")
    buildings: List["Building"] = Relationship(back_populates="project")
    units: List["Unit"] = Relationship(back_populates="project")


# ============================================================================
# PROPERTY HIERARCHY
# ============================================================================


class LandRegistry(SQLModel, table=True):
    """Land parcels - base level of property hierarchy"""

    __tablename__ = "land_registry"

    # Primary key
    property_id: int = Field(primary_key=True)

    # Location
    area_id: Optional[int] = Field(default=None, foreign_key="areas.area_id")
    zone_id: Optional[int] = None
    land_number: Optional[str] = Field(default=None, max_length=50)
    land_sub_number: Optional[str] = Field(default=None, max_length=50)

    # Area measurement
    actual_area: Optional[Decimal] = Field(
        default=None, max_digits=15, decimal_places=2
    )

    # Property classification
    property_type_id: Optional[int] = Field(
        default=None, foreign_key="property_types.property_type_id"
    )
    property_sub_type_id: Optional[int] = Field(
        default=None, foreign_key="property_sub_types.property_sub_type_id"
    )

    # Registration details
    parcel_id: Optional[str] = Field(default=None, max_length=50)
    munc_zip_code: Optional[str] = Field(default=None, max_length=20)
    munc_number: Optional[str] = Field(default=None, max_length=50)
    is_free_hold: Optional[bool] = None
    is_registered: Optional[bool] = None
    pre_registration_number: Optional[str] = Field(default=None, max_length=50)

    # Subdivision tracking
    separated_from: Optional[int] = Field(
        default=None, foreign_key="land_registry.property_id"
    )
    separated_reference: Optional[int] = None

    # Project relationships
    project_id: Optional[int] = Field(default=None, foreign_key="projects.project_id")
    master_project_id: Optional[int] = Field(
        default=None, foreign_key="master_projects.master_project_id"
    )
    land_type_id: Optional[int] = None
    land_type_ar: Optional[str] = Field(default=None, max_length=255)
    land_type: Optional[str] = Field(default=None, max_length=255)

    # Relationships
    area: Optional[Area] = Relationship(back_populates="land_registries")
    project: Optional[Project] = Relationship(back_populates="land_registries")
    master_project: Optional[MasterProject] = Relationship(
        back_populates="land_registries"
    )
    buildings: List["Building"] = Relationship(back_populates="parent_land")
    units: List["Unit"] = Relationship(back_populates="grandparent_land")

    parent_land: Optional["LandRegistry"] = Relationship(
        back_populates="subdivisions",
        sa_relationship_kwargs={
            "remote_side": "LandRegistry.property_id",
            "foreign_keys": "LandRegistry.separated_from",
        },
    )
    subdivisions: List["LandRegistry"] = Relationship(
        back_populates="parent_land",
        sa_relationship_kwargs={"foreign_keys": "LandRegistry.separated_from"},
    )


class Building(SQLModel, table=True):
    """Buildings and villas - mid-level of property hierarchy"""

    __tablename__ = "buildings"

    # Primary key
    property_id: int = Field(primary_key=True)

    # Location
    area_id: Optional[int] = Field(default=None, foreign_key="areas.area_id")
    zone_id: Optional[int] = None
    land_number: Optional[str] = Field(default=None, max_length=50)
    land_sub_number: Optional[str] = Field(default=None, max_length=50)
    building_number: Optional[str] = Field(default=None, max_length=100)

    # Building characteristics
    floors: Optional[int] = None
    bld_levels: Optional[int] = None
    rooms: Optional[int] = None
    rooms_ar: Optional[str] = Field(default=None, max_length=100)
    rooms_description: Optional[str] = Field(default=None, max_length=100)
    car_parks: Optional[int] = None

    # Area measurements
    common_area: Optional[Decimal] = Field(
        default=None, max_digits=20, decimal_places=4
    )
    actual_common_area: Optional[Decimal] = Field(
        default=None, max_digits=15, decimal_places=2
    )
    built_up_area: Optional[Decimal] = Field(
        default=None, max_digits=15, decimal_places=2
    )
    actual_area: Optional[Decimal] = Field(
        default=None, max_digits=15, decimal_places=2
    )

    # Unit counts
    shops: Optional[int] = None
    flats: Optional[int] = None
    offices: Optional[int] = None
    swimming_pools: Optional[int] = None
    elevators: Optional[int] = None

    # Property classification
    property_type_id: Optional[int] = Field(
        default=None, foreign_key="property_types.property_type_id"
    )
    property_sub_type_id: Optional[int] = Field(
        default=None, foreign_key="property_sub_types.property_sub_type_id"
    )

    # Hierarchy
    parent_property_id: Optional[int] = Field(
        default=None, foreign_key="land_registry.property_id"
    )

    # Registration details
    creation_date: Optional[date] = None
    parcel_id: Optional[str] = Field(default=None, max_length=50)
    is_free_hold: Optional[bool] = None
    is_lease_hold: Optional[bool] = None
    is_registered: Optional[bool] = None
    pre_registration_number: Optional[str] = Field(default=None, max_length=50)

    # Project relationships
    project_id: Optional[int] = Field(default=None, foreign_key="projects.project_id")
    master_project_id: Optional[int] = Field(
        default=None, foreign_key="master_projects.master_project_id"
    )
    land_type_id: Optional[int] = None
    land_type_ar: Optional[str] = Field(default=None, max_length=255)
    land_type: Optional[str] = Field(default=None, max_length=255)

    # Relationships
    area: Optional[Area] = Relationship(back_populates="buildings")
    parent_land: Optional[LandRegistry] = Relationship(back_populates="buildings")
    project: Optional[Project] = Relationship(back_populates="buildings")
    master_project: Optional[MasterProject] = Relationship(back_populates="buildings")
    units: List["Unit"] = Relationship(back_populates="parent_building")


class Unit(SQLModel, table=True):
    """Individual units (apartments, offices, hotel rooms, etc.) - detail level of property hierarchy"""

    __tablename__ = "units"

    # Primary key
    property_id: int = Field(primary_key=True)

    # Location
    area_id: Optional[int] = Field(default=None, foreign_key="areas.area_id")
    zone_id: Optional[int] = None
    land_number: Optional[str] = Field(default=None, max_length=100)
    land_sub_number: Optional[str] = Field(default=None, max_length=100)
    building_number: Optional[str] = Field(default=None, max_length=100)
    unit_number: Optional[str] = Field(default=None, max_length=100)
    floor: Optional[str] = Field(default=None, max_length=50)

    # Unit characteristics
    rooms: Optional[int] = None
    rooms_ar: Optional[str] = Field(default=None, max_length=100)
    rooms_description: Optional[str] = Field(default=None, max_length=100)

    # Area measurements
    unit_balcony_area: Optional[Decimal] = Field(
        default=None, max_digits=15, decimal_places=2
    )
    common_area: Optional[Decimal] = Field(
        default=None, max_digits=15, decimal_places=2
    )
    actual_common_area: Optional[Decimal] = Field(
        default=None, max_digits=15, decimal_places=2
    )
    actual_area: Optional[Decimal] = Field(
        default=None, max_digits=15, decimal_places=2
    )

    # Parking details
    unit_parking_number: Optional[str] = Field(default=None, max_length=1000)
    parking_allocation_type: Optional[str] = Field(default=None, max_length=200)
    parking_allocation_type_ar: Optional[str] = Field(default=None, max_length=200)
    parking_allocation_type_description: Optional[str] = Field(
        default=None, max_length=255
    )

    # Property classification
    property_type_id: Optional[int] = Field(
        default=None, foreign_key="property_types.property_type_id"
    )
    property_sub_type_id: Optional[int] = Field(
        default=None, foreign_key="property_sub_types.property_sub_type_id"
    )

    # Hierarchy
    parent_property_id: Optional[int] = Field(
        default=None, foreign_key="buildings.property_id"
    )
    grandparent_property_id: Optional[int] = Field(
        default=None, foreign_key="land_registry.property_id"
    )

    # Registration details
    creation_date: Optional[date] = None
    munc_zip_code: Optional[str] = Field(default=None, max_length=20)
    munc_number: Optional[str] = Field(default=None, max_length=100)
    parcel_id: Optional[str] = Field(default=None, max_length=100)
    is_free_hold: Optional[bool] = None
    is_lease_hold: Optional[bool] = None
    is_registered: Optional[bool] = None
    pre_registration_number: Optional[str] = Field(default=None, max_length=100)

    # Project relationships
    project_id: Optional[int] = Field(default=None, foreign_key="projects.project_id")
    master_project_id: Optional[int] = Field(
        default=None, foreign_key="master_projects.master_project_id"
    )
    land_type_id: Optional[int] = None
    land_type_ar: Optional[str] = Field(default=None, max_length=255)
    land_type: Optional[str] = Field(default=None, max_length=255)

    # Relationships
    area: Optional[Area] = Relationship(back_populates="units")
    parent_building: Optional[Building] = Relationship(back_populates="units")
    grandparent_land: Optional[LandRegistry] = Relationship(back_populates="units")
    project: Optional[Project] = Relationship(back_populates="units")
    master_project: Optional[MasterProject] = Relationship(back_populates="units")


# ============================================================================
# TRANSACTION DATA
# ============================================================================


class Transaction(SQLModel, table=True):
    """Market transaction records - independent analytics data"""

    __tablename__ = "transactions"

    # Primary key
    transaction_id: str = Field(primary_key=True, max_length=50)

    # Transaction classification
    procedure_id: Optional[int] = Field(
        default=None, foreign_key="transaction_procedures.procedure_id"
    )
    trans_group_id: Optional[int] = None
    trans_group_ar: Optional[str] = Field(default=None, max_length=255)
    trans_group: Optional[str] = Field(default=None, max_length=255)
    procedure_name_ar: Optional[str] = Field(default=None, max_length=255)
    procedure_name: Optional[str] = Field(default=None, max_length=255)
    instance_date: Optional[date] = None

    # Property classification
    property_type_id: Optional[int] = None
    property_type_ar: Optional[str] = Field(default=None, max_length=255)
    property_type: Optional[str] = Field(default=None, max_length=255)
    property_sub_type_id: Optional[int] = None
    property_sub_type_ar: Optional[str] = Field(default=None, max_length=255)
    property_sub_type: Optional[str] = Field(default=None, max_length=255)
    property_usage_ar: Optional[str] = Field(default=None, max_length=255)
    property_usage: Optional[str] = Field(default=None, max_length=255)

    # Registration details
    reg_type_id: Optional[int] = None
    reg_type_ar: Optional[str] = Field(default=None, max_length=255)
    reg_type: Optional[str] = Field(default=None, max_length=255)

    # Location
    area_id: Optional[int] = Field(default=None, foreign_key="areas.area_id")
    area_name_ar: Optional[str] = Field(default=None, max_length=255)
    area_name: Optional[str] = Field(default=None, max_length=255)
    building_name_ar: Optional[str] = Field(default=None, max_length=255)
    building_name: Optional[str] = Field(default=None, max_length=255)

    # Project details
    project_number: Optional[str] = Field(default=None, max_length=50)
    project_name_ar: Optional[str] = Field(default=None, max_length=255)
    project_name: Optional[str] = Field(default=None, max_length=255)
    master_project_ar: Optional[str] = Field(default=None, max_length=255)
    master_project: Optional[str] = Field(default=None, max_length=255)

    # Nearby amenities
    nearest_landmark_ar: Optional[str] = Field(default=None, max_length=255)
    nearest_landmark: Optional[str] = Field(default=None, max_length=255)
    nearest_metro_ar: Optional[str] = Field(default=None, max_length=255)
    nearest_metro: Optional[str] = Field(default=None, max_length=255)
    nearest_mall_ar: Optional[str] = Field(default=None, max_length=255)
    nearest_mall: Optional[str] = Field(default=None, max_length=255)

    # Property characteristics
    rooms_ar: Optional[str] = Field(default=None, max_length=100)
    rooms_description: Optional[str] = Field(default=None, max_length=100)
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
    area: Optional[Area] = Relationship(back_populates="transactions")
    procedure: Optional[TransactionProcedure] = Relationship(
        back_populates="transactions"
    )


class RentContract(SQLModel, table=True):
    """Rental contract records from Ejari system (Dubai's official rental registration)

    Note: A single contract can cover multiple properties, each identified by line_number.
    The composite primary key (contract_id, line_number) ensures uniqueness.
    """

    __tablename__ = "rent_contracts"

    # Primary key (composite key)
    contract_id: str = Field(primary_key=True, max_length=50)
    line_number: int = Field(primary_key=True)

    # Contract details
    contract_reg_type_id: Optional[int] = None
    contract_reg_type_ar: Optional[str] = Field(default=None, max_length=100)
    contract_reg_type: Optional[str] = Field(default=None, max_length=100)
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
    ejari_bus_property_type: Optional[str] = Field(default=None, max_length=100)

    ejari_property_type_id: Optional[int] = None
    ejari_property_type: Optional[str] = Field(default=None, max_length=100)
    ejari_property_type_ar: Optional[str] = Field(default=None, max_length=100)

    ejari_property_sub_type_id: Optional[int] = None
    ejari_property_sub_type: Optional[str] = Field(default=None, max_length=100)
    ejari_property_sub_type_ar: Optional[str] = Field(default=None, max_length=100)

    property_usage: Optional[str] = Field(default=None, max_length=100)
    property_usage_ar: Optional[str] = Field(default=None, max_length=100)

    # Project details
    project_number: Optional[str] = Field(default=None, max_length=50)
    project_name_ar: Optional[str] = Field(default=None, max_length=255)
    project_name: Optional[str] = Field(default=None, max_length=255)
    master_project_ar: Optional[str] = Field(default=None, max_length=255)
    master_project: Optional[str] = Field(default=None, max_length=255)

    # Location
    area_id: Optional[int] = Field(default=None, foreign_key="areas.area_id")
    area_name_ar: Optional[str] = Field(default=None, max_length=255)
    area_name: Optional[str] = Field(default=None, max_length=255)
    actual_area: Optional[Decimal] = Field(
        default=None, max_digits=15, decimal_places=2
    )

    # Nearby amenities
    nearest_landmark_ar: Optional[str] = Field(default=None, max_length=255)
    nearest_landmark: Optional[str] = Field(default=None, max_length=255)
    nearest_metro_ar: Optional[str] = Field(default=None, max_length=255)
    nearest_metro: Optional[str] = Field(default=None, max_length=255)
    nearest_mall_ar: Optional[str] = Field(default=None, max_length=255)
    nearest_mall: Optional[str] = Field(default=None, max_length=255)

    # Tenant information
    tenant_type_id: Optional[int] = None
    tenant_type_ar: Optional[str] = Field(default=None, max_length=100)
    tenant_type: Optional[str] = Field(default=None, max_length=100)

    # Relationships
    area: Optional[Area] = Relationship(back_populates="rent_contracts")
