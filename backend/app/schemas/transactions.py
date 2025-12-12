from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from decimal import Decimal
from datetime import date


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    transaction_id: str
    project_name_en: Optional[str] = None
    building_name_en: Optional[str] = None
    property_type_en: Optional[str] = None
    property_sub_type_en: Optional[str] = None
    rooms_en: Optional[str] = None
    procedure_area: Optional[Decimal] = None
    actual_worth: Optional[Decimal] = None
    meter_sale_price: Optional[Decimal] = None
    reg_type_en: Optional[str] = None
    instance_date: Optional[date] = None

    area_name_en: Optional[str] = None


class TransactionListResponse(BaseModel):
    transactions: List[TransactionResponse]
    total: int
    limit: int
    offset: int


class RentalContractResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    contract_id: str
    project_name_en: Optional[str] = None
    ejari_property_type_en: Optional[str] = None
    ejari_property_sub_type_en: Optional[str] = None
    tenant_type_en: Optional[str] = None
    actual_area: Optional[Decimal] = None
    annual_amount: Optional[Decimal] = None
    contract_reg_type_en: Optional[str] = None
    contract_start_date: Optional[date] = None
    area_name_en: Optional[str] = None


class RentalContractListResponse(BaseModel):
    contracts: List[RentalContractResponse]
    total: int
    limit: int
    offset: int
