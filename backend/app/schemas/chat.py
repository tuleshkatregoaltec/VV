"""Chat API Schemas - Pydantic models for request/response validation."""

from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


class CreateConversationRequest(BaseModel):
    """Request model for creating a new conversation"""

    title: Optional[str] = None


class ConversationResponse(BaseModel):
    """Response model for conversation data"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    """Response model for list of conversations"""

    conversations: List[ConversationResponse]
    total: int


class MessageResponse(BaseModel):
    """Response model for message data"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime
    tool_call_ids: Optional[List[int]] = None


class ToolCallResultResponse(BaseModel):
    """Response model for tool call result data"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tool_name: str
    tool_args: dict
    result: dict
    cached: bool
    execution_time_ms: Optional[int]
    created_at: datetime
