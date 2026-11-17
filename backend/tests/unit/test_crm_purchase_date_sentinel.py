"""A lease with no matched sale has no purchase date, not 1 January 1970.

The lease query left-joins sale matches; a lease without a match gets the Date column's zero
value, 1970-01-01. Live, 498 of 500 Leads rows showed it and it was copied into the lease
snapshot of every lead opened from the feed.
"""

from datetime import date
from unittest.mock import AsyncMock

from test_crm_service import _lead_row

from app.crm import renewal_leads
from app.crm.models import CrmLead
from app.crm.opportunities import _lead_from_row


def test_the_zero_date_of_an_unmatched_lease_is_no_purchase_date():
    lead = _lead_from_row(_lead_row(last_purchase_date=date(1970, 1, 1)))
    assert lead.last_purchase_date is None


def test_a_saved_snapshot_with_the_zero_date_reads_as_no_purchase_date():
    lead = _lead_from_row(_lead_row(last_purchase_date=date(2022, 1, 24)))
    snapshot = lead.model_dump(mode="json") | {"last_purchase_date": "1970-01-01"}
    assert CrmLead.model_validate(snapshot).last_purchase_date is None
    assert CrmLead.model_validate(lead.model_dump()).last_purchase_date == date(2022, 1, 24)


async def test_opening_a_lead_does_not_store_the_zero_date(monkeypatch):
    lead = _lead_from_row(_lead_row(unit_number="101", last_purchase_date=date(1970, 1, 1)))
    detail = type("Detail", (), {"lead": lead})()
    monkeypatch.setattr(renewal_leads, "get_lead_detail", AsyncMock(return_value=detail))
    monkeypatch.setattr(renewal_leads, "_owners_by_candidate", AsyncMock(return_value={}))
    opened = AsyncMock(return_value="opened")
    monkeypatch.setattr(renewal_leads.inbound, "open_vitevue_lease_enquiry", opened)
    await renewal_leads.open_renewal_lead(None, lease_id="e1", user_id="u", organization_id="o")
    assert opened.await_args.kwargs["lease"]["last_purchase_date"] is None
