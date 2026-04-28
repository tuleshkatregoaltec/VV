import pytest

from holocron.contracts import SourceSpec
from holocron.sources.registry import SourceRegistry


def _extract() -> None:
    return None


def test_registry_registers_and_returns_sources() -> None:
    registry = SourceRegistry()
    source = SourceSpec(name="example_source", provider="example", extractor=_extract)

    registry.register(source)

    assert registry.get("example_source") is source
    assert registry.all() == (source,)


def test_registry_rejects_duplicate_source_names() -> None:
    registry = SourceRegistry()
    source = SourceSpec(name="example_source", provider="example", extractor=_extract)

    registry.register(source)

    with pytest.raises(ValueError, match="Duplicate source"):
        registry.register(source)
