"""Token Usage Schemas - Request/Response models for token usage endpoints"""

from pydantic import BaseModel


class UserTokenStatsResponse(BaseModel):
    """Token usage statistics for a user"""

    user_id: str
    tokens_used_today: int
    daily_limit: int
    usage_percentage: float
    remaining_tokens: int
