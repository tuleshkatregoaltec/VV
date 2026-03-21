"""Failure artifact helpers for HTTP and browser scrapers."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from collections.abc import Mapping
from typing import Any


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-")
    return cleaned or "artifact"


def _artifact_stem(label: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{_slug(label)}-{timestamp}"


class DiagnosticsCollector:
    def __init__(
        self,
        *,
        root_dir: str = "",
        source_name: str,
        release_id: str = "",
    ) -> None:
        self.root_dir = root_dir.strip()
        self.source_name = source_name
        self.release_id = release_id.strip()

    @property
    def enabled(self) -> bool:
        return bool(self.root_dir)

    def _run_dir(self) -> Path | None:
        if not self.enabled:
            return None
        timestamp = self.release_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = Path(self.root_dir) / self.source_name / timestamp
        path.mkdir(parents=True, exist_ok=True)
        return path

    def reserve_screenshot_path(self, label: str) -> Path | None:
        run_dir = self._run_dir()
        if run_dir is None:
            return None
        return run_dir / f"{_artifact_stem(label)}.png"

    def capture_failure(
        self,
        *,
        label: str,
        url: str = "",
        status: int | None = None,
        headers: Mapping[str, Any] | None = None,
        body: bytes | str | None = None,
        screenshot_path: Path | None = None,
        error: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> Path | None:
        run_dir = self._run_dir()
        if run_dir is None:
            return None

        stem = _artifact_stem(label)
        body_path: Path | None = None
        if body is not None:
            body_path = run_dir / f"{stem}.body"
            payload = body.encode("utf-8", errors="replace") if isinstance(body, str) else body
            body_path.write_bytes(payload)

        artifact = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "status": status,
            "headers": dict(headers or {}),
            "body_path": str(body_path) if body_path else "",
            "screenshot_path": str(screenshot_path) if screenshot_path else "",
            "error": error,
            "metadata": dict(metadata or {}),
        }
        artifact_path = run_dir / f"{stem}.json"
        artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
        return artifact_path
