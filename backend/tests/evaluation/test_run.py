import json

import httpx

from scripts.evaluation.dataset import Case
from scripts.evaluation.run import execute_case


async def test_explicit_binding_reaches_stream_and_persistence_without_changing_template():
    case = Case(id="q16", title="Binding", question="Compare [building]", parameters=["building"])
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.url.path.endswith("/stream"):
            from uuid import UUID

            payload = json.loads(request.content)
            assert payload["message"] == "Compare Explicit Tower"
            assert UUID(payload["request_id"])
            return httpx.Response(
                200, text='data: {"type":"content","content":"Answer"}\n\ndata: {"type":"done"}\n\n'
            )
        if request.method == "POST":
            return httpx.Response(200, json={"id": "created-by-this-run"})
        return httpx.Response(
            200,
            json=[
                {"role": "user", "content": "Compare Explicit Tower"},
                {"role": "assistant", "content": "Answer"},
            ],
        )

    async with httpx.AsyncClient(
        base_url="http://localhost", transport=httpx.MockTransport(handle)
    ) as client:
        result = await execute_case(client, case, 5, {"building": "Explicit Tower"})
    assert result["completed"] is True
    assert result["parameters"] == {"building": "Explicit Tower"}
    assert result["unbound_parameters"] == []
    assert result["answer"] == "Answer"
    assert case.question == "Compare [building]"
    assert requests[-1].method == "DELETE"
    assert requests[-1].url.path.endswith("created-by-this-run")


async def test_stream_failure_still_cleans_up_only_its_created_conversation():
    calls = []

    def handle(request):
        calls.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.url.path.endswith("/stream"):
            return httpx.Response(403)
        return httpx.Response(200, json={"id": "owned-evaluation-conversation"})

    async with httpx.AsyncClient(
        base_url="http://localhost", transport=httpx.MockTransport(handle)
    ) as client:
        result = await execute_case(client, Case(id="q01", title="Failure", question="Question"), 5)
    assert not result["completed"]
    assert result["error_type"] == "HTTPStatusError"
    assert calls[-1].method == "DELETE"
    assert calls[-1].url.path.endswith("owned-evaluation-conversation")


async def test_live_run_cannot_start_without_explicit_budget_or_with_nonfinite_budget():
    import pytest

    from scripts.evaluation.run import run_benchmark

    for budget in (None, "NaN", "Infinity", "-1", "0"):
        with pytest.raises(ValueError, match="budget"):
            await run_benchmark(max_spend_usd=budget)
