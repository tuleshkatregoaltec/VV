import unittest

from dagster import Definitions

from holocron.definitions import defs


class DefinitionsTest(unittest.TestCase):
    def test_definitions_validate_loadable(self) -> None:
        Definitions.validate_loadable(defs)


if __name__ == "__main__":
    unittest.main()
