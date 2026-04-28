"""Shared browser runtime helpers for scrape-oriented sources."""

from __future__ import annotations

from pathlib import Path
import shutil

DEFAULT_CHROMIUM_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)


def resolve_browser_executable(
    chrome_path: str,
    *,
    candidates: tuple[str, ...] = DEFAULT_CHROMIUM_CANDIDATES,
    source_name: str,
) -> str | None:
    candidate = chrome_path.strip()
    if candidate:
        resolved = shutil.which(candidate) if "/" not in candidate else candidate
        if resolved and Path(resolved).exists():
            return resolved
        raise FileNotFoundError(f"{source_name} browser executable not found: {chrome_path}")

    for name in candidates:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def browser_context_kwargs(
    *,
    user_agent: str,
    storage_state_path: str = "",
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "user_agent": user_agent,
        "viewport": {"width": 1440, "height": 900},
        "locale": "en-US",
        "timezone_id": "UTC",
    }
    if storage_state_path.strip():
        kwargs["storage_state"] = storage_state_path
    return kwargs
