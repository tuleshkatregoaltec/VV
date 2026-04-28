"""HTTP client resource using httpx with retry logic."""

from __future__ import annotations

import httpx
from dagster import ConfigurableResource
from pydantic import PrivateAttr
from tenacity import retry, stop_after_attempt, wait_exponential


class HttpClientResource(ConfigurableResource):
    timeout_seconds: float = 30.0
    follow_redirects: bool = True

    _client_instance: object = PrivateAttr(default=None)

    def client(self) -> httpx.Client:
        if self._client_instance is None:
            self._client_instance = httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=self.follow_redirects,
            )
        return self._client_instance  # type: ignore[return-value]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get(self, url: str, **kwargs) -> httpx.Response:
        response = self.client().get(url, **kwargs)
        response.raise_for_status()
        return response
