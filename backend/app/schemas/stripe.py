from pydantic import BaseModel


class PaymentSyncResponse(BaseModel):
    """Payment sync response."""

    payment_completed: bool
    organization_id: str | None
    organization_status: str | None
    message: str
