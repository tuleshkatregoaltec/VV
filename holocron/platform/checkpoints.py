from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class JsonCheckpointStore(Protocol):
    def get_json(self, *, key: str) -> dict[str, Any] | None: ...

    def put_json(self, *, key: str, payload: dict[str, Any]) -> None: ...


def checkpoint_s3_key(*, source: str, operation: str) -> str:
    return f"state/source={source}/operation={operation}.json"


def read_checkpoint(
    store: JsonCheckpointStore,
    *,
    source: str,
    operation: str,
) -> dict[str, Any] | None:
    checkpoint = store.get_json(key=checkpoint_s3_key(source=source, operation=operation))
    if checkpoint is None:
        return None
    if not isinstance(checkpoint, dict):
        raise TypeError(
            f"Checkpoint for source={source} operation={operation} must be a JSON object"
        )
    return checkpoint


def write_checkpoint(
    store: JsonCheckpointStore,
    *,
    source: str,
    operation: str,
    payload: Mapping[str, Any],
) -> None:
    store.put_json(
        key=checkpoint_s3_key(source=source, operation=operation),
        payload=dict(payload),
    )
