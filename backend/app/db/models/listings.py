from typing import Any, LiteralString, TYPE_CHECKING
from decimal import Decimal
from sqlmodel import SQLModel
from datetime import date


class PropertyListing(SQLModel, table=True):

    __tablename__: LiteralString = "property_listings"

    id: Any # Temporarily, add actual id

    # Building/Unit data
    master_project: str

    # Data shown in transactions
    project_name: str
    building_name: str
    property_type: str # Land, Unit (flat for residential), Villa etc.
    property_sub_type: str # Store, office (only really used for commercial)
    rooms_description: str # Bedrooms as str (2 B/R, Studio...)  
    procedure_area: Decimal # Sq.ft.
    meter_sale_price: Decimal # Calculated or listed price/sq.ft.
    reg_type: str # Off-plan or resale

    # Extra fields not in transaction data
    service_charge: Decimal
    furnished: bool
    posted_date: date
    is_freehold: bool
    listing_description: str
    bathrooms: int
    listing_agency: str
    developer: str
    has_parking: bool
    link: str
    source_platform: str


    price: int 