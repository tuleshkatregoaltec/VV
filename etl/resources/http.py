"""HTTP client resource using httpx with retry logic."""

from __future__ import annotations

from contextlib import contextmanager

import httpx
from dagster import ConfigurableResource
from tenacity import retry, stop_after_attempt, wait_exponential


class HttpClientResource(ConfigurableResource):
    timeout_seconds: float = 30.0
    follow_redirects: bool = True

    def client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=self.follow_redirects,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get(self, url: str, **kwargs) -> httpx.Response:
        with self.client() as c:
            resp = c.get(url, **kwargs)
            resp.raise_for_status()
            return resp

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def post(self, url: str, **kwargs) -> httpx.Response:
        with self.client() as c:
            resp = c.post(url, **kwargs)
            resp.raise_for_status()
            return resp
