from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class OrganisationCreateRequest(BaseModel):
    name: str
    domains: List[str]
    max_users: int = 5


class OrganisationUpdateRequest(BaseModel):
    max_users: int
    is_active: bool


class OrganisationResponse(BaseModel):
    id: str
    name: str
    email_domain: str
    max_users: int
    is_active: bool
    active_user_count: Optional[int] = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class OrganisationDetailResponse(BaseModel):
    organisation: OrganisationResponse
    users: List[dict]
