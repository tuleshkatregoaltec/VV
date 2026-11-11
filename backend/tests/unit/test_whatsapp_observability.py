"""Message text must not reach logs, Honeybadger or tracing, even when something fails."""

import hashlib
import hmac
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from honeybadger.config import Configuration
from honeybadger.notice import Notice
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.test import TestModel

from app.whatsapp import customer_agent as customer
from app.whatsapp import customer_intake as intake
from app.whatsapp import logging as whatsapp_logging
from app.whatsapp import router as webhook
from app.whatsapp.customer_queue import ClassificationJob

SECRET = "PRIVATE-BUYER-TEXT-8841"
WEBHOOK = "http://api.example.test/api/v1/webhooks/whatsapp"


def notice_for(exception, **context):
    return Notice(exception=exception, context=context, config=Configuration(api_key="x"))


def test_honeybadger_notice_for_a_webhook_failure_carries_no_request_or_message_data():
    error = RuntimeError(f"insert failed for {SECRET}")
    error.__cause__ = ValueError(f"cause mentions {SECRET}")
    notice = notice_for(
        error,
        url=WEBHOOK,
        method="POST",
        query_string=f"hub.verify_token={SECRET}&hub.challenge=1",
        headers={"x-hub-signature-256": SECRET, "cookie": SECRET},
        body={"entry": [{"changes": [{"value": {"messages": [{"text": {"body": SECRET}}]}}]}]},
        client=("203.0.113.9", 1),
    )
    scrubbed = whatsapp_logging.scrub_notice(notice)
    payload = json.dumps(scrubbed.payload, default=str)
    assert SECRET not in payload
    assert scrubbed.payload["error"]["class"] == "RuntimeError"
    assert scrubbed.payload["request"]["context"]["url"] == WEBHOOK


def test_other_honeybadger_notices_are_untouched():
    error = RuntimeError("ordinary failure")
    notice = notice_for(error, url="http://api.example.test/api/v1/news", query_string="q=1")
    scrubbed = whatsapp_logging.scrub_notice(notice)
    assert scrubbed is notice and scrubbed.exception is error
    assert scrubbed.context["query_string"] == "q=1"


def signed(payload: bytes) -> dict[str, str]:
    digest = hmac.new(b"test-app-secret", payload, hashlib.sha256).hexdigest()
    return {"x-hub-signature-256": "sha256=" + digest}


@pytest.fixture
async def client(monkeypatch):
    for name, value in {
        "WHATSAPP_DEMO_ENABLED": True,
        "WHATSAPP_AUTOMATION_ENABLED": False,
        "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": True,
        "WHATSAPP_VERIFY_TOKEN": "test-verify-token",
        "WHATSAPP_APP_SECRET": "test-app-secret",
        "WHATSAPP_PHONE_NUMBER_ID": "123",
    }.items():
        monkeypatch.setattr(webhook.settings, name, value)
    app = FastAPI()
    app.include_router(webhook.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def test_unexpected_webhook_failure_is_class_only_in_logs_and_honeybadger(
    client, monkeypatch, caplog
):
    reported = []
    monkeypatch.setattr(whatsapp_logging, "report_failure", reported.append)
    monkeypatch.setattr(webhook, "report_failure", reported.append)
    monkeypatch.setattr(
        webhook, "receive_customer", AsyncMock(side_effect=RuntimeError(f"db said {SECRET}"))
    )
    body = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()
    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            "/api/v1/webhooks/whatsapp", content=body, headers=signed(body)
        )
    assert response.status_code == 500 and SECRET not in response.text
    assert SECRET not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert [type(item).__name__ for item in reported] == ["RuntimeError"]


def test_failure_report_names_only_the_exception_class(monkeypatch):
    sent = []
    monkeypatch.setattr(whatsapp_logging.settings, "HONEYBADGER_API_KEY", "key")
    monkeypatch.setattr(
        whatsapp_logging.honeybadger, "notify", lambda **kwargs: sent.append(kwargs)
    )
    whatsapp_logging.report_failure(RuntimeError(f"db said {SECRET}"))
    assert sent == [
        {"error_class": "RuntimeError", "error_message": "WhatsApp webhook processing failed"}
    ]


@pytest.fixture
def offline_models(monkeypatch):
    monkeypatch.setattr(customer.settings, "ASSISTANT_ENABLED", True)
    monkeypatch.setattr(customer, "_classifier", None)
    monkeypatch.setattr(customer, "_drafter", None)
    monkeypatch.setattr(customer, "create_assistant_model", lambda role: TestModel())


def test_whatsapp_agents_never_emit_tracing_spans(offline_models):
    assert customer.classifier().instrument is False
    assert customer.drafter().instrument is False


@pytest.mark.parametrize("stage", ["classifier", "drafter"])
async def test_model_failure_never_logs_the_message_or_provider_payload(stage, monkeypatch, caplog):
    from contextlib import asynccontextmanager

    from pydantic_ai.usage import RunUsage

    @asynccontextmanager
    async def budget(**scope):
        yield RunUsage()

    monkeypatch.setattr(customer.settings, "ASSISTANT_ENABLED", True)
    monkeypatch.setattr(customer.operations, "channel_budget", budget, raising=False)
    decision = SimpleNamespace(
        output=customer.TopicDecision(
            topic="property", risk="routine", confidence=0.99, reason="ok"
        )
    )
    failing = AsyncMock(side_effect=RuntimeError(f"provider echoed {SECRET}"))
    ok = AsyncMock(return_value=decision)
    monkeypatch.setattr(
        customer,
        "classifier",
        lambda: SimpleNamespace(run=failing if stage == "classifier" else ok),
    )
    monkeypatch.setattr(customer, "drafter", lambda: SimpleNamespace(run=failing))
    with caplog.at_level(logging.DEBUG):
        await customer.build_customer_draft(
            message=f"How much is the villa? {SECRET}",
            knowledge=[{"id": "villa", "text": "The villa has a garden."}],
            history=[{"role": "user", "content": f"earlier {SECRET}"}],
            user_id="u",
            organization_id="o",
            conversation_id=1,
        )
    assert SECRET not in caplog.text
    assert all(record.exc_info is None and record.exc_text is None for record in caplog.records)
    assert "RuntimeError" in caplog.text


async def test_background_classification_failure_never_logs_the_message(monkeypatch, caplog):
    job = ClassificationJob("c", "t", "m", 1, f"Interested in {SECRET}")
    monkeypatch.setattr(
        intake.automation, "classify", AsyncMock(side_effect=RuntimeError(f"boom {SECRET}"))
    )
    with caplog.at_level(logging.DEBUG):
        await intake._run(job, SimpleNamespace(WHATSAPP_CLASSIFIER_CONCURRENCY=1))
    assert SECRET not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
