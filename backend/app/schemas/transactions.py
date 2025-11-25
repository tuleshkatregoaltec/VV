from pydantic import BaseModel
from typing import Optional, List, ClassVar
from decimal import Decimal
from datetime import date


class NumericRange(BaseModel):
    min: Optional[Decimal] = None
    max: Optional[Decimal] = None


class TransactionResponse(BaseModel):
    model_config: ClassVar[dict] = {"from_attributes": True}

    transaction_id: str
    project_name: Optional[str] = None
    building_name: Optional[str] = None
    property_type: Optional[str] = None
    property_sub_type: Optional[str] = None
    rooms_description: Optional[str] = None
    procedure_area: Optional[Decimal] = None
    actual_worth: Optional[Decimal] = None
    meter_sale_price: Optional[Decimal] = None
    reg_type: Optional[str] = None
    instance_date: Optional[date] = None

    area_name: Optional[str] = None


class TransactionListResponse(BaseModel):
    transactions: List[TransactionResponse]
    total: int
    limit: int
    offset: int


class RentalContractResponse(BaseModel):
    model_config: ClassVar[dict] = {"from_attributes": True}

    contract_id: str
    project_name: Optional[str] = None
    ejari_property_type: Optional[str] = None
    ejari_property_sub_type: Optional[str] = None
    tenant_type: Optional[str] = None
    actual_area: Optional[Decimal] = None
    annual_amount: Optional[Decimal] = None
    contract_reg_type: Optional[str] = None
    contract_start_date: Optional[date] = None


class RentalContractListResponse(BaseModel):
    contracts: List[RentalContractResponse]
    total: int
    limit: int
    offset: int


class FilterOptionsResponse(BaseModel):
    projects: List[str]
    buildings: Optional[List[str]] = None
    property_types: List[str]
    property_sub_types: List[str]
    # for sales
    rooms: Optional[List[str]] = None
    registration_types: Optional[List[str]] = None
    price_range: Optional[NumericRange] = None
    price_per_sqft_range: Optional[NumericRange] = None
    # for rentals
    tenant_types: Optional[List[str]] = None
    contract_reg_types: Optional[List[str]] = None
    annual_rent_range: Optional[NumericRange] = None
    # shared
    area_range: NumericRange
