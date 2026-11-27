import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.crm.assistant import crm_tools, query_my_records
from app.crm.assistant.dependencies import ChatDependencies
from app.crm.assistant.models import CrmAssistantQuery
from app.crm.assistant.workflows import crm_agent as agent


@pytest.fixture(autouse=True)
def fixed_view(monkeypatch):
    """Reads without rows record the role's view from the database; these sessions are fakes."""

    async def view(db, **identity):
        return "view"

    monkeypatch.setattr(crm_tools.assistant, "view_signature", view)


@pytest.mark.parametrize("identity", ["user_id", "organization_id", "role", "sql"])
def test_crm_tool_rejects_identity_role_and_sql_overrides(identity):
    tool = agent._function_toolset.tools["query_my_crm_records"]
    with pytest.raises(ValidationError):
        tool.function_schema.validator.validate_python({"resource": "leads", identity: "forged"})


@pytest.mark.parametrize("fields", [{"limit": 51}, {"offset": -1}, {"resource": "users"}])
def test_crm_tool_rejects_unbounded_or_unapproved_requests(fields):
    with pytest.raises(ValidationError):
        CrmAssistantQuery.model_validate({"resource": "leads", **fields})


async def test_crm_without_trusted_identity_cannot_open_database(monkeypatch):
    def unexpected():
        raise AssertionError("Missing identity must fail before opening a database session")

    monkeypatch.setattr(crm_tools, "get_db_session", unexpected)
    result = await crm_tools.query_my_crm_records(
        SimpleNamespace(deps=None), CrmAssistantQuery(resource="leads")
    )
    assert result["available"] is False
    with pytest.raises(ValueError):
        ChatDependencies(user_id="", organization_id="org")
    with pytest.raises(ValueError):
        await query_my_records(
            None, CrmAssistantQuery(resource="leads"), user_id="user", organization_id=""
        )


async def test_unsupported_matches_are_unavailable_rather_than_zero():
    # Deals are readable now (see test_assistant_crm_role_parity); matching still is not, and
    # an unsupported read must never look like "you have none".
    result = await query_my_records(
        None, CrmAssistantQuery(resource="matches"), user_id="user", organization_id="org"
    )
    assert result.available is False and result.total is None
    assert result.records == []


async def test_parallel_paging_has_one_shared_private_detail_budget(monkeypatch):
    from app.crm.assistant.models import CrmAssistantResult

    async def session():
        yield None

    calls = []

    async def read(db, request, **identity):
        calls.append(request)
        await asyncio.sleep(0)
        return CrmAssistantResult(
            resource=request.resource,
            limit=request.limit,
            offset=request.offset,
            total=1000,
            records=[]
            if request.summary_only
            else [
                {"id": request.offset + i + 1, "phone": "+971501234567"}
                for i in range(request.limit)
            ],
        )

    monkeypatch.setattr(crm_tools, "get_db_session", session)
    monkeypatch.setattr(crm_tools.assistant, "query_my_records", read)
    context = SimpleNamespace(deps=ChatDependencies("u", "org"))
    results = await asyncio.gather(
        *(
            crm_tools.query_my_crm_records(
                context,
                CrmAssistantQuery(
                    resource="leads", include_contact_details=True, limit=50, offset=index * 50
                ),
            )
            for index in range(4)
        )
    )
    assert sum(len(result.get("records", [])) for result in results) == 10
    assert len(calls) == 1 and calls[0].limit == 10
    summary = await crm_tools.query_my_crm_records(
        context, CrmAssistantQuery(resource="leads", summary_only=True)
    )
    assert summary["total"] == 1000 and summary["records"] == []


async def test_empty_search_returns_unused_private_detail_budget(monkeypatch):
    from app.crm.assistant.models import CrmAssistantResult

    async def session():
        yield None

    async def read(db, request, **identity):
        return CrmAssistantResult(resource="leads", limit=request.limit, offset=0, total=0)

    monkeypatch.setattr(crm_tools, "get_db_session", session)
    monkeypatch.setattr(crm_tools.assistant, "query_my_records", read)
    context = SimpleNamespace(deps=ChatDependencies("u", "org"))
    await crm_tools.query_my_crm_records(
        context, CrmAssistantQuery(resource="leads", search="No match")
    )
    assert context.deps.retrieval_budget["crm_detail_rows"] == 10


def _counting_reader(monkeypatch, fail_first=False):
    from app.crm.assistant.models import CrmAssistantResult

    async def session():
        yield None

    calls = []

    async def read(db, request, **identity):
        calls.append(request)
        if fail_first and len(calls) == 1:
            raise RuntimeError("database unavailable")
        return CrmAssistantResult(
            resource=request.resource,
            limit=request.limit,
            offset=request.offset,
            total=7,
            records=[] if request.summary_only else [{"id": 1}, {"id": 2}],
        )

    monkeypatch.setattr(crm_tools, "get_db_session", session)
    monkeypatch.setattr(crm_tools.assistant, "query_my_records", read)
    return calls


async def test_identical_crm_read_in_one_turn_is_reused_not_repeated(monkeypatch):
    """A repeated identical query (retry or second workflow) showed as another
    "records ready" line, re-read the database, re-spent the detail budget and
    duplicated evidence. It must reuse the first result and say so in progress."""
    calls = _counting_reader(monkeypatch)
    events = []
    deps = ChatDependencies("u", "org", progress=events.append)
    query = CrmAssistantQuery(resource="leads", status="new", limit=5)

    first = await crm_tools.query_my_crm_records(
        SimpleNamespace(deps=deps, tool_call_id="a"), query
    )
    again = await crm_tools.query_my_crm_records(
        SimpleNamespace(deps=deps, tool_call_id="b"), query.model_copy()
    )
    assert again == first and len(calls) == 1
    assert len(deps.evidence) == 1
    assert deps.retrieval_budget["crm_detail_rows"] == 10 - 2
    results = [event for event in events if event["type"] == "tool_call_result"]
    assert [event.get("cached", False) for event in results] == [False, True]


@pytest.mark.parametrize(
    "different",
    [
        {"status": "contacted"},
        {"assignment": "mine"},
        {"offset": 5},
        {"summary_only": True},
        {"include_contact_details": True},
        {"resource": "renewals"},
    ],
)
async def test_crm_reads_differing_in_any_argument_stay_distinct(monkeypatch, different):
    """Progress events carry only the tool name; distinct filters or scopes must still be read."""
    calls = _counting_reader(monkeypatch)
    events = []
    deps = ChatDependencies("u", "org", progress=events.append)
    base = {"resource": "leads", "status": "new", "limit": 5}
    for fields in (base, {**base, **different}):
        await crm_tools.query_my_crm_records(
            SimpleNamespace(deps=deps, tool_call_id=str(fields)), CrmAssistantQuery(**fields)
        )
    assert len(calls) == 2 and len(deps.evidence) == 2
    assert not any(event.get("cached") for event in events)


async def test_failed_crm_read_is_retried_rather_than_reused(monkeypatch):
    calls = _counting_reader(monkeypatch, fail_first=True)
    deps = ChatDependencies("u", "org")
    query = CrmAssistantQuery(resource="leads", summary_only=True)
    failed = await crm_tools.query_my_crm_records(SimpleNamespace(deps=deps), query)
    assert failed["available"] is False and "total" not in failed
    retried = await crm_tools.query_my_crm_records(SimpleNamespace(deps=deps), query)
    assert retried["total"] == 7 and len(calls) == 2


async def test_parallel_identical_crm_reads_share_one_database_read(monkeypatch):
    calls = _counting_reader(monkeypatch)
    deps = ChatDependencies("u", "org")
    query = CrmAssistantQuery(resource="leads", limit=5)
    results = await asyncio.gather(
        *(crm_tools.query_my_crm_records(SimpleNamespace(deps=deps), query) for _ in range(3))
    )
    assert len(calls) == 1 and len(deps.evidence) == 1
    assert all(result == results[0] for result in results)


async def test_status_summaries_differing_only_in_paging_are_one_read(monkeypatch):
    """Stored turns showed the model asking for the same status summary with limit 1, 20 or 50.
    A summary returns no rows, so each repeat was a fresh read and another progress line.
    One summary per filter set; a different status or assignment filter is still its own read."""
    calls = _counting_reader(monkeypatch)
    events = []
    deps = ChatDependencies("u", "org", progress=events.append)
    variants = [
        {"limit": 50},
        {"limit": 1},
        {"limit": 20, "offset": 40},
        {"include_contact_details": True},
        {"assignment": "unassigned"},
        {"status": "new"},
    ]
    for index, fields in enumerate(variants):
        await crm_tools.query_my_crm_records(
            SimpleNamespace(deps=deps, tool_call_id=str(index)),
            CrmAssistantQuery(resource="leads", summary_only=True, **fields),
        )
    assert [(call.assignment, call.status) for call in calls] == [
        (None, None),
        ("unassigned", None),
        (None, "new"),
    ]
    assert len(deps.evidence) == 3
    results = [event for event in events if event["type"] == "tool_call_result"]
    assert [event.get("cached", False) for event in results] == [
        False,
        True,
        True,
        True,
        False,
        False,
    ]
    # The detail budget is untouched by summaries, however they were paged.
    assert deps.retrieval_budget["crm_detail_rows"] == 10
