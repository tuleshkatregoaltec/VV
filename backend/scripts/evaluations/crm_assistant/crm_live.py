"""Optional live-model layer: real CRM Assistant turns against the synthetic fixture.

Preview by default: prints the plan (cases, configured models) and calls nothing. A live run
needs all of:
- `--live` on the command line and CRM_EVAL_ALLOW_MODEL_CALLS=1 (two separate opt-ins; each
  turn is a paid model-provider call);
- CRM_EVAL_POSTGRES_URL pointing at a local PostgreSQL. The run creates its own database there
  (`vv_crm_eval_<random>`), migrates it, seeds a fresh fixture copy per case and drops it at the
  end. It never uses .env.dev's database;
- the application's own POSTGRES_URL local as well, so no unpatched path can reach a shared
  database.

Each turn goes through the production chat turn (input guard, routing, tools, output guards,
proposal rechecks) with only admission (Redis/billing) replaced and "today" fixed to the
fixture's reference date. Outbound HTTP is blocked except to the model provider; Brevo and
Google Calendar report themselves unconfigured. Proposals are never confirmed here:
confirmation is the user's act, and the database-integration layer covers it.

Evidence (`.evaluation/crm_assistant/<UTC time>/`, private files): the summary and per-case
check results, with case IDs, tool names, proposal kinds and statuses only. Answer text, which
holds only synthetic fixture data, is written for human review only with `--save-answers`.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from scripts.evaluations.crm_assistant import crm_fixture as fixture
from scripts.evaluations.crm_assistant.crm_dataset import ActionProbe, CrmCase
from scripts.evaluations.crm_assistant.crm_probes import isolated_side_effects, observe
from scripts.evaluations.crm_assistant.crm_report import (
    CaseResult,
    Check,
    as_record,
    safe_error,
    summarize,
)
from scripts.evaluations.crm_assistant.crm_scoring import Observation, score

ALLOW_ENV = "CRM_EVAL_ALLOW_MODEL_CALLS"
DATABASE_ENV = "CRM_EVAL_POSTGRES_URL"
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
MODEL_HOSTS = frozenset({"openrouter.ai"})
ROOT = Path(__file__).resolve().parents[3]
ROLES = ("coordinator", "router", "crm", "followup", "action")


def _host(url: str | None) -> str | None:
    from sqlalchemy.engine import make_url

    try:
        return make_url(url).host if url else None
    except Exception:
        return None


def gate_errors(environ, app_database_url: str) -> list[str]:
    """Why a live run may not start; empty when every opt-in and safety condition holds."""
    errors = []
    if environ.get(ALLOW_ENV) != "1":
        errors.append(f"Set {ALLOW_ENV}=1 to allow paid model-provider calls")
    if _host(environ.get(DATABASE_ENV)) not in LOOPBACK:
        errors.append(f"Set {DATABASE_ENV} to a local PostgreSQL (localhost)")
    if _host(app_database_url) not in LOOPBACK:
        errors.append("POSTGRES_URL must be local; never run against .env.dev's database")
    return errors


def plan(cases: list[CrmCase]) -> dict:
    from app.config import settings

    return {
        "layer": "live_model",
        "cases": len(cases),
        "case_ids": [case.id for case in cases],
        "turns": len(cases),
        "models": {role: getattr(settings, f"ASSISTANT_{role.upper()}_MODEL") for role in ROLES},
        "typed_routing": settings.ASSISTANT_TYPED_ROUTING_ENABLED,
        "confirmations": "never (covered by the database-integration layer)",
    }


@contextlib.asynccontextmanager
async def disposable_database(server_url: str):
    """A fresh, migrated database on a local server, dropped afterwards."""
    import asyncpg
    from sqlalchemy.engine import make_url

    url = make_url(server_url)
    if url.host not in LOOPBACK:
        raise RuntimeError("The live evaluation only creates databases on a local server")
    name = "vv_crm_eval_" + uuid.uuid4().hex
    admin = url.set(drivername="postgresql", database="postgres")
    connection = await asyncpg.connect(admin.render_as_string(hide_password=False))
    try:
        await connection.execute(f'CREATE DATABASE "{name}"')
        target = url.set(drivername="postgresql+asyncpg", database=name)
        rendered = target.render_as_string(hide_password=False)
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env={**os.environ, "POSTGRES_URL": rendered},
            check=True,
            capture_output=True,
            text=True,
        )
        yield rendered
    finally:
        await connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await connection.close()


@contextlib.contextmanager
def turn_runtime():
    """Admission (Redis and billing) replaced; the assistant enabled; today fixed."""
    from unittest.mock import AsyncMock

    from app.crm.assistant import agent, routing, service, workflows

    today = lambda: fixture.REFERENCE_DATE  # noqa: E731
    lease = service.admission.TurnLease("crm-eval", service.settings.ASSISTANT_TURN_TOKEN_LIMIT)
    patches = [
        mock.patch.object(service.settings, "ASSISTANT_ENABLED", True),
        mock.patch.object(service.admission, "acquire", AsyncMock(return_value=lease)),
        mock.patch.object(service.admission, "finish", AsyncMock()),
        *(mock.patch.object(m, "business_today", today) for m in (agent, routing, workflows)),
    ]
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        yield


async def run_turn(db, seeded: fixture.Seeded, case: CrmCase, *, allowed_hosts=frozenset()):
    """One production chat turn as the case's actor; returns what the server recorded."""
    from app.chat.conversations import create_conversation
    from app.crm.assistant.service import stream_chat_response

    user_id, organization_id = seeded.people[case.actor], seeded.org_of(case.actor)
    with isolated_side_effects(db, seeded, allowed_hosts=allowed_hosts), turn_runtime():
        conversation = await create_conversation(db, user_id, organization_id)
        events = [
            json.loads(chunk.removeprefix("data: "))
            async for chunk in stream_chat_response(
                db, conversation.id, case.question, user_id, organization_id
            )
        ]
    observed = Observation(
        tools=[e["tool"] for e in events if e.get("type") == "tool_call_start"],
        proposals=[
            {"kind": e["action"].get("kind"), "status": e["action"].get("status")}
            for e in events
            if e.get("type") == "action_proposed"
        ],
        answer="".join(e.get("content", "") for e in events if e.get("type") == "content"),
        error=next((e.get("code") for e in events if e.get("type") == "error"), None),
    )
    observed.stored_actions = await observe(db, seeded, f"actions:{case.actor}", "count")
    if isinstance(case.probe, ActionProbe) and case.probe.state:
        observed.state_unchanged = all(
            [
                await observe(db, seeded, item.subject, item.field) == item.before
                for item in case.probe.state
            ]
        )
    return observed


def private_write(path: Path, value) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, indent=2, default=str, ensure_ascii=False)
        stream.write("\n")


async def run_live(cases: list[CrmCase], *, server_url: str, save_answers: bool) -> dict:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    results: list[CaseResult] = []
    answers = []
    async with disposable_database(server_url) as target:
        engine = create_async_engine(target)
        try:
            for case in cases:
                async with AsyncSession(engine, expire_on_commit=False) as db:
                    try:
                        seeded = await fixture.seed(db)
                        observed = await run_turn(db, seeded, case, allowed_hosts=MODEL_HOSTS)
                    except Exception as exc:
                        results.append(
                            CaseResult(
                                case.id,
                                "live_model",
                                "error",
                                [Check("turn_ran", False, safe_error(exc))],
                            )
                        )
                        continue
                results.append(score(case, observed))
                if save_answers:
                    answers.append({"case_id": case.id, "answer": observed.answer})
        finally:
            await engine.dispose()
    summary = summarize("live_model", [case.id for case in cases], results)
    directory = (
        ROOT / ".evaluation" / "crm_assistant" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_write(directory / "summary.json", summary)
    private_write(directory / "results.json", [as_record(result) for result in results])
    if save_answers:
        private_write(directory / "answers_for_review.json", answers)
    summary["evidence"] = str(directory.relative_to(ROOT))
    return summary
