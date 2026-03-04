from typing import Optional
from pydantic import BaseModel


class LandPlot(BaseModel):
    property_id: int
    land_number: Optional[str]
    area_name_en: str
    actual_area: float
    property_type_en: Optional[str]
    is_free_hold: Optional[bool]
    project_name_en: Optional[str]


class UnitTypeData(BaseModel):
    type: str
    count: int
    percentage: float
    avg_size_sqm: float
    avg_price_sqm: Optional[float]


class ComparableData(BaseModel):
    project_id: int
    project_name: str
    area_name: str
    no_of_buildings: int
    avg_floors: Optional[float]
    unit_mix: list[UnitTypeData]
    price_per_sqm_by_type: dict[str, float]


class FeasibilityChatRequest(BaseModel):
    messages: list[dict]
    context: dict
    history_json: str | None = None
