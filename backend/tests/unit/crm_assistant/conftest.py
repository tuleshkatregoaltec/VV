"""Fixtures for CRM Assistant unit tests."""

import pytest
from assistant_helpers import FakeLeads


@pytest.fixture
def fake_leads(monkeypatch):
    from app.crm.assistant import actions
    from app.crm.assistant.tools import leads as tools

    fake = FakeLeads()
    monkeypatch.setattr(tools.inbound_repository, "get_crm_inbound_enquiry", fake.get_row)
    monkeypatch.setattr(tools, "get_inbound_enquiry", fake.get_response)
    monkeypatch.setattr(actions, "get_inbound_enquiry", fake.get_response)
    monkeypatch.setattr(tools, "list_renewal_leads", fake.lease_leads)
    monkeypatch.setattr(tools, "list_inbound_enquiries", fake.list)
    return fake
