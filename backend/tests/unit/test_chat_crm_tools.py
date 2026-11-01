import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.chat import crm_tools
from app.chat.dependencies import ChatDependencies
from app.chat.workflows import crm_agent as agent
from app.crm.assistant import query_my_records
from app.crm.assistant_models import CrmAssistantQuery


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


async def test_unpersisted_deals_are_unavailable_rather_than_zero():
    result = await query_my_records(
        None, CrmAssistantQuery(resource="deals"), user_id="user", organization_id="org"
    )
    assert result.available is False and result.total is None
    assert result.records == []


async def test_parallel_paging_has_one_shared_private_detail_budget(monkeypatch):
    from app.crm.assistant_models import CrmAssistantResult

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
    from app.crm.assistant_models import CrmAssistantResult

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
