from typing import Optional, List, LiteralString, TYPE_CHECKING
from decimal import Decimal
from sqlmodel import SQLModel, Field, Relationship
from datetime import date

if TYPE_CHECKING:
    from .geography import Area, MasterProject


class Developer(SQLModel, table=True):
    """Real estate developers and companies (Emaar, DAMAC, Nakheel, etc.)"""

    __tablename__: LiteralString = "developers"

    # Primary key
    developer_id: int = Field(primary_key=True)
    participant_id: Optional[int] = None
    developer_number: Optional[int] = Field(default=None, unique=True)
    developer_name_ar: Optional[str] = Field(default=None, max_length=255)
    developer_name_en: Optional[str] = Field(default=None, max_length=255)
    registration_date: Optional[date] = None

    # License information
    license_source_id: Optional[int] = None
    license_source_ar: Optional[str] = Field(default=None, max_length=255)
    license_source_en: Optional[str] = Field(default=None, max_length=255)
    license_type_id: Optional[int] = None
    license_type_ar: Optional[str] = Field(default=None, max_length=255)
    license_type_en: Optional[str] = Field(default=None, max_length=255)
    license_number: Optional[str] = Field(default=None, max_length=50)
    license_issue_date: Optional[date] = None
    license_expiry_date: Optional[date] = None

    # Company details
    chamber_of_commerce_no: Optional[str] = Field(default=None, max_length=50)
    legal_status: Optional[str] = Field(default=None, max_length=10)
    legal_status_ar: Optional[str] = Field(default=None, max_length=255)
    legal_status_en: Optional[str] = Field(default=None, max_length=255)

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

    __tablename__: LiteralString = "projects"

    # Primary key
    project_id: int = Field(primary_key=True)
    project_number: Optional[int] = Field(default=None, unique=True)
    project_name_ar: Optional[str] = Field(default=None, max_length=255)
    project_name_en: Optional[str] = Field(default=None, max_length=255)

    # Developer relationships
    developer_id: Optional[int] = Field(
        default=None, foreign_key="developers.developer_id", index=True
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
    zoning_authority_en: Optional[str] = Field(default=None, max_length=255)

    # Descriptions
    project_description_ar: Optional[str] = None
    project_description_en: Optional[str] = None

    # Counts
    no_of_lands: Optional[int] = None
    no_of_buildings: Optional[int] = None
    no_of_villas: Optional[int] = None
    no_of_units: Optional[int] = None

    # Relationships
    developer: Optional["Developer"] = Relationship(
        back_populates="projects_developed",
        sa_relationship_kwargs={"foreign_keys": "Project.developer_id"},
    )
    master_developer: Optional["Developer"] = Relationship(
        back_populates="projects_master",
        sa_relationship_kwargs={"foreign_keys": "Project.master_developer_id"},
    )
    area: Optional["Area"] = Relationship(back_populates="projects")
    land_registries: List["LandRegistry"] = Relationship(back_populates="project")
    buildings: List["Building"] = Relationship(back_populates="project")
    units: List["Unit"] = Relationship(back_populates="project")


# Property Hierarchy Tables


class LandRegistry(SQLModel, table=True):
    """Land parcels - base level of property hierarchy"""

    __tablename__: LiteralString = "land_registry"

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
    land_type_en: Optional[str] = Field(default=None, max_length=255)

    # Relationships
    area: Optional["Area"] = Relationship(back_populates="land_registries")
    project: Optional["Project"] = Relationship(back_populates="land_registries")
    master_project: Optional["MasterProject"] = Relationship(
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

    __tablename__: LiteralString = "buildings"

    # Primary key
    property_id: int = Field(primary_key=True)

    # Location
    area_id: Optional[int] = Field(
        default=None, foreign_key="areas.area_id", index=True
    )
    zone_id: Optional[int] = None
    land_number: Optional[str] = Field(default=None, max_length=50)
    land_sub_number: Optional[str] = Field(default=None, max_length=50)
    building_number: Optional[str] = Field(default=None, max_length=100)

    # Building characteristics
    floors: Optional[int] = None
    bld_levels: Optional[int] = None
    rooms: Optional[int] = None
    rooms_ar: Optional[str] = Field(default=None, max_length=100)
    rooms_en: Optional[str] = Field(default=None, max_length=100)
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
    project_id: Optional[int] = Field(
        default=None, foreign_key="projects.project_id", index=True
    )
    master_project_id: Optional[int] = Field(
        default=None, foreign_key="master_projects.master_project_id"
    )
    land_type_id: Optional[int] = None
    land_type_ar: Optional[str] = Field(default=None, max_length=255)
    land_type_en: Optional[str] = Field(default=None, max_length=255)

    # Relationships
    area: Optional["Area"] = Relationship(back_populates="buildings")
    parent_land: Optional["LandRegistry"] = Relationship(back_populates="buildings")
    project: Optional["Project"] = Relationship(back_populates="buildings")
    master_project: Optional["MasterProject"] = Relationship(back_populates="buildings")
    units: List["Unit"] = Relationship(back_populates="parent_building")


class Unit(SQLModel, table=True):
    """Individual units (apartments, offices, hotel rooms, etc.) - detail level of property hierarchy"""

    __tablename__: LiteralString = "units"

    # Primary key
    property_id: int = Field(primary_key=True)

    # Location
    area_id: Optional[int] = Field(
        default=None, foreign_key="areas.area_id", index=True
    )
    zone_id: Optional[int] = None
    land_number: Optional[str] = Field(default=None, max_length=100)
    land_sub_number: Optional[str] = Field(default=None, max_length=100)
    building_number: Optional[str] = Field(default=None, max_length=100)
    unit_number: Optional[str] = Field(default=None, max_length=100)
    floor: Optional[str] = Field(default=None, max_length=50)

    # Unit characteristics
    rooms: Optional[int] = None
    rooms_ar: Optional[str] = Field(default=None, max_length=100)
    rooms_en: Optional[str] = Field(default=None, max_length=100)

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
    parking_allocation_type_en: Optional[str] = Field(default=None, max_length=255)

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
    project_id: Optional[int] = Field(
        default=None, foreign_key="projects.project_id", index=True
    )
    master_project_id: Optional[int] = Field(
        default=None, foreign_key="master_projects.master_project_id"
    )
    land_type_id: Optional[int] = None
    land_type_ar: Optional[str] = Field(default=None, max_length=255)
    land_type_en: Optional[str] = Field(default=None, max_length=255)

    # Relationships
    area: Optional["Area"] = Relationship(back_populates="units")
    parent_building: Optional["Building"] = Relationship(back_populates="units")
    grandparent_land: Optional["LandRegistry"] = Relationship(back_populates="units")
    project: Optional["Project"] = Relationship(back_populates="units")
    master_project: Optional["MasterProject"] = Relationship(back_populates="units")
