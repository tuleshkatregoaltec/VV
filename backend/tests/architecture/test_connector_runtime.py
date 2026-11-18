"""The deployed runtime remains the sole owner of assistant and WhatsApp state."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).parents[2]


def test_removed_prototypes_cannot_shadow_the_shared_assistant_or_register_tables():
    from sqlmodel import SQLModel

    import app.postgres.models  # noqa: F401 - register the managed runtime schema
    from app.crm import assistant

    assert Path(assistant.__file__).name == "assistant.py"
    assert callable(assistant.query_my_records)
    # Calendar and email were restored (lead-assignment scoped, user-bound Google sign-in,
    # migration f2b4d6e8a0c1); the assistant and WhatsApp prototypes stay removed.
    assert not any(
        table.startswith(("crm_assistant_", "crm_whatsapp_")) for table in SQLModel.metadata.tables
    )
    for name in ("assistant", "whatsapp"):
        source = BACKEND / "app" / "crm" / name
        assert not source.is_file()
        assert not list(source.rglob("*.py"))


def test_valuation_migration_extends_one_current_vv_history_without_prototype_tables():
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    assert len(scripts.get_heads()) == 1
    revisions = {revision.revision for revision in scripts.walk_revisions()}
    assert "b5e2c9a7d4f1" in revisions
    assert scripts.get_revision("b5e2c9a7d4f1").down_revision == "b6d2f8a4c1e7"
    assert not revisions & {
        "a2d5c7e9f104",
        "b6d8f0a2c4e1",
        "b7d2e9f4a1c3",
        "c3e5a7b9d1f2",
        "c4e1a8b7d2f9",
        "d8a3f1c5e7b9",
    }
