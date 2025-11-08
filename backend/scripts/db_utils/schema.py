"""Database schema management utilities."""

import logging
from sqlalchemy import inspect, text
from sqlmodel import Session

from backend.app.database import engine
from backend.app.models import SQLModel

logger = logging.getLogger(__name__)


def migrate_schema() -> bool:
    """Update database schema to match current models without losing data."""
    logger.info("[migrate] Comparing database schema with models...\n")

    inspector = inspect(engine)
    metadata = SQLModel.metadata
    changes_made = False

    for table_name, table in metadata.tables.items():
        if not inspector.has_table(table_name):
            logger.info(f"  Creating new table: {table_name}")
            table.create(engine)
            changes_made = True
            continue

        existing_columns = {
            col["name"]: col for col in inspector.get_columns(table_name)
        }
        model_columns = {col.name: col for col in table.columns}

        for col_name, col in model_columns.items():
            if col_name not in existing_columns:
                logger.info(f"  Adding column {table_name}.{col_name}")

                col_type = col.type.compile(engine.dialect)
                nullable = "NULL" if col.nullable else "NOT NULL"
                default = ""
                if col.default is not None:
                    if hasattr(col.default, "arg"):
                        default = f" DEFAULT {col.default.arg}"

                with Session(engine) as session:
                    session.exec(
                        text(
                            f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type} {nullable}{default}"
                        )
                    )
                    session.commit()
                changes_made = True

        for col_name, col in model_columns.items():
            if col_name in existing_columns:
                existing_col = existing_columns[col_name]

                if col.nullable != existing_col["nullable"]:
                    action = "DROP NOT NULL" if col.nullable else "SET NOT NULL"
                    logger.info(
                        f"  Updating {table_name}.{col_name} to {'nullable' if col.nullable else 'non-nullable'}"
                    )

                    with Session(engine) as session:
                        session.exec(
                            text(
                                f"ALTER TABLE {table_name} ALTER COLUMN {col_name} {action}"
                            )
                        )
                        session.commit()
                    changes_made = True

    return changes_made


def clear_database(disable_fk_fn, enable_fk_fn) -> None:
    """Drop and recreate all database tables."""
    metadata = SQLModel.metadata

    disable_fk_fn()
    metadata.drop_all(engine)
    logger.info("  ✓ Dropped all tables")

    metadata.create_all(engine)
    logger.info("  ✓ Created all tables")
    enable_fk_fn()
