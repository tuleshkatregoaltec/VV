from typing import Optional, List, LiteralString
from sqlmodel import SQLModel, Field, Relationship

class PropertyType(SQLModel, table=True):
    """Property type classifications (Land, Building, Unit, Villa, etc.)"""

    __tablename__: LiteralString = "property_types"

    # Primary key
    property_type_id: int = Field(primary_key=True)
    property_type_ar: str = Field(max_length=255)
    property_type: str = Field(max_length=255)

    # Relationships
    sub_types: List["PropertySubType"] = Relationship(back_populates="property_type")


class PropertySubType(SQLModel, table=True):
    """Detailed property classifications (Apartment, Office, Retail, Warehouse, etc.)"""

    __tablename__: LiteralString = "property_sub_types"

    # Primary key
    property_sub_type_id: int = Field(primary_key=True)
    property_type_id: int = Field(foreign_key="property_types.property_type_id")
    property_sub_type_ar: str = Field(max_length=255)
    property_sub_type: str = Field(max_length=255)

    # Relationships
    property_type: Optional["PropertyType"] = Relationship(back_populates="sub_types")
