"""CRM › Connectors › Email: emailing CRM leads, shared templates, and what happened to each send.

Recipients are leads of any type whose contact has an email (marketing, reports, general news).
Sends, templates and received emails live in a local JSON file (email_store), not in Postgres;
leads are only read from the database.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# A send only ever moves up this ladder (see brevo.STATUS_RANK).
EmailSendStatus = Literal[
    "queued",
    "sent",
    "deferred",
    "delivered",
    "opened",
    "clicked",
    "bounced",
    "spam",
    "unsubscribed",
    "failed",
    "replied",
]


class CrmEmailTemplate(BaseModel):
    """A reusable subject and message, shared by everyone in the organization."""

    id: int
    organization_id: str
    name: str
    subject: str
    body: str
    # Lead intents the template suits (buy, rent, sell, let, unknown); empty means every type.
    lead_types: list[str] = Field(default_factory=list)
    created_by_user_id: str
    updated_by_user_id: str
    created_at: datetime
    updated_at: datetime


class CrmEmailInbound(BaseModel):
    """An email received through Brevo inbound parsing, matched to a lead when possible."""

    id: int
    organization_id: str
    enquiry_id: int | None = None
    # The send this replies to, when the reply-to address or thread headers say so.
    send_id: int | None = None
    message_id: str | None = None
    from_email: str
    from_name: str | None = None
    to_email: str | None = None
    subject: str
    body: str
    # File names only; attachments are not stored.
    attachments: list[str] = Field(default_factory=list)
    created_lead: bool = False
    received_at: datetime
    created_at: datetime


class CrmEmailSend(BaseModel):
    """One email as it went out. Its id is the Brevo tag, so events find it exactly.

    `enquiry_id` is the lead; None for an email sent straight to an address (a test send).
    """

    id: int
    organization_id: str
    enquiry_id: int | None = None
    to_email: str
    to_name: str | None = None
    subject: str
    body: str
    sent_by_user_id: str
    message_id: str | None = None
    status: str = "queued"
    error: str | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    opened_at: datetime | None = None
    clicked_at: datetime | None = None
    bounced_at: datetime | None = None
    # [{event, at, link}] under the canonical event name, oldest first, never duplicated.
    events: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EmailStoreData(BaseModel):
    """Everything Connectors › Email keeps, in one JSON file (see email_store)."""

    sends: list[CrmEmailSend] = Field(default_factory=list)
    templates: list[CrmEmailTemplate] = Field(default_factory=list)
    inbound: list[CrmEmailInbound] = Field(default_factory=list)
    # Last id handed out per kind; ids are never reused, so a Brevo tag stays unique.
    last_ids: dict[str, int] = Field(default_factory=dict)
    # Organization -> normalized addresses; independent of deletable send history.
    suppressed_addresses: dict[str, list[str]] = Field(default_factory=dict)

    def next_id(self, kind: str) -> int:
        self.last_ids[kind] = self.last_ids.get(kind, 0) + 1
        return self.last_ids[kind]


class EmailStatusResponse(BaseModel):
    configured: bool
    sender_name: str | None
    sender_email: str | None
    webhook_configured: bool


class EmailLeadResponse(BaseModel):
    """A lead whose contact has an email, with how emailing it has gone so far."""

    id: int
    name: str
    email: str
    phone: str | None
    intent: str
    source: str
    status: str
    do_not_contact: bool
    last_status: str | None
    last_sent_at: datetime | None
    sends: int


class EmailLeadListResponse(BaseModel):
    items: list[EmailLeadResponse]
    total: int
    # Every source among the organization's emailable leads, for the Source filter.
    sources: list[str]


class EmailSendCreate(BaseModel):
    enquiry_ids: list[int] = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=300)
    # Plain text with {{name}}, {{first_name}}, {{email}} tokens.
    body: str = Field(min_length=1, max_length=20000)


class EmailSendResult(BaseModel):
    enquiry_id: int
    email: str
    ok: bool
    error: str | None = None


class EmailSendBatchResponse(BaseModel):
    sent: int
    failed: int
    results: list[EmailSendResult]


LeadIntent = Literal["unknown", "buy", "rent", "sell", "let"]


class EmailTemplateWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    # Empty: suits every lead type.
    lead_types: list[LeadIntent] = Field(default_factory=list, max_length=5)


class EmailTemplateResponse(BaseModel):
    id: int
    name: str
    subject: str
    body: str
    lead_types: list[str]
    updated_by_user_id: str
    updated_at: datetime


class EmailEvent(BaseModel):
    event: str
    at: datetime
    link: str | None = None


class EmailSendResponse(BaseModel):
    id: int
    enquiry_id: int | None
    to_email: str
    to_name: str | None
    subject: str
    body: str
    status: EmailSendStatus
    error: str | None
    sent_at: datetime | None
    delivered_at: datetime | None
    opened_at: datetime | None
    clicked_at: datetime | None
    bounced_at: datetime | None
    opens: int
    clicks: int
    events: list[EmailEvent]
    created_at: datetime


class EmailSendListResponse(BaseModel):
    items: list[EmailSendResponse]
    counts: dict[str, int]


class EmailInboundResponse(BaseModel):
    id: int
    enquiry_id: int | None
    lead_name: str | None
    send_id: int | None
    from_email: str
    from_name: str | None
    subject: str
    body: str
    attachments: list[str]
    created_lead: bool
    received_at: datetime


class EmailInboundListResponse(BaseModel):
    items: list[EmailInboundResponse]
    total: int


class EmailThreadItem(BaseModel):
    """One email on a lead, either way: `out` is a send from Vitevue, `in` a received email."""

    direction: Literal["out", "in"]
    id: int
    subject: str
    body: str
    at: datetime
    # Outbound only: where the send got to (sent, opened, replied…).
    status: str | None = None
    counterpart: str


class EmailSyncResponse(BaseModel):
    fetched: int
    applied: int
    unmatched: int
