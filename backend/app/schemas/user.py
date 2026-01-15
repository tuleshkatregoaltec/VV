from typing import Optional

from pydantic import BaseModel


class UserUpdateRequest(BaseModel):
    is_active: Optional[bool] = None
    daily_token_limit: Optional[int] = None
