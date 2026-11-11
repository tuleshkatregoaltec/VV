"""PostgreSQL models for application state (not analytics data).

This module explicitly registers domain SQLModel classes for Alembic migrations. Runtime callers import models from their owning domains.
"""

from app.assistant_actions.models import (
    AssistantAction,
    AssistantListingDraft,
    AssistantOutbox,
    AssistantReminder,
    AssistantViewing,
)
from app.billing.models import Subscription
from app.chat.models import ChatTurnLease, Conversation, Message
from app.crm.audit_models import CrmMutationAudit
from app.crm.import_job_models import CrmImportJob
from app.crm.import_models import (
    CrmContactImport,
    CrmContactList,
    CrmOwnerAssessmentRevision,
    CrmOwnerNote,
    CrmOwnerWorkspace,
    CrmPropertyContactClaim,
)
from app.crm.inbound_models import (
    CrmInboundActivity,
    CrmInboundContact,
    CrmInboundEnquiry,
    CrmInboundImport,
    CrmInboundMatch,
    CrmInboundNote,
)
from app.crm.models import (
    CrmAgentAreaPreference,
    CrmCompanyListingSource,
    CrmLeadNote,
    CrmLeadWorkspace,
    CrmLicensedBroker,
    CrmSavedLead,
)
from app.feasibility.models import FeasibilitySavedStudy
from app.news.models import NewsArticle
from app.organization.models import Organization, OrganizationInvitation, OrganizationMembership
from app.token_usage.models import UserTokenUsage
from app.whatsapp.customer_models import (
    WhatsAppConnection,
    WhatsAppContact,
    WhatsAppCustomerMessage,
    WhatsAppCustomerThread,
    WhatsAppPublishedListing,
)
from app.whatsapp.models import WhatsAppTurn

__all__ = [
    "WhatsAppPublishedListing",
    "WhatsAppConnection",
    "WhatsAppContact",
    "WhatsAppCustomerThread",
    "WhatsAppCustomerMessage",
    "WhatsAppTurn",
    "AssistantAction",
    "AssistantListingDraft",
    "AssistantOutbox",
    "AssistantReminder",
    "AssistantViewing",
    # Auth & User Management
    "Organization",
    "OrganizationMembership",
    "OrganizationInvitation",
    "UserTokenUsage",
    # Billing
    "Subscription",
    # News
    "NewsArticle",
    # Chat
    "Conversation",
    "ChatTurnLease",
    "Message",
    # CRM
    "CrmMutationAudit",
    "CrmSavedLead",
    "CrmLeadWorkspace",
    "CrmLeadNote",
    "CrmAgentAreaPreference",
    "CrmLicensedBroker",
    "CrmImportJob",
    "CrmCompanyListingSource",
    "CrmContactImport",
    "CrmContactList",
    "CrmPropertyContactClaim",
    "CrmOwnerWorkspace",
    "CrmOwnerNote",
    "CrmOwnerAssessmentRevision",
    "CrmInboundImport",
    "CrmInboundContact",
    "CrmInboundEnquiry",
    "CrmInboundNote",
    "CrmInboundActivity",
    "CrmInboundMatch",
    # Feasibility
    "FeasibilitySavedStudy",
]
