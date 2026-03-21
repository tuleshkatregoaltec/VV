"""Browser-like HTTP client using curl_cffi with retry and failure artifacts."""

from __future__ import annotations

from collections.abc import Mapping

from curl_cffi import requests as curl_requests
from dagster import ConfigurableResource
from pydantic import PrivateAttr
from tenacity import retry, stop_after_attempt, wait_exponential

from holocron.scrape.diagnostics import DiagnosticsCollector


class BrowserlikeHTTPClient(ConfigurableResource):
    timeout_seconds: float = 30.0
    follow_redirects: bool = True
    impersonate: str = "chrome124"
    proxy: str = ""

    _client_instance: object = PrivateAttr(default=None)

    def client(self):
        if self._client_instance is None:
            self._client_instance = curl_requests.Session(
                timeout=self.timeout_seconds,
                impersonate=self.impersonate,
            )
        return self._client_instance

    def _effective_proxy(self, proxy: str | None) -> str:
        return (proxy or self.proxy).strip()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get(
        self,
        url: str,
        *,
        proxy: str | None = None,
        diagnostics: DiagnosticsCollector | None = None,
        failure_label: str = "",
        headers: Mapping[str, str] | None = None,
        **kwargs,
    ):
        effective_proxy = self._effective_proxy(proxy)
        request_kwargs = dict(kwargs)
        if headers is not None:
            request_kwargs["headers"] = dict(headers)

        try:
            if effective_proxy:
                request_kwargs["proxy"] = effective_proxy
            request_kwargs.setdefault("allow_redirects", self.follow_redirects)
            response = self.client().get(url, **request_kwargs)
            response.raise_for_status()
            return response
        except Exception as exc:
            if diagnostics is not None and diagnostics.enabled:
                response = getattr(exc, "response", None)
                body = None
                status = None
                response_headers = None
                if response is not None:
                    body = getattr(response, "content", None) or getattr(response, "text", None)
                    status = getattr(response, "status_code", None)
                    response_headers = getattr(response, "headers", None)
                diagnostics.capture_failure(
                    label=failure_label or "http_failure",
                    url=url,
                    status=status,
                    headers=response_headers,
                    body=body,
                    error=str(exc),
                    metadata={"proxy": effective_proxy, "impersonate": self.impersonate},
                )
            raise
