from pydantic import BaseModel

class ChatMessageResponse(BaseModel):
    id: str
    object: str
    created_at: int
    status: str
    error: str