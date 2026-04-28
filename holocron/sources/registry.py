from __future__ import annotations

from holocron.contracts import SourceSpec


class SourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, SourceSpec] = {}

    def register(self, source: SourceSpec) -> None:
        if source.name in self._sources:
            raise ValueError(f"Duplicate source: {source.name}")
        self._sources[source.name] = source

    def get(self, name: str) -> SourceSpec:
        try:
            return self._sources[name]
        except KeyError as exc:
            raise KeyError(f"Unknown source: {name}") from exc

    def all(self) -> tuple[SourceSpec, ...]:
        return tuple(self._sources.values())
