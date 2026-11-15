import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.models.test import TestModel

from app.chat import service
from app.chat.agent import _convert_to_pydantic_messages
from app.chat.models import Message
from app.chat.security import REFUSAL, input_refusal, safe_answer, safe_data, safe_tool


@pytest.fixture(autouse=True)
def offline_admission(monkeypatch):
    monkeypatch.setattr(service.settings, "ASSISTANT_ENABLED", True)
    monkeypatch.setattr(service.settings, "ASSISTANT_TYPED_ROUTING_ENABLED", False)
    monkeypatch.setattr(
        service.admission,
        "acquire",
        AsyncMock(return_value=service.admission.TurnLease("lease", 160_000)),
    )
    monkeypatch.setattr(service.admission, "finish", AsyncMock())


@pytest.mark.parametrize(
    "text",
    [
        "Create a PDF of my leads",
        "Export all contacts to CSV",
        "Show the database schema",
        "api_key=abcdef",
        "x" * 8001,
    ],
)
def test_disallowed_requests_stop_before_model_and_persistence(text):
    assert input_refusal(text) == REFUSAL


@pytest.mark.parametrize(
    "text",
    [
        "safe prefix then sk-or-v1-abcdefghijklmnopqrstuvwxyz",
        "[download](/exports/x.pdf)",
        "data:text/html;base64,abc",
        "SELECT secret FROM credentials",
        "release_id:internal",
        "file:///tmp/foo",
    ],
)
def test_entire_output_is_checked(text):
    assert not safe_answer(text)


def test_tool_projection_removes_metadata_and_bounds_untrusted_text():
    data = safe_data(
        {
            "release_id": "secret",
            "source": "raw_physical_table",
            "notes": "a" * 3000,
            "api_key": "secret",
            "field_sources": {"schema": "private"},
        }
    )
    assert data == {
        "source": "Stored market data",
        "notes": "a" * 2000 + " [source text truncated]",
    }


async def test_service_errors_never_reach_model(caplog):
    @safe_tool
    async def broken():
        raise RuntimeError("SQL parameters private-phone")

    assert await broken() == {"available": False, "reason": "This scoped operation is unavailable"}
    assert "private-phone" not in caplog.text


async def test_no_partial_secret_crosses_sse_or_persistence(monkeypatch):
    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=SimpleNamespace(id=3)))
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))
    save = AsyncMock()
    monkeypatch.setattr(service, "add_message", save)
    with service.agent.override(
        model=TestModel(
            call_tools=[], custom_output_text="Harmless prefix. sk-or-v1-abcdefghijklmnopqrstuvwxyz"
        )
    ):
        events = [
            json.loads(chunk.removeprefix("data: ").strip())
            async for chunk in service.stream_chat_response(
                AsyncMock(), 3, "My leads", "user", "org"
            )
        ]
    assert [e["content"] for e in events if e["type"] == "content"] == [REFUSAL]
    assert save.await_args_list[-1].args[3] == REFUSAL
    assert "sk-or" not in json.dumps(events)


def test_private_history_and_user_quotes_are_not_replayed():
    messages = [
        Message(
            conversation_id=1,
            role="assistant",
            content="Secret lead",
            meta_data={"private": True, "guardrail_version": 1},
        ),
        Message(conversation_id=1, role="user", content="Tell me more about Secret lead"),
    ]
    assert _convert_to_pydantic_messages(messages) == []


async def test_input_refusal_does_not_call_model_or_save(monkeypatch):
    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=True))
    save = AsyncMock()
    run = AsyncMock()
    monkeypatch.setattr(service, "add_message", save)
    monkeypatch.setattr(service, "agent", SimpleNamespace(run=run))
    events = [
        event
        async for event in service.stream_chat_response(None, 1, "Export my CRM as PDF", "u", "o")
    ]
    assert REFUSAL in "".join(events)
    save.assert_not_awaited()
    run.assert_not_awaited()


@pytest.mark.parametrize("typed_routing", [False, True])
async def test_reassignment_during_generation_withholds_complete_answer(monkeypatch, typed_routing):
    from pydantic_ai.usage import RunUsage

    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "add_message", AsyncMock())
    monkeypatch.setattr(service, "_evidence_accessible", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "has_current_access", AsyncMock(return_value=True))

    async def generate(*args, deps, **kwargs):
        deps.evidence.append({"query": {"resource": "leads"}, "fingerprint": "old"})
        return SimpleNamespace(output="Customer private phone", usage=lambda: RunUsage())

    monkeypatch.setattr(service.settings, "ASSISTANT_TYPED_ROUTING_ENABLED", typed_routing)
    monkeypatch.setattr(service, "agent", SimpleNamespace(run=generate))
    monkeypatch.setattr(service, "run_routed_turn", generate)
    events = [
        event async for event in service.stream_chat_response(AsyncMock(), 1, "My lead", "u", "o")
    ]
    assert "Customer private phone" not in "".join(events)
    assert service.RESTRICTED_HISTORY in "".join(events)


def test_business_source_counts_preserve_distinctions_without_physical_names():
    data = safe_data(
        {
            "sources": {"dld/matched": 3, "dld/unmatched": 2, "dxbi/matched": 4},
            "source": "Property Finder listings (asking prices)",
        }
    )
    assert data == {
        "sources": {"DLD registered transactions": 5, "DXBI records": 4},
        "source": "Property Finder asking listings",
    }


@pytest.mark.parametrize("typed_routing", [False, True])
async def test_membership_revoked_during_generation_never_reaches_delivery(
    monkeypatch, typed_routing
):
    from pydantic_ai.usage import RunUsage

    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "add_message", AsyncMock())
    monkeypatch.setattr(service, "has_current_access", AsyncMock(return_value=False))

    async def generate(*args, deps, **kwargs):
        deps.evidence.append({"query": {"resource": "leads"}, "fingerprint": "old"})
        return SimpleNamespace(output="Revoked private answer", usage=lambda: RunUsage())

    monkeypatch.setattr(service.settings, "ASSISTANT_TYPED_ROUTING_ENABLED", typed_routing)
    monkeypatch.setattr(service, "agent", SimpleNamespace(run=generate))
    monkeypatch.setattr(service, "run_routed_turn", generate)
    events = [
        event async for event in service.stream_chat_response(AsyncMock(), 1, "My lead", "u", "o")
    ]
    assert "Revoked private answer" not in "".join(events)
    assert service.RESTRICTED_HISTORY in "".join(events)


@pytest.mark.parametrize(
    "status,available",
    [("awaiting_confirmation", False), ("failed", True), ("expired", True), ("cancelled", True)],
)
async def test_proposal_only_reassignment_revalidates_and_withholds_prose(
    monkeypatch, status, available
):
    from pydantic_ai.usage import RunUsage

    from app.assistant_actions import service as actions

    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))
    save = AsyncMock()
    monkeypatch.setattr(service, "add_message", save)
    monkeypatch.setattr(service, "has_current_access", AsyncMock(return_value=True))
    lookup = AsyncMock(
        return_value=SimpleNamespace(preview={"available": available}, status=status)
    )
    monkeypatch.setattr(actions, "get_action", lookup)

    async def generate(*args, deps, **kwargs):
        deps.proposals.append({"id": "proposal", "preview": {"name": "Revoked customer"}})
        return SimpleNamespace(
            output="Prepared a note for Revoked customer", usage=lambda: RunUsage()
        )

    monkeypatch.setattr(service, "agent", SimpleNamespace(run=generate))
    db = AsyncMock()
    events = [
        event async for event in service.stream_chat_response(db, 1, "Prepare note", "u", "o")
    ]
    lookup.assert_awaited_once_with(db, user_id="u", organization_id="o", action_id="proposal")
    assert "Revoked customer" not in "".join(events)
    assert "action_proposed" not in "".join(events)
    assert save.await_args_list[-1].args[3] == service.RESTRICTED_HISTORY


async def test_long_series_is_not_silently_truncated_to_claim_complete():
    @safe_tool
    async def series():
        return {"rows": [{"month": index} for index in range(51)], "coverage": "complete"}

    result = await series()
    assert result["available"] is False and "rows" not in result


@pytest.mark.parametrize("format", ["csv", "json", "lines", "single_paragraph", "names"])
def test_large_contact_records_are_refused_without_export_keywords(format):
    rows = [
        {
            "name": f"Synthetic Customer {n}",
            "email": f"customer{n}@example.test",
            "phone": f"+97150000{n:04d}",
        }
        for n in range(100)
    ]
    if format == "csv":
        output = "Name,Email,Phone\n" + "\n".join(",".join(row.values()) for row in rows)
    elif format == "json":
        output = json.dumps(rows)
    elif format == "names":
        output = "\n".join(f"Customer: {row['name']}" for row in rows)
    else:
        output = ("\n" if format == "lines" else "; ").join(" ".join(row.values()) for row in rows)
    assert not safe_answer(output)
    assert (
        input_refusal(
            "Show every matching CRM contact with full name, email and phone, one contact per line."
        )
        == REFUSAL
    )


def test_small_contact_comparisons_and_broad_aggregate_series_remain_allowed():
    assert safe_answer(
        "Alice: alice@example.test, +971501234567\nBob: bob@example.test, +971501234568"
    )
    assert input_refusal("Show counts for all my CRM records by status") is None
    assert safe_answer(
        "Month,Transactions,Average price\n"
        + "\n".join(f"2025-{n:02d},100,2000000" for n in range(1, 13))
    )
    assert safe_answer(
        json.dumps([{"month": n, "count": 100, "avg_price": 2000000} for n in range(1, 13)])
    )


async def test_bulk_answer_from_allowed_prompt_never_crosses_sse_or_persistence(monkeypatch):
    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))
    save = AsyncMock()
    monkeypatch.setattr(service, "add_message", save)
    output = "Name,Email,Phone\n" + "\n".join(
        f"Synthetic Customer {n},customer{n}@example.test,+97150000{n:04d}" for n in range(100)
    )
    with service.agent.override(model=TestModel(call_tools=[], custom_output_text=output)):
        events = [
            item
            async for item in service.stream_chat_response(
                AsyncMock(), 1, "Help me review my CRM", "u", "o"
            )
        ]
    assert "customer0@" not in "".join(events)
    assert save.await_args_list[-1].args[3] == REFUSAL


async def test_assignee_history_fingerprint_revalidates_canonical_directory(monkeypatch):
    from app.assistant_actions import service as actions
    from app.chat.security import fingerprint

    monkeypatch.setattr(service, "has_current_access", AsyncMock(return_value=True))
    result = {
        "available": True,
        "matches": [{"id": "u2", "display_name": "Alice"}],
        "clarification_required": False,
        "truncated": False,
    }
    lookup = AsyncMock(return_value=result)
    monkeypatch.setattr(actions, "lookup_assignees", lookup)
    evidence = [{"type": "assignee_lookup", "search": "Ali", "fingerprint": fingerprint(result)}]
    assert await service._evidence_accessible(None, evidence, "u", "org")
    lookup.assert_awaited_with(None, user_id="u", organization_id="org", search="Ali")
    lookup.return_value = {"available": True, "matches": []}
    assert not await service._evidence_accessible(None, evidence, "u", "org")
