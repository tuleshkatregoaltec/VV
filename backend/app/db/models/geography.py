from typing import Optional, List, LiteralString, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from .properties import LandRegistry, Building, Unit, Project
    from .transactions import Transaction, RentContract

class MasterProject(SQLModel, table=True):
    """Large development complexes (Dubai Marina, Business Bay, DAMAC Hills, etc.)"""

    __tablename__: LiteralString = "master_projects"

    # Primary key
    master_project_id: int = Field(primary_key=True)
    master_project_name_ar: Optional[str] = Field(default=None, max_length=255)
    master_project_name: Optional[str] = Field(default=None, max_length=255)

    # Relationships
    land_registries: List["LandRegistry"] = Relationship(
        back_populates="master_project"
    )
    buildings: List["Building"] = Relationship(back_populates="master_project")
    units: List["Unit"] = Relationship(back_populates="master_project")


class Area(SQLModel, table=True):
    """Geographic areas and districts (Dubai Marina, Downtown Dubai, Jumeirah, etc.)"""

    __tablename__: LiteralString = "areas"

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
