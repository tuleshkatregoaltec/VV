from holocron.sources.registry import SourceRegistry
from holocron.sources.dxbi import SOURCE as DXBI_SOURCE

registry = SourceRegistry()

registry.register(DXBI_SOURCE)

__all__ = ["DXBI_SOURCE", "registry"]
