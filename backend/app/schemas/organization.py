from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import datetime


class OrganizationCreateRequest(BaseModel):
    name: str
    domain: str
    max_users: int = 5


class OrganizationUpdateRequest(BaseModel):
    max_users: int
    is_active: bool


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    domain: str = Field(validation_alias="email_domain")
    max_users: int
    is_active: bool
    active_user_count: Optional[int] = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class OrganizationDetailResponse(BaseModel):
    organization: OrganizationResponse
    users: List[dict]
