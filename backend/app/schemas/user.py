from pydantic import BaseModel

class UserUpdateRequest(BaseModel):
    is_active: bool