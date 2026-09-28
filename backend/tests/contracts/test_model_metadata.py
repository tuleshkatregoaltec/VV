import json
from pathlib import Path

from conftest import get_app
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import SQLModel


def table_contract():
    get_app()  # Register the exact current runtime models, including incidental imports.
    dialect = postgresql.dialect()
    return {
        table.name: {
            "ddl": str(CreateTable(table).compile(dialect=dialect)),
            "indexes": sorted(
                str(CreateIndex(index).compile(dialect=dialect)) for index in table.indexes
            ),
        }
        for table in sorted(SQLModel.metadata.tables.values(), key=lambda item: item.name)
    }


def test_postgres_models_preserve_schema():
    expected = json.loads((Path(__file__).parent / "fixtures/model_metadata.json").read_text())
    assert table_contract() == expected
