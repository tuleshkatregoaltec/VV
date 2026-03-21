"""Shared browser runtime helpers for scrape-oriented sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import time
from urllib.parse import urlparse

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


def launch_browser(
    playwright,
    *,
    chrome_path: str,
    source_name: str,
    headless: bool = True,
    proxy: str = "",
    args: list[str] | None = None,
):
    launch_kwargs: dict[str, object] = {
        "executable_path": resolve_browser_executable(chrome_path, source_name=source_name),
        "headless": headless,
        "args": args or ["--disable-blink-features=AutomationControlled"],
    }
    if proxy.strip():
        launch_kwargs["proxy"] = _parse_proxy(proxy)
    return playwright.chromium.launch(**launch_kwargs)


def _parse_proxy(proxy: str) -> dict:
    """Parse a proxy URL into Playwright's proxy dict format.

    Playwright requires credentials as separate fields, not embedded in the URL.
    Accepts: http://user:pass@host:port or http://host:port
    """
    parsed = urlparse(proxy.strip())
    proxy_dict: dict = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        proxy_dict["username"] = parsed.username
    if parsed.password:
        proxy_dict["password"] = parsed.password
    return proxy_dict


@dataclass
class AdaptiveBackoff:
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    consecutive_signals: int = 0

    def current_delay_seconds(self) -> float:
        if self.consecutive_signals <= 0:
            return 0.0
        return min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** (self.consecutive_signals - 1)),
        )

    def before_request(self) -> None:
        delay = self.current_delay_seconds()
        if delay > 0:
            time.sleep(delay)

    def record_signal(self) -> None:
        self.consecutive_signals += 1

    def record_success(self) -> None:
        self.consecutive_signals = 0
