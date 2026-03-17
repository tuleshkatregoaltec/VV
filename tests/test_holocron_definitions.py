import unittest

from dagster import Definitions

from holocron.definitions import defs
from holocron.sources import SOURCES


class HolocronDefinitionsTest(unittest.TestCase):
    def test_definitions_validate_loadable(self) -> None:
        Definitions.validate_loadable(defs)

    def test_source_jobs_exist(self) -> None:
        for source in SOURCES:
            self.assertIsNotNone(defs.resolve_job_def(source.ingest_job_name))


if __name__ == "__main__":
    unittest.main()
