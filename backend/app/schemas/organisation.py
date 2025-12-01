from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import datetime


class OrganisationCreateRequest(BaseModel):
    name: str
    domain: str
    max_users: int = 5


class OrganisationUpdateRequest(BaseModel):
    max_users: int
    is_active: bool


class OrganisationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    id: str
    name: str
    domain: str = Field(validation_alias="email_domain")
    max_users: int
    is_active: bool
    active_user_count: Optional[int] = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class OrganisationDetailResponse(BaseModel):
    organisation: OrganisationResponse
    users: List[dict]
