"""The assistant reuses the conversation tables an earlier assistant created (c51b90aa7f42), so
its migration must change them in place, not create them again."""

import subprocess
from pathlib import Path

from app.crm.assistant.models import (
    CrmAssistantAction,
    CrmAssistantConversation,
    CrmAssistantMessage,
)

BACKEND = Path(__file__).parents[3]


def _upgrade_sql() -> str:
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "b6d8f0a2c4e1:c3e5a7b9d1f2", "--sql"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_migration_keeps_existing_tables_and_adds_actions():
    sql = _upgrade_sql()
    assert "CREATE TABLE crm_assistant_conversations" not in sql
    assert "CREATE TABLE crm_assistant_messages" not in sql
    assert "ALTER TABLE crm_assistant_messages RENAME sources TO meta_data" in sql
    assert "CREATE TABLE crm_assistant_actions" in sql


def test_models_match_the_tables_already_in_the_database():
    messages = CrmAssistantMessage.__table__
    assert "meta_data" in messages.c and "sources" not in messages.c
    assert {index.name for index in messages.indexes} == {"ix_crm_assistant_message_order"}

    conversations = CrmAssistantConversation.__table__
    assert conversations.c.title.nullable is False
    assert {index.name for index in conversations.indexes} == {
        "ix_crm_assistant_conversations_organization_id",
        "ix_crm_assistant_conversations_user_id",
        "ix_crm_assistant_conversation_owner",
        "ix_crm_assistant_conversation_updated_at",
    }
    assert CrmAssistantAction.__table__.name == "crm_assistant_actions"
