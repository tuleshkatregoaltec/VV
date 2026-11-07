"""Multi-agent webhook intake: routing, blocked contacts, privacy and contact sync.

The repository is replaced by an in-memory store whose every flush/commit is
snapshotted, so the privacy tests can assert on what would be persisted at each
stage (not only the end state). The PostgreSQL suite repeats the key cases against
real tables.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.usage import RunUsage

from app.config import settings
from app.whatsapp import customer_agent
from app.whatsapp import customer_automation as automation
from app.whatsapp import customer_intake as intake
from app.whatsapp import customer_queue as queue
from app.whatsapp import customer_repository as repository
from app.whatsapp.customer_models import (
    WhatsAppConnection,
    WhatsAppContact,
    WhatsAppCustomerMessage,
    WhatsAppCustomerThread,
)
from app.whatsapp.models import utcnow

PERSONAL = "Dinner at mum's tonight? Bring the kids"
PROPERTY = "Is the 2 bedroom in Marina still available?"


class Store:
    def __init__(self):
        self.tables = {
            WhatsAppConnection: {},
            WhatsAppCustomerThread: {},
            WhatsAppCustomerMessage: {},
            WhatsAppContact: {},
        }
        self.snapshots: list[tuple[str, str]] = []

    def put(self, row):
        self.tables[type(row)][row.id] = row
        return row

    def all(self, table):
        return list(self.tables[table].values())

    def dump(self) -> str:
        return json.dumps(
            [
                row.model_dump(mode="json")
                for table in self.tables.values()
                for row in table.values()
            ],
            default=str,
        )

    def snapshot(self, stage):
        self.snapshots.append((stage, self.dump()))


class Session:
    def __init__(self, store):
        self.store = store
        self.added = []

    def add(self, row):
        self.added.append(row)
        self.store.put(row)

    async def flush(self):
        self.store.snapshot("flush")

    async def commit(self):
        self.store.snapshot("commit")

    async def rollback(self):
        pass

    async def delete(self, row):
        self.store.tables[type(row)].pop(row.id, None)


@pytest.fixture
def store(monkeypatch):
    store = Store()
    session = Session(store)
    store.session = session

    async def sessions():
        yield session

    monkeypatch.setattr(intake, "get_db_session", sessions)
    monkeypatch.setattr(automation, "get_db_session", sessions)

    def connections():
        return store.all(WhatsAppConnection)

    async def routed_connection(db, account_id, phone_number_id):
        return next(
            (
                c
                for c in connections()
                if c.account_id == account_id
                and c.phone_number_id == phone_number_id
                and c.status == "connected"
            ),
            None,
        )

    async def account_connections(db, account_id):
        return [c for c in connections() if c.account_id == account_id]

    def matches(contact, connection_id, wa_id, bsuid):
        return contact.connection_id == connection_id and (
            (wa_id and contact.wa_id == wa_id) or (bsuid and contact.bsuid == bsuid)
        )

    async def blocked_contact(db, connection_id, wa_id, bsuid):
        return any(
            c.blocked and matches(c, connection_id, wa_id, bsuid)
            for c in store.all(WhatsAppContact)
        )

    async def contact_for(db, connection_id, wa_id, bsuid):
        return next(
            (c for c in store.all(WhatsAppContact) if matches(c, connection_id, wa_id, bsuid)),
            None,
        )

    async def message_exists(db, message_id):
        return message_id in store.tables[WhatsAppCustomerMessage]

    async def daily_counts(db, connection_id, since):
        return {}

    async def thread_for_sender(db, connection_id, sender):
        return next(
            (
                t
                for t in store.all(WhatsAppCustomerThread)
                if t.connection_id == connection_id and t.sender == sender
            ),
            None,
        )

    async def has_property_messages(db, thread_id):
        return any(
            m.thread_id == thread_id and m.topic == "real_estate"
            for m in store.all(WhatsAppCustomerMessage)
        )

    async def messages(db, thread_id, **kwargs):
        return [m for m in store.all(WhatsAppCustomerMessage) if m.thread_id == thread_id]

    async def threads(db, connection_id, **kwargs):
        return [t for t in store.all(WhatsAppCustomerThread) if t.connection_id == connection_id]

    async def delete_contacts(db, connection_id):
        for contact in store.all(WhatsAppContact):
            if contact.connection_id == connection_id:
                del store.tables[WhatsAppContact][contact.id]

    async def lock_connection(db, connection_id, *args):
        return store.tables[WhatsAppConnection].get(connection_id)

    async def lock_thread(db, thread_id, connection_id):
        thread = store.tables[WhatsAppCustomerThread].get(thread_id)
        return thread if thread and thread.connection_id == connection_id else None

    async def lock_message(db, message_id, thread_id):
        message = store.tables[WhatsAppCustomerMessage].get(message_id)
        return message if message and message.thread_id == thread_id else None

    for name, fake in {
        "routed_connection": routed_connection,
        "account_connections": account_connections,
        "blocked_contact": blocked_contact,
        "contact_for": contact_for,
        "message_exists": message_exists,
        "daily_counts": daily_counts,
        "thread_for_sender": thread_for_sender,
        "has_property_messages": has_property_messages,
        "messages": messages,
        "threads": threads,
        "delete_contacts": delete_contacts,
        "lock_connection": lock_connection,
        "lock_thread": lock_thread,
        "lock_message": lock_message,
    }.items():
        monkeypatch.setattr(repository, name, fake)
    monkeypatch.setattr(queue, "history_for", AsyncMock(return_value=[]))
    monkeypatch.setattr(automation, "channel_access", AsyncMock(return_value=True))
    monkeypatch.setattr(automation, "create_customer_conversation", AsyncMock(return_value=7))
    monkeypatch.setattr(automation.customer_access, "valid_evidence", AsyncMock(return_value=True))
    return store


def config(**update):
    return settings.model_copy(
        update={
            "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": True,
            "WHATSAPP_APP_SECRET": "secret",
            "WHATSAPP_GRAPH_API_VERSION": "v25.0",
            "WHATSAPP_CUSTOMER_TEST_RECIPIENT": None,
            "WHATSAPP_CUSTOMER_PHONE_NUMBER_ID": None,
            "WHATSAPP_CUSTOMER_ACCOUNT_ID": None,
            "WHATSAPP_CUSTOMER_ACCESS_TOKEN": None,
            **update,
        }
    )


def agent(store, name, waba, phone, **kwargs):
    return store.put(
        WhatsAppConnection(
            user_id=f"user-{name}",
            organization_id=f"org-{name}",
            phone_number_id=phone,
            account_id=waba,
            display_name=name,
            access_token_encrypted="ciphertext",
            approved_knowledge=[{"id": "faq", "text": "Marina 2BR AED 2m."}],
            **{"enabled": True, **kwargs},
        )
    )


def message(body, sender="971500000001", message_id="wamid.1", **extra):
    return {
        "id": message_id,
        "from": sender,
        "type": "text",
        "text": {"body": body},
        "timestamp": str(int(utcnow().timestamp())),
        **extra,
    }


def change(phone, field="messages", **value):
    return {
        "field": field,
        "value": {"messaging_product": "whatsapp", "metadata": {"phone_number_id": phone}, **value},
    }


def event(*entries):
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": waba, "changes": changes} for waba, changes in entries],
    }


def draft(reply="Marina 2BR AED 2m."):
    return SimpleNamespace(
        reply=reply, risk="routine", evidence_ids=["faq"], auto_eligible=True, evidence_snapshots=[]
    )


async def test_blocked_sender_leaves_no_row_in_any_table_and_is_never_queued(
    store, monkeypatch, caplog
):
    connection = agent(store, "a", "waba-a", "phone-a")
    store.put(WhatsAppContact(connection_id=connection.id, wa_id="971500000001", blocked=True))
    store.put(WhatsAppContact(connection_id=connection.id, bsuid="AE.123", blocked=True))
    classify = AsyncMock(return_value=draft())
    monkeypatch.setattr(automation, "build_customer_draft", classify)
    before = store.dump()
    payload = event(
        (
            "waba-a",
            [
                change(
                    "phone-a",
                    messages=[
                        message(PERSONAL),
                        message(
                            PERSONAL, sender="971500000009", message_id="wamid.2", user_id="AE.123"
                        ),
                    ],
                )
            ],
        )
    )
    with caplog.at_level(logging.DEBUG):
        assert await intake.receive_customer(payload, config()) == 0
        await intake.drain()
    assert store.session.added == []
    assert store.all(WhatsAppCustomerThread) == []
    assert store.all(WhatsAppCustomerMessage) == []
    assert store.dump() == before
    assert all(PERSONAL not in dumped for _, dumped in store.snapshots)
    classify.assert_not_awaited()
    assert PERSONAL not in caplog.text


async def test_personal_message_content_is_never_persisted_at_any_stage(store, monkeypatch, caplog):
    agent(store, "a", "waba-a", "phone-a")
    seen_during_classification = []

    async def classify(**kwargs):
        # The model sees the text in memory while nothing durable holds it.
        assert kwargs["message"] == PERSONAL
        seen_during_classification.append(store.dump())
        return None

    monkeypatch.setattr(automation, "build_customer_draft", classify)
    with caplog.at_level(logging.DEBUG):
        queued = await intake.receive_customer(
            event(("waba-a", [change("phone-a", messages=[message(PERSONAL)])])), config()
        )
        assert queued == 1
        # Durable state after the webhook returns: a content-free receipt only.
        receipt = store.all(WhatsAppCustomerMessage)[0]
        assert receipt.content is None and receipt.status == "classifying"
        await intake.drain()
    assert seen_during_classification and PERSONAL not in seen_during_classification[0]
    assert store.snapshots, "intake must persist something to be meaningful"
    for stage, dumped in store.snapshots:
        assert PERSONAL not in dumped, stage
    final = store.all(WhatsAppCustomerMessage)[0]
    assert final.status == "ignored" and final.content is None and final.topic is None
    assert PERSONAL not in caplog.text


async def test_property_content_is_persisted_only_after_classification_admits_it(
    store, monkeypatch
):
    agent(store, "a", "waba-a", "phone-a")
    during = []

    async def classify(**kwargs):
        during.append(store.dump())
        return draft()

    monkeypatch.setattr(automation, "build_customer_draft", classify)
    await intake.receive_customer(
        event(("waba-a", [change("phone-a", messages=[message(PROPERTY)])])), config()
    )
    assert PROPERTY not in store.dump()
    await intake.drain()
    assert PROPERTY not in during[0]
    final = store.all(WhatsAppCustomerMessage)[0]
    assert final.content == PROPERTY
    assert final.topic == "real_estate" and final.status == "auto_pending"


async def test_admitted_enquiry_whose_draft_fails_reaches_the_agent_not_ignored(store, monkeypatch):
    """Real agent pipeline: the classifier admits the enquiry, the drafter fails."""

    @asynccontextmanager
    async def budget(**scope):
        yield RunUsage()

    async def classify(prompt, **kwargs):
        return SimpleNamespace(
            output={"topic": "property", "confidence": 0.99, "risk": "routine", "reason": "t"}
        )

    monkeypatch.setattr(customer_agent.settings, "ASSISTANT_ENABLED", True)
    monkeypatch.setattr(customer_agent.operations, "channel_budget", budget)
    monkeypatch.setattr(customer_agent, "classifier", lambda: SimpleNamespace(run=classify))
    failing = SimpleNamespace(run=AsyncMock(side_effect=RuntimeError("provider down")))
    monkeypatch.setattr(customer_agent, "drafter", lambda: failing)
    connection = agent(store, "a", "waba-a", "phone-a")
    await intake.receive_customer(
        event(("waba-a", [change("phone-a", messages=[message(PROPERTY)])])), config()
    )
    await intake.drain()
    final = store.all(WhatsAppCustomerMessage)[0]
    assert final.status == "approval_required", final.status
    assert final.topic == "real_estate" and final.content == PROPERTY
    assert final.handoff_summary == customer_agent.DRAFT_FAILED_SUMMARY
    assert final.notification_created_at is not None
    thread = store.all(WhatsAppCustomerThread)[0]
    assert thread.paused and thread.connection_id == connection.id


async def test_webhooks_route_to_the_owning_agent_by_phone_number_and_waba(store, monkeypatch):
    a = agent(store, "a", "waba-a", "phone-a")
    b = agent(store, "b", "waba-b", "phone-b")
    agent(store, "c", "waba-c", "phone-c", status="disconnected")
    calls = []

    async def classify(**kwargs):
        calls.append((kwargs["user_id"], kwargs["message"]))
        return None

    monkeypatch.setattr(automation, "build_customer_draft", classify)
    payload = event(
        ("waba-a", [change("phone-a", messages=[message("to a", message_id="m-a")])]),
        ("waba-b", [change("phone-b", messages=[message("to b", message_id="m-b")])]),
        # A phone number presented under someone else's WABA is not trusted.
        ("waba-a", [change("phone-b", messages=[message("spoof", message_id="m-x")])]),
        ("waba-z", [change("phone-z", messages=[message("unknown", message_id="m-z")])]),
        ("waba-c", [change("phone-c", messages=[message("gone", message_id="m-c")])]),
    )
    assert await intake.receive_customer(payload, config()) == 2
    await intake.drain()
    threads = {t.connection_id: t for t in store.all(WhatsAppCustomerThread)}
    assert set(threads) == {a.id, b.id}
    owners = {
        m.id: threads_id for m in store.all(WhatsAppCustomerMessage) for threads_id in [m.thread_id]
    }
    assert owners == {"m-a": threads[a.id].id, "m-b": threads[b.id].id}
    assert sorted(calls) == [("user-a", "to a"), ("user-b", "to b")]


async def test_automation_off_agent_receives_no_classification(store, monkeypatch):
    agent(store, "a", "waba-a", "phone-a", enabled=False)
    classify = AsyncMock()
    monkeypatch.setattr(automation, "build_customer_draft", classify)
    assert (
        await intake.receive_customer(
            event(("waba-a", [change("phone-a", messages=[message(PROPERTY)])])), config()
        )
        == 0
    )
    await intake.drain()
    assert store.all(WhatsAppCustomerMessage) == []
    classify.assert_not_awaited()


async def test_group_messages_are_ignored(store, monkeypatch):
    agent(store, "a", "waba-a", "phone-a")
    monkeypatch.setattr(automation, "build_customer_draft", AsyncMock())
    payload = event(
        ("waba-a", [change("phone-a", messages=[message(PROPERTY, group_id="120363")])])
    )
    assert await intake.receive_customer(payload, config()) == 0
    assert store.all(WhatsAppCustomerThread) == []


def state_sync(*items):
    return [
        {"type": "contact", "action": action, "contact": contact, "metadata": {"timestamp": "1"}}
        for action, contact in items
    ]


async def test_contact_state_sync_add_edit_remove_updates_contacts(store):
    connection = agent(store, "a", "waba-a", "phone-a")
    sync = lambda *items: event(  # noqa: E731
        ("waba-a", [change("phone-a", "smb_app_state_sync", state_sync=state_sync(*items))])
    )
    await intake.receive_customer(
        sync(
            (
                "add",
                {
                    "full_name": "Sara Buyer",
                    "first_name": "Sara",
                    "phone_number": "+971 50 111 2222",
                },
            ),
            ("add", {"full_name": "Mum", "phone_number": "971503334444", "user_id": "AE.9"}),
            ("add", {"full_name": "No number", "user_id": "AE.77"}),
        ),
        config(),
    )
    contacts = {c.wa_id or c.bsuid: c for c in store.all(WhatsAppContact)}
    assert set(contacts) == {"971501112222", "971503334444", "AE.77"}
    assert contacts["971501112222"].name == "Sara Buyer"
    assert contacts["971503334444"].bsuid == "AE.9"
    assert all(c.connection_id == connection.id for c in contacts.values())
    assert connection.contacts_synced_at is not None

    contacts["971503334444"].blocked = True
    await intake.receive_customer(
        sync(
            ("edit", {"full_name": "Sara B. (Marina)", "phone_number": "+971501112222"}),
            ("remove", {"phone_number": "+971501112222"}),
            ("remove", {"phone_number": "971503334444"}),
        ),
        config(),
    )
    remaining = {c.wa_id or c.bsuid: c for c in store.all(WhatsAppContact)}
    # Unblocked contacts are deleted on removal; a block survives the address book.
    assert set(remaining) == {"971503334444", "AE.77"}
    assert remaining["971503334444"].blocked and not remaining["971503334444"].in_address_book

    await intake.receive_customer(
        sync(("edit", {"full_name": "Mother", "user_id": "AE.9"})), config()
    )
    assert remaining["971503334444"].name == "Mother"
    assert remaining["971503334444"].in_address_book


async def test_state_sync_is_scoped_to_the_routed_agent(store):
    a = agent(store, "a", "waba-a", "phone-a")
    agent(store, "b", "waba-b", "phone-b")
    await intake.receive_customer(
        event(
            (
                "waba-b",
                [
                    change(
                        "phone-a",
                        "smb_app_state_sync",
                        state_sync=state_sync(("add", {"phone_number": "971501112222"})),
                    )
                ],
            )
        ),
        config(),
    )
    assert store.all(WhatsAppContact) == []
    assert a.contacts_synced_at is None


async def test_agent_echo_pauses_a_property_thread_without_storing_echo_content(store):
    connection = agent(store, "a", "waba-a", "phone-a")
    thread = store.put(WhatsAppCustomerThread(connection_id=connection.id, sender="971500000001"))
    store.put(
        WhatsAppCustomerMessage(
            id="earlier",
            thread_id=thread.id,
            content=PROPERTY,
            topic="real_estate",
            status="accepted",
            sent_at=utcnow(),
        )
    )
    pending = store.put(
        WhatsAppCustomerMessage(
            id="pending",
            thread_id=thread.id,
            content=PROPERTY,
            topic="real_estate",
            status="auto_pending",
            reply="draft",
            send_after=utcnow() + timedelta(seconds=30),
            sent_at=utcnow(),
        )
    )
    echo = {
        "from": "phone-a-display",
        "to": "971500000001",
        "id": "wamid.echo",
        "timestamp": str(int(utcnow().timestamp())),
        "type": "text",
        "text": {"body": "ECHO-PRIVATE I'll call you"},
    }
    other = {**echo, "to": "971509999999", "id": "wamid.echo2"}
    await intake.receive_customer(
        event(
            (
                "waba-a",
                [change("phone-a", "smb_message_echoes", message_echoes=[echo, other])],
            )
        ),
        config(),
    )
    assert thread.paused
    assert pending.status == "cancelled" and pending.reason == "agent_replied"
    assert len(store.all(WhatsAppCustomerThread)) == 1  # no thread for a personal chat
    assert all("ECHO-PRIVATE" not in dumped for _, dumped in store.snapshots)


async def test_echo_to_a_personal_thread_changes_nothing(store):
    connection = agent(store, "a", "waba-a", "phone-a")
    thread = store.put(WhatsAppCustomerThread(connection_id=connection.id, sender="971500000001"))
    store.put(
        WhatsAppCustomerMessage(id="m", thread_id=thread.id, status="ignored", sent_at=utcnow())
    )
    echo = {
        "to": "971500000001",
        "id": "wamid.echo",
        "timestamp": str(int(utcnow().timestamp())),
        "type": "text",
        "text": {"body": "see you"},
    }
    await intake.receive_customer(
        event(("waba-a", [change("phone-a", "smb_message_echoes", message_echoes=[echo])])),
        config(),
    )
    assert not thread.paused


async def test_agent_reply_during_classification_cancels_the_automated_answer(store, monkeypatch):
    # The buyer's first message is still being classified (no topic yet) when the agent
    # answers from the phone. The automation must not answer it a second time.
    agent(store, "a", "waba-a", "phone-a")
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_classify(**kwargs):
        started.set()
        await release.wait()
        return draft()

    monkeypatch.setattr(automation, "build_customer_draft", slow_classify)
    sent_at = utcnow() - timedelta(seconds=5)
    inbound = message(PROPERTY, timestamp=str(int(sent_at.timestamp())))
    assert (
        await intake.receive_customer(
            event(("waba-a", [change("phone-a", messages=[inbound])])), config()
        )
        == 1
    )
    await started.wait()
    echo = {
        "to": "971500000001",
        "id": "wamid.echo",
        "timestamp": str(int(utcnow().timestamp())),
        "type": "text",
        "text": {"body": "ECHO-PRIVATE yes still available"},
    }
    await intake.receive_customer(
        event(("waba-a", [change("phone-a", "smb_message_echoes", message_echoes=[echo])])),
        config(),
    )
    release.set()
    await intake.drain()
    receipt = store.tables[WhatsAppCustomerMessage]["wamid.1"]
    assert receipt.status == "cancelled" and receipt.reason == "agent_replied"
    assert receipt.content is None and receipt.reply is None and receipt.send_after is None
    assert all("ECHO-PRIVATE" not in dumped for _, dumped in store.snapshots)


async def test_echo_does_not_cancel_a_message_that_arrived_after_it(store):
    connection = agent(store, "a", "waba-a", "phone-a")
    thread = store.put(WhatsAppCustomerThread(connection_id=connection.id, sender="971500000001"))
    now = utcnow()
    before = store.put(
        WhatsAppCustomerMessage(
            id="before",
            thread_id=thread.id,
            status="classifying",
            sent_at=now - timedelta(minutes=1),
        )
    )
    after = store.put(
        WhatsAppCustomerMessage(
            id="after",
            thread_id=thread.id,
            status="classifying",
            sent_at=now + timedelta(minutes=1),
        )
    )
    echo = {"to": "971500000001", "id": "wamid.echo", "timestamp": str(int(now.timestamp()))}
    await intake.receive_customer(
        event(("waba-a", [change("phone-a", "smb_message_echoes", message_echoes=[echo])])),
        config(),
    )
    assert before.status == "cancelled" and after.status == "classifying"


async def test_one_failing_change_does_not_strand_receipts_committed_before_it(store, monkeypatch):
    agent(store, "a", "waba-a", "phone-a")
    agent(store, "b", "waba-b", "phone-b")
    classify = AsyncMock(return_value=draft())
    monkeypatch.setattr(automation, "build_customer_draft", classify)
    monkeypatch.setattr(
        intake.contacts, "apply_state_sync", AsyncMock(side_effect=RuntimeError("boom"))
    )
    payload = event(
        ("waba-a", [change("phone-a", messages=[message(PROPERTY)])]),
        ("waba-b", [change("phone-b", "smb_app_state_sync", state_sync=[])]),
        (
            "waba-b",
            [
                change(
                    "phone-b", messages=[message(PROPERTY, sender="971500000002", message_id="m3")]
                )
            ],
        ),
    )
    # The failure still surfaces, so Meta retries; committed receipts are deduplicated.
    with pytest.raises(RuntimeError):
        await intake.receive_customer(payload, config())
    await intake.drain()
    rows = store.tables[WhatsAppCustomerMessage]
    assert rows["wamid.1"].status == "auto_pending", "receipt before the failure was stranded"
    assert rows["m3"].status == "auto_pending", "receipt after the failure was not processed"
    assert classify.await_count == 2


async def test_partner_removed_disconnects_the_agent_and_deletes_the_token(store):
    connection = agent(store, "a", "waba-a", "phone-a")
    store.put(WhatsAppContact(connection_id=connection.id, wa_id="971501112222"))
    payload = event(
        (
            "waba-a",
            [
                {
                    "field": "account_update",
                    "value": {
                        "event": "PARTNER_REMOVED",
                        "disconnection_info": {"reason": "ACCOUNT_DISCONNECTED"},
                    },
                }
            ],
        )
    )
    await intake.receive_customer(payload, config())
    assert connection.status == "disconnected"
    assert connection.enabled is False
    assert connection.access_token_encrypted is None
    assert connection.last_account_event == "PARTNER_REMOVED"
    assert store.all(WhatsAppContact) == []
