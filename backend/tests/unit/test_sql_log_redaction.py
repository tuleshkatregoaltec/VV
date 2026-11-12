import io
import logging
import logging.config

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql.util import _repr_params
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.postgres.models  # noqa: F401 - registers every table
from app.core.log_redaction import RedactSqlParameters
from app.core.logging_config import LOGGING_CONFIG
from app.crm import collections
from app.crm.collection_models import CollectionCreate, CrmCollection
from app.crm.collections import CollectionActor
from app.organization.models import Organization

TOKEN = "GCQiLwRLcX7VAY137YcbECvhQvlxy97E1te3Fwhm-6I"
assert len(TOKEN) == 43


@pytest.fixture
def sql_output():
    """The sqlalchemy.engine logger as configured for sql.log, writing to a buffer."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(LOGGING_CONFIG["formatters"]["default"]["format"]))
    handler.addFilter(RedactSqlParameters())
    logger = logging.getLogger("sqlalchemy.engine")
    old_level, old_handlers, old_prop = logger.level, logger.handlers[:], logger.propagate
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    yield stream
    logger.handlers, logger.propagate = old_handlers, old_prop
    logger.setLevel(old_level)


def test_configured_sql_handler_has_the_filter():
    assert "redact_sql_params" in LOGGING_CONFIG["handlers"]["file_sql"]["filters"]
    assert LOGGING_CONFIG["filters"]["redact_sql_params"]["()"] == (
        "app.core.log_redaction.RedactSqlParameters"
    )


@pytest.mark.parametrize(
    "params",
    [
        ("u1", TOKEN),
        ["u1", TOKEN],
        {"user": "u1", "token": TOKEN},
        [("u1", TOKEN), ("u2", "other")],
        [{"user": "u1", "token": TOKEN}],
    ],
)
@pytest.mark.parametrize("wrap", [False, True])
def test_engine_record_params_are_redacted(sql_output, params, wrap):
    ismulti = isinstance(params, list) and bool(params) and isinstance(params[0], (tuple, dict))
    arg = _repr_params(params, batches=10, ismulti=ismulti) if wrap else params
    logging.getLogger("sqlalchemy.engine.Engine").info("[%s] %r", "generated in 0.1s", arg)
    for handler in logging.getLogger("sqlalchemy.engine").handlers:
        handler.flush()
    out = sql_output.getvalue()
    assert TOKEN not in out
    assert "[redacted]" in out
    assert "u1" in out


async def test_real_collection_create_never_logs_the_token(sql_output):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Organization(id="org-a", name="org-a"))
        await session.commit()
        actor = CollectionActor("alice", "org-a", False, "Alice", "alice@example.com")
        created = await collections.create_collection(
            session, actor=actor, payload=CollectionCreate(name="Picks")
        )
        row = (
            await session.exec(select(CrmCollection).where(CrmCollection.id == created.id))
        ).one()
        token = row.share_token
    await engine.dispose()

    out = sql_output.getvalue()
    assert "INSERT INTO crm_collection" in out
    # The row's real token is what must not appear.
    assert len(token) == 43 and token not in out
    assert "[redacted]" in out
