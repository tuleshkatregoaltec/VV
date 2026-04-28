from datetime import UTC, datetime

from holocron.contracts import BronzeTable, RawFile, SilverTable, SourceSpec
from holocron.platform.execution import build_raw_release


def _extract() -> None:
    return None


def test_build_raw_release_shapes_core_manifest_fields() -> None:
    source = SourceSpec(
        name="example_source",
        provider="example",
        extractor=_extract,
        bronze_tables=(BronzeTable(name="example_bronze"),),
        silver_tables=(SilverTable(name="example_silver"),),
    )
    release = build_raw_release(
        source=source,
        files=(RawFile(path="rows.jsonl", sha256="abc", size_bytes=42),),
        now=datetime(2026, 3, 31, 12, 0, tzinfo=UTC),
    )

    assert release.source == "example_source"
    assert release.run_id == "2026-03-31T12-00-00Z"
    assert release.extract_date == "2026-03-31"
    assert release.files[0].path == "rows.jsonl"
