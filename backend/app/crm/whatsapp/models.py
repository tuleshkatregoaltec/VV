"""CRM › Connectors › WhatsApp (Meta WhatsApp Cloud API): sender numbers, messages, opt-outs.

Each agent sends from their own registered number, so a customer sees one chat per agent; one
campaign number is reserved for promotions. A conversation is the messages between one sender
number and one customer WhatsApp id (`wa_id`, digits only, as Meta sends it). Leads are matched to
a conversation by phone at read time; nothing here is copied onto the lead.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlmodel import JSON, Column, SQLModel
from sqlmodel import Field as SQLField

NumberPurpose = Literal["agent", "campaign"]
MessageStatus = Literal["queued", "sent", "delivered", "read", "failed"]


class CrmWhatsAppNumber(SQLModel, table=True):
    """A number registered under the business account, and who sends from it.

    The Phone Number ID is Meta's id for the number: every send goes to it, and every webhook says
    which one received, which is how a webhook finds its organization.
    """

    __tablename__ = "crm_whatsapp_numbers"
    __table_args__ = (
        UniqueConstraint("phone_number_id", name="uq_crm_whatsapp_number_phone_number_id"),
        # One active number per agent: a reply always leaves from the same number.
        Index(
            "uq_crm_whatsapp_number_agent",
            "organization_id",
            "user_id",
            unique=True,
            postgresql_where=text("active AND purpose = 'agent'"),
        ),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str = SQLField(index=True)
    phone_number_id: str
    display_number: str
    label: str
    purpose: str = SQLField(default="agent")
    # The agent who sends from it; None for the campaign number.
    user_id: str | None = SQLField(default=None, index=True)
    active: bool = True
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmWhatsAppMessage(SQLModel, table=True):
    """One message in or out on a sender number. `wamid` is Meta's message id: webhooks are
    delivered more than once, so it is unique and a repeat is ignored."""

    __tablename__ = "crm_whatsapp_messages"
    __table_args__ = (
        UniqueConstraint("wamid", name="uq_crm_whatsapp_message_wamid"),
        Index("ix_crm_whatsapp_messages_conversation", "number_id", "wa_id", "created_at"),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str = SQLField(index=True)
    number_id: int = SQLField(
        sa_column=Column(
            ForeignKey("crm_whatsapp_numbers.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    wa_id: str = SQLField(index=True)
    direction: str
    body: str = SQLField(sa_column=Column(Text, nullable=False))
    # None only for a send Meta refused, which never got an id.
    wamid: str | None = None
    template_name: str | None = None
    template_language: str | None = None
    # Outgoing only; moves forward only (see meta.STATUS_RANK).
    status: str | None = None
    error: str | None = SQLField(default=None, sa_column=Column(Text))
    contact_name: str | None = None
    sent_by_user_id: str | None = None
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmWhatsAppOptOut(SQLModel, table=True):
    """A customer who asked for no more WhatsApp messages from the organization (any number)."""

    __tablename__ = "crm_whatsapp_opt_outs"

    organization_id: str = SQLField(primary_key=True)
    wa_id: str = SQLField(primary_key=True)
    # What they sent: "STOP", "Stop promotions", ...
    reason: str
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


# ── API shapes (frontend: lib/crm/api/types.ts, Connectors › WhatsApp) ──


class WhatsAppStatusResponse(BaseModel):
    """Whether the signed-in user can message: the server is connected and they have a number."""

    configured: bool
    # WhatsApp is set up on the server, whether or not this user has a number yet.
    connected: bool
    business_name: str | None
    display_number: str | None


class WhatsAppTemplateResponse(BaseModel):
    name: str
    language: str
    category: Literal["marketing", "utility", "authentication"]
    review: Literal["approved", "pending", "rejected", "paused"]
    body: str


class WhatsAppMessageResponse(BaseModel):
    id: str
    direction: Literal["in", "out"]
    body: str
    at: datetime
    status: MessageStatus | None
    template: str | None
    error: str | None


class WhatsAppThreadResponse(BaseModel):
    wa_number: str | None
    opted_out: bool
    window_ends_at: datetime | None
    messages: list[WhatsAppMessageResponse]


class WhatsAppChatResponse(BaseModel):
    wa_id: str
    contact_name: str | None
    # The matched lead; stage, score and source come from the lead itself (Leads API).
    lead_id: int | None
    lead_name: str | None
    last_body: str
    last_direction: Literal["in", "out"]
    last_at: datetime
    window_ends_at: datetime | None
    unread: int


class WhatsAppTemplateSend(BaseModel):
    name: str = Field(min_length=1, max_length=512)
    language: str = Field(min_length=2, max_length=15)
    # Values for {{1}}, {{2}}, ... in order. {{1}} defaults to the contact's first name.
    params: list[str] = Field(default_factory=list, max_length=20)


class WhatsAppReply(BaseModel):
    body: str = Field(min_length=1, max_length=4096)


class WhatsAppSendResponse(BaseModel):
    ok: bool


class WhatsAppNumberWrite(BaseModel):
    display_number: str = Field(min_length=3, max_length=40)
    label: str = Field(min_length=1, max_length=120)
    purpose: NumberPurpose
    user_id: str | None = None
    active: bool = True


class WhatsAppNumberResponse(BaseModel):
    phone_number_id: str
    display_number: str
    label: str
    purpose: NumberPurpose
    user_id: str | None
    active: bool


class WhatsAppMetaNumber(BaseModel):
    """A number as Meta lists it under the business account (setup only)."""

    phone_number_id: str
    display_number: str
    verified_name: str | None
    quality_rating: str | None


# ── Campaigns (campaign number, organization owner) ──

CampaignStatus = Literal["sending", "completed"]
RecipientStatus = Literal["pending", "sending", "sent", "failed", "skipped", "unknown"]


class CrmWhatsAppCampaign(SQLModel, table=True):
    """One approved template sent once to each chosen, opted-in lead from the campaign number."""

    __tablename__ = "crm_whatsapp_campaigns"

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str = SQLField(index=True)
    number_id: int = SQLField(
        sa_column=Column(
            ForeignKey("crm_whatsapp_numbers.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    name: str
    template_name: str
    template_language: str
    template_body: str = SQLField(sa_column=Column(Text, nullable=False))
    # {{1}}, {{2}}… for every recipient; FIRST_NAME is replaced by each recipient's first name.
    params: list[str] = SQLField(default_factory=list, sa_column=Column(JSON, nullable=False))
    status: str = SQLField(default="sending")
    created_by_user_id: str
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    completed_at: datetime | None = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class CrmWhatsAppCampaignRecipient(SQLModel, table=True):
    """One person a campaign goes to. The row is the durable record of whether they were sent to:
    sending claims rows (pending → sending) so two servers never send to the same person, and a
    row left in `sending` by a crash becomes `unknown` rather than being sent twice."""

    __tablename__ = "crm_whatsapp_campaign_recipients"
    __table_args__ = (
        UniqueConstraint("campaign_id", "wa_id", name="uq_crm_whatsapp_campaign_recipient"),
        Index("ix_crm_whatsapp_campaign_recipients_queue", "campaign_id", "status"),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    campaign_id: int = SQLField(
        sa_column=Column(
            ForeignKey("crm_whatsapp_campaigns.id", ondelete="CASCADE"), nullable=False
        )
    )
    organization_id: str = SQLField(index=True)
    enquiry_id: int | None = SQLField(
        default=None,
        sa_column=Column(
            ForeignKey("crm_inbound_enquiries.id", ondelete="SET NULL"), nullable=True
        ),
    )
    wa_id: str
    name: str
    status: str = SQLField(default="pending")
    error: str | None = SQLField(default=None, sa_column=Column(Text))
    message_id: int | None = SQLField(
        default=None,
        sa_column=Column(
            ForeignKey("crm_whatsapp_messages.id", ondelete="SET NULL"), nullable=True
        ),
    )
    claimed_at: datetime | None = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class WhatsAppAudienceLead(BaseModel):
    id: int
    name: str
    wa_number: str
    intent: str
    source: str


class WhatsAppAudienceResponse(BaseModel):
    """Leads a campaign may go to, and how many were left out and why."""

    items: list[WhatsAppAudienceLead]
    no_consent: int
    opted_out: int
    no_number: int


class WhatsAppCampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    template_name: str = Field(min_length=1, max_length=512)
    language: str = Field(min_length=2, max_length=15)
    params: list[str] = Field(default_factory=list, max_length=20)
    enquiry_ids: list[int] = Field(min_length=1, max_length=5000)


class WhatsAppCampaignCounts(BaseModel):
    """Recipients by where sending got to, then sent messages by what Meta reported."""

    total: int = 0
    pending: int = 0
    sent: int = 0
    delivered: int = 0
    read: int = 0
    failed: int = 0
    skipped: int = 0
    unknown: int = 0
    replies: int = 0


class WhatsAppCampaignResponse(BaseModel):
    id: int
    name: str
    template_name: str
    template_language: str
    status: CampaignStatus
    created_at: datetime
    completed_at: datetime | None
    counts: WhatsAppCampaignCounts


class WhatsAppCampaignRecipientResponse(BaseModel):
    enquiry_id: int | None
    name: str
    wa_number: str
    # pending / sending / skipped / unknown, or the message's own status once sent.
    status: str
    error: str | None


class WhatsAppCampaignDetail(WhatsAppCampaignResponse):
    template_body: str
    params: list[str]
    recipients: list[WhatsAppCampaignRecipientResponse]
