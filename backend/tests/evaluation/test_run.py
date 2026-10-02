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


async def test_explicit_alternative_dataset_is_selected_before_any_server_or_login(
    monkeypatch, tmp_path
):
    from decimal import Decimal

    import pytest

    from app.config import settings
    from scripts.evaluation import run
    from scripts.evaluation.dataset import BENCHMARK

    for name, value in {
        "ENVIRONMENT": "local",
        "AI_PRICING_MODEL": settings.DEFAULT_CHAT_MODEL,
        "AI_INPUT_USD_PER_MILLION": Decimal("0.25"),
        "AI_OUTPUT_USD_PER_MILLION": Decimal("1.50"),
        "FIRST_SUPERUSER": "offline@example.invalid",
        "FIRST_SUPERUSER_PASSWORD": "offline-test-only",
        "AUTH_URL": "http://127.0.0.1:9",
    }.items():
        monkeypatch.setattr(settings, name, value)

    def no_start(*_args, **_kwargs):
        pytest.fail("Unknown case selection must stop before creating a run or starting a server")

    monkeypatch.setattr(run, "private_directory", no_start)
    for dataset, case_ids in (
        (BENCHMARK.with_name("scope_heldout.json"), ["q01"]),
        (None, ["q101"]),
    ):
        with pytest.raises(ValueError, match="Unknown/empty case selection"):
            await run.run_benchmark(
                directory=tmp_path / "must-not-exist",
                case_ids=case_ids,
                dataset_path=dataset,
                max_spend_usd="0.01",
            )
    assert not (tmp_path / "must-not-exist").exists()


def test_cli_forwards_explicit_dataset_without_mutating_the_canonical_default(monkeypatch):
    import sys
    from unittest.mock import AsyncMock

    from scripts.evaluation import __main__, run

    execute = AsyncMock()
    monkeypatch.setattr(run, "run_benchmark", execute)
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluation", "run", "--dataset", "scope_heldout.json", "--budget-usd", "0.01"],
    )
    __main__.main()
    assert execute.call_args.kwargs["dataset_path"] == "scope_heldout.json"
    assert execute.call_args.kwargs["max_spend_usd"] == "0.01"
