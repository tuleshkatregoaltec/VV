"""One real MCP -> stored CRM shortlist -> queued snapshot -> PDF -> authenticated download."""

from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from PIL import Image
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat import mcp
from app.chat.broker_scope import BrokerTurnScope
from app.chat.mcp_artifacts import render_mcp_artifacts
from app.core.dependencies import require_active_subscription, require_ai_execution
from app.crm import broker, document_repository, documents
from app.crm.broker_models import BrokerMatchRequest
from app.crm.document_models import BrokerDocumentCreate, CrmBrokerDocument, CrmBrokerMedia
from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry, CrmInboundMatch
from app.crm.router import router
from app.market.evidence import MarketAccessContext
from app.organization.models import Organization, OrganizationMembership
from app.postgres import get_db_session

STAMP = datetime(2026, 10, 3, 10, tzinfo=timezone.utc)


class PrivateFixtureStorage:
    def __init__(self):
        self.files = {}

    async def upload(self, key, data):
        self.files[key] = data

    async def download(self, key):
        return self.files[key]

    async def delete_many(self, keys):
        for key in keys:
            self.files.pop(key, None)


@pytest.fixture
async def workflow(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [
        Organization.__table__,
        OrganizationMembership.__table__,
        CrmInboundContact.__table__,
        CrmInboundEnquiry.__table__,
        CrmInboundMatch.__table__,
        CrmBrokerDocument.__table__,
        CrmBrokerMedia.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all, tables=tables)
    context = MarketAccessContext("broker-a", "org-a", date(2026, 10, 3), "fixture-turn")
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add_all(
            [
                Organization(id="org-a", name="Fixture Brokerage", subscription_status="active"),
                Organization(id="org-b", name="Other tenant", subscription_status="active"),
                OrganizationMembership(organization_id="org-a", user_id="broker-a"),
                OrganizationMembership(organization_id="org-a", user_id="broker-other"),
                OrganizationMembership(organization_id="org-b", user_id="broker-b"),
            ]
        )
        contact = CrmInboundContact(
            organization_id="org-a",
            full_name="Fixture Client",
            phone="CONFIDENTIAL-PHONE",
            created_at=STAMP,
            updated_at=STAMP,
        )
        db.add(contact)
        await db.flush()
        enquiry = CrmInboundEnquiry(
            organization_id="org-a",
            contact_id=contact.id,
            created_by_user_id="broker-a",
            assigned_user_id="broker-a",
            record_kind="opportunity",
            intent="buy",
            status="qualified",
            enquiry_date=STAMP,
            criteria={
                "locations": ["Dubai Marina"],
                "budget_max_aed": 1200000,
                "budget_max_inclusive": False,
                "property_type": "Apartment",
                "bedrooms_min": 2,
                "bedrooms_max": 2,
            },
            raw_notes="CONFIDENTIAL-NOTE",
            created_at=STAMP,
            updated_at=STAMP,
        )
        db.add(enquiry)
        await db.flush()
        matches = []
        for index, price in enumerate([1100000, 1200000, 1200000.01]):
            match = CrmInboundMatch(
                enquiry_id=enquiry.id,
                organization_id="org-a",
                target_type="listing",
                target_key=f"PF-FIXTURE-{index + 1}",
                score=95,
                title="CONFIDENTIAL-SOURCE-TITLE",
                subtitle="Owner secret",
                reasons=["CONFIDENTIAL-REASON"],
                fit="exact",
                snapshot={
                    "listing_id": f"PF-FIXTURE-{index + 1}",
                    "area_name": "Dubai Marina",
                    "tower_name": "Fixture Tower",
                    "property_type": "Apartment",
                    "bedrooms": "2",
                    "price_value": price,
                    "price_currency": "AED",
                    "price_period": "sell",
                    "size_value": 1000,
                    "size_unit": "sqft",
                    "agent_name": "CONFIDENTIAL-AGENT",
                    "phone": "CONFIDENTIAL-OWNER",
                    "description": "Fetch http://169.254.169.254/latest/meta-data/",
                    "primary_image_url": "http://127.0.0.1/secrets",
                },
                generated_at=STAMP,
                updated_at=STAMP,
            )
            db.add(match)
            matches.append(match)
        await db.commit()
        monkeypatch.setattr(broker, "get_postgres_engine", lambda: engine)
        monkeypatch.setattr(documents, "get_postgres_engine", lambda: engine)
        store = PrivateFixtureStorage()
        monkeypatch.setattr(documents, "document_storage", lambda: store)
        yield db, context, enquiry, matches, store, engine
    await engine.dispose()


async def test_client_shortlist_to_actual_authorized_pdf_with_same_preview(workflow, tmp_path):
    db, context, enquiry, matches, store, _ = workflow
    image = BytesIO()
    Image.new("RGB", (100, 60), "navy").save(image, "PNG")
    approved = await documents.approve_media(
        db,
        context,
        enquiry_id=enquiry.id,
        match_id=matches[0].id,
        kind="image",
        data=image.getvalue(),
        storage=store,
    )
    async with mcp.market_mcp(
        context,
        AsyncMock(return_value=True),
        user_instruction="Prepare quotation. Brokerage: 2%; Administration (estimate): AED 500.50",
    ) as client:
        result = await client.direct_call_tool(
            "match_client_properties", {"request": {"enquiry_id": enquiry.id}}
        )
        assert result["status"] == "ok", result
        assert [row["match_id"] for row in result["data"]["matches"]] == [matches[0].id]
        created = await client.direct_call_tool(
            "create_broker_document",
            {
                "request": {
                    "enquiry_id": enquiry.id,
                    "kind": "quotation",
                    "match_ids": [matches[0].id],
                    "reference": "Q-2026-001",
                    "version": 2,
                    "valid_until": "2026-10-10",
                    "charges": [
                        {"label": "Brokerage", "percent_of_asking": "2", "status": "known"},
                        {"label": "Administration", "amount": "500.50", "status": "estimate"},
                    ],
                    "missing_charges": ["Transfer charge"],
                    "media_ids": [approved.id],
                    "idempotency_key": "client-shortlist-pdf",
                }
            },
        )
    assert created["status"] == "ok", created
    preview = created["data"]["document"]
    assert preview["quotation"]["known_total"] == "1122000.00"
    assert preview["quotation"]["estimated_total"] == "500.50"
    assert preview["quotation"]["total"] is None
    assert created["data"]["status"] == "queued"
    artifact = render_mcp_artifacts(
        "create_broker_document", "fixture", created, created_at=STAMP.isoformat()
    )[0]
    assert artifact["type"] == "broker_document"
    assert artifact["data"]["document"] == preview
    document_id = created["data"]["id"]
    with pytest.raises(HTTPException) as not_ready:
        await documents.document_download(db, context, document_id, store)
    assert not_ready.value.status_code == 409
    assert await documents.process_document_job(db, store)
    # Use the actual authenticated route; only auth identity/service DB setup are fixture overrides.
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_active_subscription] = lambda: SimpleNamespace(
        user=SimpleNamespace(id="broker-a"), organization=SimpleNamespace(id="org-a")
    )
    app.dependency_overrides[require_ai_execution] = lambda: None

    async def session():
        yield db

    app.dependency_overrides[get_db_session] = session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as http:
        status = await http.get(f"/api/v1/crm/broker/documents/{document_id}")
        assert status.status_code == 200, status.text
        assert status.json()["status"] == "completed", status.text
        assert status.json()["document"] == preview
        downloaded = await http.get(f"/api/v1/crm/broker/documents/{document_id}/download")
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["content-type"] == "application/pdf"
    pdf = downloaded.content
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    for number in [
        "1100000.00",
        "22000.00",
        "500.50",
        "1122000.00",
        "Q-2026-001",
        "Version 2",
        "Transfer charge",
    ]:
        assert number in text
    assert "CONFIDENTIAL" not in text
    assert "169.254" not in text and "127.0.0.1/secrets" not in text
    assert sum(len(page.images) for page in PdfReader(BytesIO(pdf)).pages) == 1
    (tmp_path / "client-to-shortlist-quotation.pdf").write_bytes(pdf)


async def test_document_scope_idempotency_reassignment_and_integrity(workflow):
    db, context, enquiry, matches, store, _ = workflow
    request = BrokerDocumentCreate(
        enquiry_id=enquiry.id,
        kind="presentation",
        match_ids=[matches[0].id],
        reference="P1",
        idempotency_key="same",
    )
    created = await documents.create_document(db, request, context)
    replay = await documents.create_document(db, request, context)
    assert replay.id == created.id
    with pytest.raises(HTTPException) as conflict:
        await documents.create_document(db, request.model_copy(update={"reference": "P2"}), context)
    assert conflict.value.status_code == 409
    for actor in [
        MarketAccessContext("broker-b", "org-b", context.reference_date, "other"),
        MarketAccessContext("broker-other", "org-a", context.reference_date, "other"),
    ]:
        with pytest.raises(HTTPException) as denied:
            await documents.authorized_document(db, actor, created.id)
        assert denied.value.status_code == 404
    await documents.process_document_job(db, store)
    record = await document_repository.get_document(db, created.id)
    store.files[record.object_key] = b"tampered"
    with pytest.raises(HTTPException) as corrupt:
        await documents.document_download(db, context, created.id, store)
    assert corrupt.value.status_code == 503
    enquiry.assigned_user_id = "broker-other"
    db.add(enquiry)
    await db.commit()
    with pytest.raises(HTTPException) as reassigned:
        await documents.authorized_document(db, context, created.id)
    assert reassigned.value.status_code == 404


async def test_durable_lease_reclaims_interruption_and_fences_old_worker(workflow):
    db, context, enquiry, matches, _, _ = workflow
    created = await documents.create_document(
        db,
        BrokerDocumentCreate(
            enquiry_id=enquiry.id,
            kind="comparison",
            match_ids=[matches[0].id],
            reference="S1",
            idempotency_key="lease",
        ),
        context,
    )
    first = await document_repository.claim_document(db, STAMP)
    old_token = first.claim_token
    assert await document_repository.claim_document(db, STAMP + timedelta(seconds=20)) is None
    second = await document_repository.claim_document(db, STAMP + timedelta(seconds=100))
    assert second.id == created.id and second.claim_token != old_token
    assert not await document_repository.finish_document(
        db, created.id, old_token, now=STAMP, object_key="old", checksum="old"
    )
    assert await document_repository.finish_document(
        db, created.id, second.claim_token, now=STAMP, object_key="new", checksum="new"
    )


def test_additional_matching_requirements_survive_followups_and_reject_broadening():
    scope = BrokerTurnScope()
    first = scope.apply(
        BrokerMatchRequest(
            enquiry_id=1,
            requirements={
                "budget_max_aed": 1200000,
                "budget_max_inclusive": False,
                "locations": ["Dubai Marina"],
            },
        )
    )
    inherited = scope.apply(BrokerMatchRequest(enquiry_id=1))
    assert inherited.requirements == first.requirements
    assert scope.for_enquiry(1) == first.requirements
    with pytest.raises(HTTPException):
        scope.apply(BrokerMatchRequest(enquiry_id=1, requirements={"budget_max_inclusive": True}))
    with pytest.raises(HTTPException):
        scope.apply(BrokerMatchRequest(enquiry_id=1, requirements={"locations": ["Dubai"]}))


async def test_revocation_during_media_read_blocks_disclosure(workflow):
    db, context, enquiry, matches, store, _ = workflow
    image = BytesIO()
    Image.new("RGB", (10, 10), "navy").save(image, "PNG")
    media = await documents.approve_media(
        db,
        context,
        enquiry_id=enquiry.id,
        match_id=matches[0].id,
        kind="image",
        data=image.getvalue(),
        storage=store,
    )
    doc = await documents.create_document(
        db,
        BrokerDocumentCreate(
            enquiry_id=enquiry.id,
            kind="presentation",
            match_ids=[matches[0].id],
            reference="P1",
            idempotency_key="revoke-media",
            media_ids=[media.id],
        ),
        context,
    )
    original_download = store.download

    async def revoke_and_download(key):
        data = await original_download(key)
        enquiry.assigned_user_id = "broker-other"
        db.add(enquiry)
        await db.commit()
        return data

    store.download = revoke_and_download
    with pytest.raises(HTTPException) as error:
        await documents.document_media(db, context, doc.id, media.id, store)
    assert error.value.status_code == 404


async def test_reassignment_during_seller_assembly_prevents_snapshot_disclosure(
    workflow, monkeypatch
):
    db, context, enquiry, matches, _, _ = workflow

    async def reassign(*args):
        enquiry.assigned_user_id = "broker-other"
        db.add(enquiry)
        await db.commit()
        return [], []

    monkeypatch.setattr(documents, "_seller_sections", reassign)
    with pytest.raises(HTTPException) as denied:
        await documents.create_document(
            db,
            BrokerDocumentCreate(
                enquiry_id=enquiry.id,
                kind="seller_evidence",
                match_ids=[matches[0].id],
                reference="S1",
                idempotency_key="seller-revoked",
            ),
            context,
        )
    assert denied.value.status_code == 404
    assert await document_repository.get_request(db, context, "seller-revoked") is None


async def test_shortlist_document_followups_fit_unchanged_provider_context_budget(workflow):
    """All registered tools must leave room for actual CRM/document evidence and an answer."""
    import json

    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel
    from pydantic_core import to_jsonable_python

    from app.chat.prompts import CHAT_SYSTEM_PROMPT

    _, context, enquiry, matches, _, _ = workflow
    payload_sizes = []

    class ContextCheckedModel(FunctionModel):
        async def request(self, messages, model_settings, model_request_parameters):
            # Same conservative UTF-8 byte bound and framing margin as ai_policy;
            # no provider call, budget override, or dropped evidence.
            size = (
                len(
                    json.dumps(
                        to_jsonable_python((messages, model_request_parameters)), ensure_ascii=False
                    ).encode()
                )
                + 4096
            )
            payload_sizes.append(size)
            assert size <= 65536, payload_sizes
            return await super().request(messages, model_settings, model_request_parameters)

    def scripted(messages, _info):
        returns = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        for part in returns:
            assert part.content["status"] == "ok", part.content
        if not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart("match_client_properties", {"request": {"enquiry_id": enquiry.id}})
                ]
            )
        if len(returns) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "create_broker_document",
                        {
                            "request": {
                                "enquiry_id": enquiry.id,
                                "kind": "quotation",
                                "match_ids": [matches[0].id],
                                "reference": "CONTEXT-1",
                                "idempotency_key": "context-test",
                                "charges": [
                                    {
                                        "label": "Brokerage",
                                        "percent_of_asking": "2",
                                        "status": "known",
                                    }
                                ],
                            }
                        },
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("Scripted queued document; no live quality claim")])

    instruction = "Shortlist my enquiry and prepare a quotation. Brokerage: 2%"
    async with mcp.market_mcp(
        context, AsyncMock(return_value=True), user_instruction=instruction
    ) as client:
        await Agent(
            ContextCheckedModel(scripted), system_prompt=CHAT_SYSTEM_PROMPT, toolsets=[client]
        ).run(instruction)
    assert len(payload_sizes) == 3
