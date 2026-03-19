import unittest

from holocron.framework.models import LocalFileArtifact, LocalReleaseManifest
from holocron.framework.runner import manifest_config_metadata, promote_local_source


class _FakeContext:
    class _Log:
        def info(self, _message: str) -> None:
            return None

    log = _Log()


class _FakeSource:
    name = "bay_transactions"
    source = "bayut.com"
    mode = "reference_replace"


class _FakeS3:
    def __init__(self) -> None:
        self.uploads = []
        self.json_puts = []

    def upload_file(self, local_path, s3_key) -> None:
        self.uploads.append((str(local_path), s3_key))

    def put_json(self, key: str, payload: str) -> None:
        self.json_puts.append((key, payload))


class RunnerManifestTest(unittest.TestCase):
    def test_manifest_config_metadata_copies_effective_config(self) -> None:
        config = {"start_date": "2026-03-01", "end_date": "2026-03-18", "lookback_days": 3}
        self.assertEqual(manifest_config_metadata(config), config)

    def test_promote_local_source_preserves_local_manifest_metadata(self) -> None:
        artifact = LocalFileArtifact(
            name="sales.csv",
            local_path=__file__,
            size_bytes=1,
            sha256="abc",
            row_count=0,
            table_name="bay_sale_transactions",
        )
        local_release = LocalReleaseManifest(
            dataset="bay_transactions",
            release_id="bay-release",
            mode="reference_replace",
            source="bayut.com",
            created_at="2026-03-18T00:00:00+00:00",
            root_path="/tmp/bay-release",
            files=[artifact],
            metadata={"config": {"start_date": "2026-03-01", "end_date": "2026-03-18"}},
        )

        manifest = promote_local_source(
            context=_FakeContext(),
            source=_FakeSource(),
            local_release=local_release,
            s3=_FakeS3(),
        )

        self.assertEqual(manifest.metadata["local_root_path"], "/tmp/bay-release")
        self.assertEqual(manifest.metadata["local_file_count"], 1)
        self.assertEqual(
            manifest.metadata["config"],
            {"start_date": "2026-03-01", "end_date": "2026-03-18"},
        )


if __name__ == "__main__":
    unittest.main()
