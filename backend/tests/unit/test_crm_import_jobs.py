"""Queue/list and worker limits encode the bounded durable execution contract."""

import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.crm import import_worker, imports
from app.crm.import_job_models import utcnow
from app.crm.import_models import CrmContactImport, CrmContactList


async def test_import_history_fetches_lists_once_and_preserves_known_missing_lists(monkeypatch):
    records = [
        CrmContactImport(
            id=i,
            organization_id="tenant",
            created_by_user_id="user",
            name=f"Import {i}",
            original_filename="input.csv",
            sha256=str(i),
            size_bytes=10,
            status="queued",
            mapping={},
            summary={},
            created_at=utcnow(),
        )
        for i in range(1, 4)
    ]
    contact_list = CrmContactList(
        id=10,
        source_import_id=2,
        organization_id="tenant",
        created_by_user_id="user",
        name="Import 2",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    monkeypatch.setattr(imports.import_repository, "list_imports", AsyncMock(return_value=records))
    prefetch = AsyncMock(return_value=[contact_list])
    monkeypatch.setattr(imports.import_repository, "lists_for_imports", prefetch)
    fallback = AsyncMock(side_effect=AssertionError("N+1 list lookup"))
    monkeypatch.setattr(imports.import_repository, "find_import_list", fallback)
    responses = await imports.list_contact_imports(None, organization_id="tenant")
    assert [response.list_id for response in responses] == [None, 10, None]
    prefetch.assert_awaited_once_with(None, "tenant", [1, 2, 3])
    fallback.assert_not_awaited()


@pytest.mark.parametrize(
    "option,value",
    [
        ("--memory-mib", "0"),
        ("--wall-seconds", "0"),
        ("--lease-seconds", "0"),
        ("--poll-seconds", "0"),
    ],
)
def test_worker_rejects_unbounded_configuration_before_launch(monkeypatch, option, value):
    monkeypatch.setattr("sys.argv", ["worker", "--once", option, value])
    launch = Mock(side_effect=AssertionError("Invalid config started a process"))
    monkeypatch.setattr(import_worker.subprocess, "run", launch)
    with pytest.raises(SystemExit) as error:
        import_worker.main()
    assert error.value.code == 2
    launch.assert_not_called()


def test_worker_supervisor_bounds_child_wall_and_propagates_resource_budget(monkeypatch):
    monkeypatch.setattr(
        "sys.argv", ["worker", "--once", "--wall-seconds", "30", "--memory-mib", "1024"]
    )
    launch = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(import_worker.subprocess, "run", launch)
    assert import_worker.main() == 0
    args, kwargs = launch.call_args
    command = args[0]
    assert command[command.index("--memory-mib") + 1] == "1024"
    assert "--execute-one" in command
    assert kwargs["timeout"] == 30


def test_worker_timeout_is_reported_as_failure_in_finite_mode(monkeypatch):
    monkeypatch.setattr("sys.argv", ["worker", "--once"])
    monkeypatch.setattr(
        import_worker.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("worker", 1800))
    )
    assert import_worker.main() == 1
