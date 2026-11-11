"""The Offer lead stage (11 Nov 2026).

Moving a lead to Offer used to fail before anything was sent: the backend had no "offer" status,
and the CRM showed "The server had a problem". Offer sits between Viewing and Won.
"""

from app.crm.inbound_models import InboundEnquiryUpdate
from app.crm.inbound_policy import _QUALIFIED_STATUSES


def test_offer_is_a_status_a_lead_can_move_to():
    assert InboundEnquiryUpdate(status="offer").status == "offer"


def test_a_lead_at_offer_still_counts_as_qualified():
    # Matching and the qualified counts keep a lead that has an offer on the table.
    assert "offer" in _QUALIFIED_STATUSES
