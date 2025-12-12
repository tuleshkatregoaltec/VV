from pydantic import BaseModel
from typing import List, Optional


class FilterOptionsResponse(BaseModel):
    projects: List[str] = []
    buildings: Optional[List[str]] = None  # Only for sales
    property_types: List[str] = []
    property_sub_types: List[str] = []
    master_projects: Optional[List[str]] = None  # Only when fetching all
    rooms: Optional[List[str]] = None  # Only for sales
    registration_types: Optional[List[str]] = None  # Only for sales
    tenant_types: Optional[List[str]] = None  # Only for rentals
    contract_reg_types: Optional[List[str]] = None  # Only for rentals
