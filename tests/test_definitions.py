from dagster import Definitions

from holocron.definitions import defs


def test_definitions_validate_loadable() -> None:
    Definitions.validate_loadable(defs)
